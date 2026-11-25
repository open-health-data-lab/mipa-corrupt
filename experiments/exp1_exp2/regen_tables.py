"""Re-render every Table 1 from corpora that already exist.

Corruption is the expensive half of a sweep and it does not need repeating.
`notes.csv` is on disk for all 34 conditions, byte-identical to what the
operator produced; only the *measurement* changed — a new level was added — so
only the measurement is redone. That is the whole saving: not doing work whose
inputs did not change.

Measured on this corpus, `measure_note` costs ~182 ms/note, dominated by the
medspacy assertion-cue pass (133 ms) and `level_characteristics` (90 ms), not by
the new clinical level (2 ms). So a full re-measure is ~2.4 core-hours, which is
~17 minutes across 9 workers, against roughly six hours to regenerate corpora.

Parallel over **conditions**, not notes. Each condition is an independent
read-measure-write, so the split needs no shared state and no locking, and a
worker crash costs one condition rather than the sweep.

Three details are load-bearing, all copied from `run_experiments.main` — a
re-render that measures differently from the original sweep would produce tables
that cannot be compared to it, which is the one failure that would make this
worse than useless:

* **Wrap widths come from the CLEAN note.** A corruption that joins lines widens
  the margin, and a width recomputed from corrupted text would reclassify
  hard-wrap continuations as real breaks — the instrument moving with the thing
  it measures. Baseline widths are computed once here and pinned into every
  condition.
* **The baseline gets the concept layer; the conditions do not.** That asymmetry
  is already on disk (every corrupted `table1.json` records `span` as
  unavailable, "no UMLS index"), so passing concepts here would silently add
  levels the original sweep never had.
* **The baseline is measured without pinned widths**, as its own clean text
  defines them.

    python experiments/exp1_exp2/regen_tables.py                    # all 34
    python experiments/exp1_exp2/regen_tables.py --only exp2        # one experiment
    python experiments/exp1_exp2/regen_tables.py --workers 4

The baseline is rendered first and every delta is computed against it, so a
partial run still produces internally consistent files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def read_notes(path: Path) -> list[tuple[str, str]]:
    """`(note_id, text)`, from whichever text column this corpus carries."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        column = "note_text" if "note_text" in (reader.fieldnames or []) else "note_corrupted"
        return [(row["note_id"], row[column]) for row in reader]


def _one_condition(job: dict[str, Any]) -> tuple[str, float, str | None]:
    """Worker entry point: re-measure one corrupted corpus and write its tables."""
    started = time.time()
    try:
        from robustehr.document import Document
        from run_experiments import Condition, _measure_all, load_lexicon, write_delta_table

        lexicon = load_lexicon(Path(job["lexicon"]))
        docs = [Document.from_text(text, uid=uid) for uid, text in read_notes(Path(job["notes"]))]
        # No concept index, matching what is already on disk for these
        # conditions; clean widths, so the segmenter does not drift with the
        # corruption. See the module docstring.
        rows = _measure_all(docs, lexicon, {}, job["widths"])

        # The delta needs the clean corpus's numbers. Re-measuring the baseline
        # per condition would multiply the sweep by 34, so it is read from the
        # table written before the fan-out.
        baseline = json.loads(Path(job["baseline_json"]).read_text(encoding="utf-8"))
        condition = Condition(
            experiment=job["experiment"],
            corruption=job["corruption"],
            op_id=job["op_id"],
            level=job["level"],
            severity=job["severity"],
            params={},
            targeted=job["targeted"],
            stratified=job["targeted"],
            directory=Path(job["directory"]),
        )
        # Writes both `table1.json` and `table1_delta.md`.
        write_delta_table(rows, condition, lexicon, baseline)
        return job["name"], time.time() - started, None
    except Exception as exc:  # one condition must not sink the sweep
        return job["name"], time.time() - started, f"{type(exc).__name__}: {exc}"


def render_baseline(root: Path, lexicon_path: Path, index: Path, cache: Path, workers: int):  # type: ignore[no-untyped-def]
    """Measure the clean corpus and return `(table, widths)`.

    Both outputs are needed by every condition that follows: the table as the
    reference the deltas subtract from, the widths as the pinned wrap column.
    """
    from robustehr.concepts.annotate import annotate_corpus
    from robustehr.document import Document
    from robustehr.segment.wrap import wrap_width
    from run_experiments import _measure_all, load_lexicon, write_table1

    lexicon = load_lexicon(lexicon_path)
    docs = [
        Document.from_text(text, uid=uid)
        for uid, text in read_notes(root / "baseline" / "notes.csv")
    ]
    widths = {doc.uid: wrap_width(doc.lines) for doc in docs}

    concepts: dict[str, Any] = {}
    if index.exists():
        # A cache hit for the whole corpus — every note was tagged by the
        # original sweep, so this costs a read rather than a match.
        concepts = annotate_corpus(docs, index, cache, workers=workers, label="baseline")
    else:
        print(f"WARNING: no concept index at {index}; baseline loses its span level", flush=True)

    table = write_table1(
        _measure_all(docs, lexicon, concepts),
        root / "baseline",
        "baseline (clean corpus)",
        lexicon,
    )
    return table, widths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiments", type=Path, default=Path("data/experiments"))
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon/clinical_tokens.txt"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--workers", type=int, default=9)
    parser.add_argument("--only", default=None, help="substring filter on the condition name")
    args = parser.parse_args()

    from run_experiments import _INDEX, build_conditions

    _INDEX.append(str(args.index))
    root = args.experiments

    # Baseline first and alone: every delta reads its table and every condition
    # reuses its widths, so it must be complete before any worker starts. It is
    # rendered even under --only, because a stale baseline would silently make
    # every delta wrong rather than fail.
    print("baseline ...", flush=True)
    started = time.time()
    _, widths = render_baseline(root, args.lexicon, args.index, args.cache, args.workers)
    print(f"  baseline {time.time() - started:.0f}s", flush=True)
    baseline_json = root / "baseline" / "table1.json"

    jobs: list[dict[str, Any]] = []
    for condition in build_conditions(root, exp2=True):
        notes = condition.directory / "notes.csv"
        name = f"{condition.experiment}/{condition.corruption}/{condition.level}"
        if not notes.exists() or (args.only and args.only not in name):
            continue
        jobs.append(
            {
                "name": name,
                "notes": str(notes),
                "directory": str(condition.directory),
                "lexicon": str(args.lexicon),
                "baseline_json": str(baseline_json),
                "widths": widths,
                "experiment": condition.experiment,
                "corruption": condition.corruption,
                "op_id": condition.op_id,
                "level": condition.level,
                "severity": condition.severity,
                "targeted": condition.targeted,
            }
        )
    if not jobs:
        print("no conditions matched")
        return 0

    print(f"{len(jobs)} conditions on {args.workers} workers", flush=True)
    started = time.time()
    failures: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_one_condition, job) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            name, secs, err = future.result()
            if err:
                failures.append((name, err))
            print(f"  [{i:>2}/{len(jobs)}] {name:<46} {secs:>5.0f}s {err or ''}", flush=True)

    print(f"\n{len(jobs)} conditions in {(time.time() - started) / 60:.1f} min")
    if failures:
        print(f"{len(failures)} FAILED:")
        for name, err in failures:
            print(f"  {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
