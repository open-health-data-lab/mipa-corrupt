"""Export the study's edit scripts in a form that can be shared, and prove each replays.

The corpora of Experiments 1, 2 and 3 were written by pre-release builds of
RobustEHR, which stored each typographical error as the whole word with one
letter changed. A ledger in that form holds the note's own words, one letter
off, and is not something to hand to a reader.

For every condition this rewrites the ledger with each replacement stored as its
minimal difference from the text it replaces (`robustehr.store.minimal_edit`),
copies the dose table unchanged, and then replays the rewritten ledger against
the clean notes and compares every note with the `output_sha256` the original
run recorded. A condition is written only if every note reproduces.

What is written per condition, under ``--out``:

    edits.jsonl     the edit script, minimal form
    dose.jsonl      the original dose table, byte for byte
    manifest.json   the original manifest, plus what this export did

Nothing here contains a span of a note. It is still derived from the corpus:
an offset says where a word was. See RobustEHR's ``docs/run-artifact.md`` for
what each operator's edits imply, and share under the corpus's terms.

Run from the data checkout, where the paths below resolve:

    python <repo>/release/export_ledgers.py \\
        --experiments data/experiments --notes data/golden_notes.csv \\
        --out data/release_ledgers
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from robustehr.edits import apply_edits
from robustehr.rng import sha256_text
from robustehr.store import EditRow, minimal_edit, read_doses, read_edits
from robustehr.version import __version__

#: The experiments the paper reports, and where each keeps its conditions.
EXPERIMENTS = ("exp1", "exp2", "exp3_corrected")


def read_notes(path: Path) -> dict[str, str]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["note_id"]: row["text"] for row in csv.DictReader(handle)}


def conditions(root: Path) -> list[Path]:
    """Every directory under the reported experiments that holds a run."""
    found = []
    for experiment in EXPERIMENTS:
        found += sorted(p.parent for p in (root / experiment).rglob("edits.jsonl"))
    return found


def export(condition: Path, out: Path, notes: dict[str, str]) -> dict[str, object]:
    """Rewrite one condition's ledger and check it. Raises if a note fails."""
    rows = read_edits(condition)
    trimmed: list[EditRow] = []
    before = after = 0
    for row in rows:
        edit = minimal_edit(row.to_edit(), notes[row.note_uid])
        before += len(row.replacement)
        after += len(edit.replacement)
        trimmed.append(
            EditRow(
                **{
                    **asdict(row),
                    "start": edit.start,
                    "end": edit.end,
                    "replacement": edit.replacement,
                }
            )
        )

    by_cell: dict[tuple[str, str, str, str], list[EditRow]] = {}
    for row in trimmed:
        by_cell.setdefault((row.note_uid, row.cell_id, row.severity, row.scope), []).append(row)
    doses = read_doses(condition)
    for dose in doses:
        cell = (
            str(dose["note_uid"]),
            str(dose["op_id"]),
            str(dose["severity"]),
            str(dose["scope"]),
        )
        rebuilt = apply_edits(notes[cell[0]], tuple(r.to_edit() for r in by_cell.get(cell, [])))
        if sha256_text(rebuilt.text) != dose["output_sha256"]:
            raise RuntimeError(
                f"{condition}: note {cell[0]} does not reproduce from the minimal ledger"
            )

    out.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(asdict(r), sort_keys=True, default=str) for r in trimmed)
    (out / "edits.jsonl").write_text(text + "\n", encoding="utf-8")
    shutil.copyfile(condition / "dose.jsonl", out / "dose.jsonl")
    manifest = json.loads((condition / "manifest.json").read_text(encoding="utf-8"))
    manifest["edits_sha256_as_generated"] = manifest.get("edits_sha256")
    manifest["edits_sha256"] = sha256_text(text)
    manifest["replacement_form"] = "minimal_diff"
    manifest["contains_note_text"] = False
    manifest["export"] = {
        "by": "release/export_ledgers.py",
        "robustehr": __version__,
        "cells_replayed": len(doses),
        "cells_verified": len(doses),
        "replacement_chars_as_generated": before,
        "replacement_chars_exported": after,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "condition": str(out),
        "edits": len(trimmed),
        "cells": len(doses),
        "chars_before": before,
        "chars_after": after,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiments", type=Path, default=Path("data/experiments"))
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/release_ledgers"))
    args = parser.parse_args(argv)

    notes = read_notes(args.notes)
    found = conditions(args.experiments)
    if not found:
        print(f"no runs under {args.experiments} for {EXPERIMENTS}", file=sys.stderr)
        return 1
    summary = []
    for condition in found:
        relative = condition.relative_to(args.experiments)
        result = export(condition, args.out / relative, notes)
        summary.append({**result, "condition": str(relative)})
        print(
            f"{relative}: {result['cells']} cells replayed, {result['edits']} edits, "
            f"replacement characters {result['chars_before']} -> {result['chars_after']}"
        )
    index = {
        "robustehr": __version__,
        "conditions": len(summary),
        "cells_verified": sum(int(s["cells"]) for s in summary),
        "edits": sum(int(s["edits"]) for s in summary),
        "replacement_chars_as_generated": sum(int(s["chars_before"]) for s in summary),
        "replacement_chars_exported": sum(int(s["chars_after"]) for s in summary),
        "by_condition": summary,
    }
    (args.out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(
        f"-> {args.out}: {index['conditions']} conditions, {index['cells_verified']} cells "
        "verified, every one reproducing its recorded hash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
