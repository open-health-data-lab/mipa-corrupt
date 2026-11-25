"""Where did the edits actually land — on clinical content, or on prose?

Every other artifact reports *how much* was corrupted. None reports *what*, and
for a targeted experiment that is the claim being made. Experiment 2 says it
corrupts clinical content; the only evidence that it does is a measurement of
the edits it produced.

**Experiment 1 is the control, and it is what makes Experiment 2 readable.** It
corrupts the whole document with no clinical target, so its edits should land on
clinical and non-clinical tokens in roughly the proportion the corpus contains
them. If Experiment 2's distribution is not sharply different, the targeting did
not work — and an earlier build's did not: measured, only ~30% of its edit budget
reached clinical content while 14% hit plain English (`she`, `you`, `please`).

Classification uses the same evidence the targeting rule does, so the table
answers "did the rule do what it claims" rather than introducing a second,
unvalidated notion of clinical:

    clinical        salience >= 0.50, or a curated drug-vocabulary hit
    non-clinical    ordinary English below that threshold
    unmeasured      the corpus never showed us this token often enough

`unmeasured` is reported rather than folded into either side. It is mostly rare
clinical terms and de-identification artifacts, and assigning it silently would
flatter whichever side it was assigned to.

    python analysis/edit_placement.py
    python analysis/edit_placement.py --limit 200      # faster, same shape

Writes `results/measurements/edit_placement.json` and prints the comparison table.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")


@dataclass
class Placement:
    """Edited word-tokens for one condition, by what kind of token they were."""

    condition: str
    experiment: str
    counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, Counter[str]] = field(default_factory=dict)
    #: Notes where before/after aligned character-for-character. A corruption
    #: that changes length cannot be compared this way, and reporting its edits
    #: as 0 would read as "it corrupted nothing clinical" rather than "this
    #: instrument cannot see it". Structural operators are exactly that case.
    comparable: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def share(self, key: str) -> float:
        return self.counts[key] / self.total if self.total else 0.0

    def row(self) -> dict[str, object]:
        return {
            "condition": self.condition,
            "experiment": self.experiment,
            "edited_tokens": self.total,
            **{f"{k}_n": self.counts[k] for k in KINDS},
            **{f"{k}_share": round(self.share(k), 4) for k in KINDS},
            "comparable_notes": self.comparable,
            "skipped_length_changed": self.skipped,
            "top_non_clinical": [
                w for w, _ in self.examples.get("non-clinical", Counter()).most_common(10)
            ],
        }


KINDS = ("clinical", "non-clinical", "unmeasured")


def load(path: Path, column: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["hadm_id"]: row[column] for row in csv.DictReader(handle)}


def classify_fn():  # type: ignore[no-untyped-def]
    """`token -> kind`, using the targeting rule's own evidence."""
    from robustehr import salience
    from robustehr.drugs import load_synonyms

    syn = load_synonyms()
    table = salience.table()
    threshold = salience.DEFAULT_THRESHOLD

    def kind(word: str) -> str:
        # Drug vocabulary first, mirroring `ClinicalSalience.admits`: the rule
        # admits a drug REGARDLESS of its salience, because the gold rarely
        # annotates medications and most drugs sit below threshold (metoprolol
        # 0.004). Checking the salience table first mislabelled exactly those
        # drugs non-clinical and understated exp2's clinical share.
        lower = word.lower()
        bare = lower.rstrip("-")
        if bare in syn.to_generic or bare in syn.to_brand:
            return "clinical"
        if lower in table:
            return "clinical" if table[lower] >= threshold else "non-clinical"
        return "unmeasured"

    return kind


def measure(baseline: dict[str, str], corrupted: dict[str, str], kind) -> Counter[str]:  # type: ignore[no-untyped-def]
    """Count edited word-tokens by kind.

    Compares character by character over the shared ids. A corruption that
    changes length would break the alignment, so those notes are skipped rather
    than mis-attributed — every operator here is length-preserving, so in
    practice none are.
    """
    counts: Counter[str] = Counter()
    examples: Counter[str] = Counter()
    comparable = skipped = 0
    for hadm_id in baseline.keys() & corrupted.keys():
        before, after = baseline[hadm_id], corrupted[hadm_id]
        if len(before) != len(after):
            skipped += 1
            continue
        comparable += 1
        for match in WORD.finditer(before):
            start, end = match.span()
            if before[start:end] != after[start:end]:
                k = kind(match.group())
                counts[k] += 1
                if k == "non-clinical":
                    examples[match.group().lower()] += 1
    return counts, examples, comparable, skipped


def write_markdown(path: Path, results: list[Placement], notes: int) -> None:
    """One table per experiment, because the comparison between them is the point."""
    lines = [
        "# Where the corruption landed — clinical vs non-clinical tokens",
        "",
        f"Measured over **{notes:,} notes** by diffing each corrupted corpus against the "
        "clean baseline and classifying every changed word-token.",
        "",
        "A token counts as **clinical** if the measured salience lexicon puts it at or above "
        "0.50 — the rate at which it falls inside a span a clinician adjudicated as a clinical "
        "concept — or if it is in the curated drug vocabulary. Same evidence the targeting rule "
        "uses, so this answers *did the rule do what it claims* rather than introducing a "
        "second, unvalidated notion of clinical. Method and validation: "
        "[validation-protocol §9](../../docs/validation-protocol.md).",
        "",
        "`unmeasured` is reported rather than folded into either side — mostly rare clinical "
        "terms and de-identification artifacts, and assigning it silently would flatter "
        "whichever side received it.",
        "",
        "Structural corruptions change the length of the note, so the character alignment this "
        "measure needs does not exist for them. They are marked *not comparable* rather than "
        'reported as zero, which would read as "corrupted nothing clinical".',
        "",
    ]
    titles = {
        "exp1": (
            "Experiment 1 — whole-document corruption (the control)",
            "No clinical target. Edits should land on clinical tokens at roughly the rate "
            "clinical tokens occur in the corpus, which the SNOMED CT Entity Linking gold "
            "independently puts at **29.1%** of word tokens.",
        ),
        "exp2": (
            "Experiment 2 — clinically-targeted corruption",
            "`ClinicalSalience` target. If this is not sharply higher than Experiment 1, "
            "the targeting did not work — and an earlier build's did not, reaching only "
            "~30%, statistically indistinguishable from no targeting at all.",
        ),
    }
    for experiment in ("exp1", "exp2"):
        head, blurb = titles[experiment]
        lines += [
            f"## {head}",
            "",
            blurb,
            "",
            "| Corruption | Severity | Edited tokens | Clinical | Non-clinical | Unmeasured |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for p in sorted(results, key=lambda x: x.condition):
            if p.experiment != experiment:
                continue
            corruption, severity = p.condition.rsplit("/", 1)
            if not p.total:
                lines.append(
                    f"| `{corruption}` | {severity} | — | _not comparable (length-changing)_ | | |"
                )
                continue
            lines.append(
                f"| `{corruption}` | {severity} | {p.total:,} | "
                f"**{p.share('clinical'):.1%}** | {p.share('non-clinical'):.1%} | "
                f"{p.share('unmeasured'):.1%} |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiments", type=Path, default=Path("data/experiments"))
    parser.add_argument("--limit", type=int, default=None, help="notes per condition")
    parser.add_argument("--out", type=Path, default=Path("results/measurements/edit_placement.json"))
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("data/experiments/edit_placement.md"),
        help="human-readable table, written beside the corpora it describes",
    )
    args = parser.parse_args()

    from mipa import corpora as mipa_corpora

    kind = classify_fn()
    baseline_all = load(args.experiments / "baseline" / "notes.csv", "note_text")
    if args.limit:
        keep = sorted(baseline_all)[: args.limit]
        baseline_all = {k: baseline_all[k] for k in keep}

    results: list[Placement] = []
    for experiment in ("exp1", "exp2"):
        for condition in mipa_corpora.discover(args.experiments, experiment=experiment):
            if condition.is_baseline:
                continue
            corrupted = load(condition.notes_csv, "note_corrupted")
            if args.limit:
                corrupted = {k: v for k, v in corrupted.items() if k in baseline_all}
            counts, examples, comparable, skipped = measure(baseline_all, corrupted, kind)
            p = Placement(
                condition=f"{condition.corruption}/{condition.severity}",
                experiment=experiment,
            )
            p.counts = counts
            p.examples = {"non-clinical": examples}
            p.comparable, p.skipped = comparable, skipped
            results.append(p)
            print(f"  measured {experiment} {p.condition}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "what": "share of corrupted word-tokens that were clinical content",
                "classifier": "robustehr.salience >= 0.50, or curated drug vocabulary",
                "notes": len(baseline_all),
                "conditions": [p.row() for p in results],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    write_markdown(args.markdown, results, len(baseline_all))
    print(f"\nwrote {args.markdown}")

    print(
        f"\n{'condition':<34} {'exp':<5} {'edits':>8} {'clinical':>9} {'non-clin':>9} {'unmeas':>8}"
    )
    print("-" * 80)
    for p in sorted(results, key=lambda x: (x.condition, x.experiment)):
        if not p.total:
            # Length-changing operator: the character alignment this measure
            # needs does not exist, so there is nothing to report either way.
            print(
                f"{p.condition:<34} {p.experiment:<5} {'—':>8} "
                f"{'not comparable (length-changing)':>29}"
            )
            continue
        print(
            f"{p.condition:<34} {p.experiment:<5} {p.total:>8,} "
            f"{p.share('clinical'):>8.1%} {p.share('non-clinical'):>9.1%} "
            f"{p.share('unmeasured'):>8.1%}"
        )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
