"""The one-page Table 1: what a manuscript prints.

`table1.md` is 246 lines. That is the right length for an artifact a reader can
audit — every level an operator can target, with its denominator — and the
wrong length for a methods section, where Table 1 is one page and answers "what
kind of notes are these".

So both exist and neither replaces the other. This selects the characteristics
a clinical reader would expect to see and drops the operator-eligibility detail,
which belongs in the full table beside the operators it constrains.

Two things are kept that a generic corpus table would omit, because this corpus
is being corrupted rather than merely described:

* **Concept mentions**, since the semantic operators are dosed over them.
* **Clinical vs non-clinical content**, since that split is what the targeted
  arm is aimed at and what its result is read against.

    python analysis/table1_short.py --table data/experiments/baseline/table1.json
    python analysis/table1_short.py --table data/mipa_exp1/table1_sample/table1.json

Writes `table1_short.md` beside its input unless `--out` says otherwise.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

#: `(level, field, label)`, in print order. A curated selection: enough to
#: characterise the corpus, short enough to read at a glance.
ROWS: tuple[tuple[str, str, str], ...] = (
    ("character", "n", "Characters"),
    ("document", "lines", "Lines"),
    ("section", "n", "Sections"),
    ("header", "n", "Section headers"),
    ("sentence", "n", "Sentences"),
    ("list_item", "n", "List items"),
    ("aligned_block", "n", "Aligned blocks (lab tables)"),
    ("placeholder", "n", "De-identification placeholders"),
    ("token", "n", "Tokens"),
    ("token", "content", "Content tokens"),
    ("numeric_value", "n", "Numeric values"),
    ("span", "n", "Concept mentions"),
    ("medication", "n", "Medication mentions"),
)

#: Rendered as its own block with a share, because it is the axis the targeted
#: experiment is judged on rather than one characteristic among many.
CLINICAL = (
    ("clinical", "Clinical — salience >= 0.50, or a curated drug"),
    ("non_clinical", "Non-clinical — ordinary English below that"),
    ("unmeasured", "Unmeasured — never seen often enough to score"),
)


def cell(block: dict | None) -> str:
    """Median [IQR], matching the full table's convention."""
    if not isinstance(block, dict) or block.get("median") is None:
        return "—"
    med, p25, p75 = block["median"], block.get("p25"), block.get("p75")
    if p25 is None or p75 is None:
        return f"{med:,}"
    return f"{med:,} [{p25:,}-{p75:,}]"


def total(block: dict | None) -> str:
    value = (block or {}).get("total")
    return f"{value:,}" if isinstance(value, int) else "—"


def render(payload: dict, label: str) -> str:
    by_level = payload["by_level"]
    notes = payload.get("notes") or {}
    n_notes = notes.get("total") if isinstance(notes, dict) else notes
    header = f"# Table 1 — {payload.get('corpus', label)}"

    L = [
        header,
        "",
        "Median [IQR] per note, over "
        + (f"**{n_notes:,} notes**. " if isinstance(n_notes, int) else "the corpus. ")
        + "Nearest-rank quantiles, never means: note lengths are right-skewed, so a mean",
        "describes a note that does not exist.",
        "",
        "The full characterisation — every structural level with the operators that can",
        "target it, and the eligibility counts each operator is dosed over — is in",
        "`table1.md`. This is the short form.",
        "",
        "| Characteristic | Per note | Corpus total |",
        "|---|---:|---:|",
    ]
    for level, field, text in ROWS:
        block = by_level.get(level, {}).get(field)
        if not isinstance(block, dict):
            continue
        L.append(f"| {text} | {cell(block)} | {total(block)} |")

    cc = by_level.get("clinical_content")
    if isinstance(cc, dict):
        clinical = (cc.get("clinical") or {}).get("total")
        other = (cc.get("non_clinical") or {}).get("total")
        L += ["", "### Content tokens, by clinical salience", ""]
        L += ["| Class | Per note | Corpus total | Share |", "|---|---:|---:|---:|"]
        for field, text in CLINICAL:
            block = cc.get(field)
            if not isinstance(block, dict):
                continue
            # Share of MEASURED content only: `unmeasured` has no share
            # because it is not part of the denominator, and printing one would
            # imply it had been assigned to a side.
            measured = (
                clinical + other
                if isinstance(clinical, int) and isinstance(other, int)
                else 0
            )
            share = (
                f"{block['total'] / measured:.1%}"
                if measured and field in {"clinical", "non_clinical"}
                else "—"
            )
            L.append(f"| {text} | {cell(block)} | {total(block)} | {share} |")
        if isinstance(clinical, int) and isinstance(other, int) and clinical + other:
            L += [
                "",
                f"**{clinical / (clinical + other):.1%} of measured content tokens are "
                "clinical.** `unmeasured` is held out of that denominator rather than",
                "folded into either side — it is mostly rare clinical terms and",
                "de-identification artifacts, so assigning it would flatter whichever side",
                "received it. The rule, its measured precision (0.820) and its failure",
                "modes are in `03_targeting/targeting_showcase.md`.",
            ]
    L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True, help="a generated table1.json")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--label", default="corpus")
    args = ap.parse_args()

    payload = json.loads(args.table.read_text(encoding="utf-8"))
    out = args.out or args.table.with_name("table1_short.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload, args.label), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
