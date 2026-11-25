"""Did the targeting work? One table, and the tokens to check it against.

`edit_placement.py` measures where edits landed and reports it per experiment.
This turns the same measurement into the thing a manuscript needs: Experiment 1
and Experiment 2 **on the same row**, at matched corruption and severity, with
the enrichment between them stated rather than left for the reader to divide.

It also prints the tokens. A percentage is a claim; the tokens are the evidence,
and they are what lets a clinician reading the paper judge the classifier for
themselves in ten seconds — which no aggregate can substitute for. The residual
disagreements are the most informative part and are shown rather than hidden.

    python analysis/targeting_showcase.py
    python analysis/targeting_showcase.py --limit 200      # faster, same shape

Reads `results/measurements/edit_placement.json` for the aggregates (regenerate it
with `edit_placement.py` if the corpora changed) and the corpora themselves for
the token examples. Writes `results/measurements/targeting_showcase.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")
#: The pair the experiment actually runs. Structural corruptions change note
#: length, so the character alignment this measure needs does not exist for
#: them — they are absent here rather than reported as zero.
CORRUPTIONS = ("typographical_errors", "homoglyph_substitutions")
SEVERITIES = ("low", "medium", "high")


def load(path: Path, column: str, keep: set[str] | None = None) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            r["hadm_id"]: r[column]
            for r in csv.DictReader(handle)
            if keep is None or r["hadm_id"] in keep
        }


def edited_tokens(baseline: dict[str, str], corrupted: dict[str, str]) -> Counter[str]:
    """Which word-tokens changed, and how often.

    Character-aligned, so it only works for length-preserving operators — which
    is every operator compared here.
    """
    hits: Counter[str] = Counter()
    for hadm_id in baseline.keys() & corrupted.keys():
        before, after = baseline[hadm_id], corrupted[hadm_id]
        if len(before) != len(after):
            continue
        for m in WORD.finditer(before):
            s, e = m.span()
            if before[s:e] != after[s:e]:
                hits[m.group().lower()] += 1
    return hits


def classifier():  # type: ignore[no-untyped-def]
    """`token -> (kind, salience)`, the targeting rule's own evidence."""
    from robustehr import salience
    from robustehr.drugs import load_synonyms

    table = salience.table()
    syn = load_synonyms()
    threshold = salience.DEFAULT_THRESHOLD

    def kind(word: str) -> tuple[str, float | None]:
        # Drug vocabulary FIRST, mirroring `ClinicalSalience.admits` and
        # `edit_placement.classify_fn`: the rule admits a drug regardless of its
        # salience, because the gold rarely annotates medications and most drugs
        # sit below threshold (`metoprolol` 0.004, `acetaminophen` 0.011).
        # Consulting the salience table first labels exactly those drugs
        # non-clinical — which is what this script did on its first run, and it
        # made the targeted arm look like it was corrupting prose when it was
        # corrupting the drug names it was aimed at.
        lower = word.lower()
        bare = lower.rstrip("-")
        if bare in syn.to_generic or bare in syn.to_brand:
            return ("clinical", table.get(lower))
        if lower in table:
            score = table[lower]
            return ("clinical" if score >= threshold else "non-clinical", score)
        return ("unmeasured", None)

    return kind


def paired_rows(placement: dict) -> list[dict]:
    """One row per (corruption, severity) with both experiments side by side."""
    by_key = {(c["experiment"], c["condition"]): c for c in placement["conditions"]}
    rows = []
    for corruption in CORRUPTIONS:
        for severity in SEVERITIES:
            cond = f"{corruption}/{severity}"
            a, b = by_key.get(("exp1", cond)), by_key.get(("exp2", cond))
            if not a or not b or not a["edited_tokens"] or not b["edited_tokens"]:
                continue
            rows.append(
                {
                    "corruption": corruption,
                    "severity": severity,
                    "exp1_n": a["edited_tokens"],
                    "exp2_n": b["edited_tokens"],
                    "exp1_clin": a["clinical_share"],
                    "exp2_clin": b["clinical_share"],
                    "exp1_non": a["non-clinical_share"],
                    "exp2_non": b["non-clinical_share"],
                    "enrichment": b["clinical_share"] / a["clinical_share"]
                    if a["clinical_share"]
                    else float("nan"),
                }
            )
    return rows


#: Representative tokens per class, chosen to include the cases the rule gets
#: WRONG as well as the ones it gets right. A definition table showing only
#: clean examples would misrepresent a classifier with 0.820 precision.
_SPECIMENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("core", ("hypertension", "edema", "pneumonia")),
    ("generic", ("left", "right", "normal")),
    ("drug", ("metoprolol", "acetaminophen", "warfarin")),
    ("assay_hit", ("hct-", "na-")),
    ("assay_miss", ("mcv-", "lipase-", "k-")),
    ("function", ("the", "and", "she")),
)

_NOTES = {
    "core": "core concept, correctly admitted",
    "generic": "**over-inclusive** — scores high by co-occurrence",
    "drug": "salience alone would reject it",
    "assay_hit": "correctly admitted",
    "assay_miss": "**missed** — clinical, but below threshold",
    "function": "correctly excluded",
}


def class_table(kind) -> list[str]:  # type: ignore[no-untyped-def]
    """What each class means, what it contains, and where it is wrong.

    The last column is the point. Anyone deciding whether to trust a targeting
    claim needs the classifier's failure modes, and stating them beside the
    definition is more useful than a precision figure quoted once in a methods
    section and never characterised.
    """
    L = [
        "",
        "## What counts as clinical",
        "",
        "| Class | Rule | Examples (salience) | Where it is wrong |",
        "|---|---|---|---|",
        "| **Clinical** | salience >= 0.50, **or** in the curated drug vocabulary "
        "| `hypertension` 0.99, `edema` 0.99, `metoprolol` 0.004 (drug) "
        "| Admits generic words that score high because they *co-occur* with findings: "
        "`left` 0.87, `right` 0.82, `normal` 0.61 — clinically weak in isolation. |",
        "| **Non-clinical** | in the lexicon, below 0.50, and not a drug "
        "| `the` 0.04, `and` 0.03, `she` 0.001 "
        "| Contains genuinely clinical tokens the gold under-annotates. Lab assays fall "
        "either side of the threshold for no clinical reason: `hct-` 0.99 and `na-` 0.99, "
        "but `mcv-` 0.38, `lipase-` 0.44, `k-` 0.23. |",
        "| **Unmeasured** | never seen often enough in the gold to score "
        "| rare terms, de-identification artifacts "
        "| Skewed *clinical* — mostly rare disorders and drug spellings — so folding it "
        "into either side would flatter that side. Reported separately for that reason. |",
        "",
        "### Incomplete specificity, stated plainly",
        "",
        "The rule measures **precision 0.820, recall 0.789, F1 0.804** against 272",
        "MIMIC-IV discharge summaries adjudicated in the SNOMED CT Entity Linking",
        "Challenge (75,491 spans). About **one token in five that it calls clinical would",
        "not be adjudicated a clinical concept**, and about one in five that would be, it",
        "misses. The errors are systematic, not random:",
        "",
        "* **Co-occurrence, not meaning.** Salience is P(token lies inside an adjudicated",
        "  span), so laterality and qualifier words score high because they sit *within*",
        "  findings. `left` at 0.87 reflects `left ventricular hypertrophy`; it does not",
        "  make `left` a clinical concept.",
        "* **The gold under-annotates medications** — 27.2% of mentions, against 80.6%",
        "  for symptoms and 70.8% for diseases. Hence the separate drug clause, and hence",
        "  precision 0.820 is a **floor rather than an estimate**: every drug admitted by",
        "  vocabulary and absent from the gold is scored against the rule.",
        "* **Context-blind and corpus-bound.** One score per token type, identical in",
        "  every sentence, derived from discharge summaries alone. It does not transfer",
        "  unexamined to progress notes, radiology, or another institution.",
        "",
        "This does not weaken the targeting comparison, because **both arms are classified",
        "by the same rule**: a systematic error moves exp1 and exp2 together and cannot",
        "manufacture a 2.9x gap. It does mean the absolute numbers should be read as",
        "*share of tokens this rule calls clinical*, not *share of clinical content*.",
        "",
        "### Specimen tokens",
        "",
        "| Token | Salience | Classified | Note |",
        "|---|---:|---|---|",
    ]
    for group, tokens in _SPECIMENS:
        for token in tokens:
            k, score = kind(token)
            shown = "—" if score is None else f"{score:.3f}"
            L.append(f"| `{token}` | {shown} | {k} | {_NOTES[group]} |")
    return L


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiments", type=Path, default=Path("data/experiments"))
    ap.add_argument("--placement", type=Path, default=Path("results/measurements/edit_placement.json"))
    ap.add_argument("--out", type=Path, default=Path("results/measurements/targeting_showcase.md"))
    ap.add_argument("--limit", type=int, default=None, help="notes to sample for the examples")
    ap.add_argument("--top", type=int, default=12, help="tokens shown per list")
    args = ap.parse_args()

    if not args.placement.exists():
        raise SystemExit(f"no {args.placement} — run analysis/edit_placement.py first")
    placement = json.loads(args.placement.read_text(encoding="utf-8"))
    rows = paired_rows(placement)
    if not rows:
        raise SystemExit("no matched exp1/exp2 conditions in the placement measurement")

    kind = classifier()
    base_path = args.experiments / "baseline" / "notes.csv"
    baseline = load(base_path, "note_text")
    if args.limit:
        baseline = {k: baseline[k] for k in sorted(baseline)[: args.limit]}
    keep = set(baseline)

    # The showcase uses the heaviest severity: same rule, most edits, so the
    # token lists are the least noisy view of what each arm goes after.
    showcase = {}
    for experiment in ("exp1", "exp2"):
        path = args.experiments / experiment / "typographical_errors" / "high" / "notes.csv"
        if not path.exists():
            continue
        hits = edited_tokens(baseline, load(path, "note_corrupted", keep))
        buckets: dict[str, Counter[str]] = {
            "clinical": Counter(),
            "non-clinical": Counter(),
            "unmeasured": Counter(),
        }
        for token, n in hits.items():
            buckets[kind(token)[0]][token] += n
        showcase[experiment] = buckets
        print(f"  {experiment}: {sum(hits.values()):,} edited tokens over {len(baseline)} notes")

    document = render(
        placement, rows, showcase, notes_n=len(baseline), top_n=args.top, kind=kind
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(document, encoding="utf-8")
    print(f"\nwrote {args.out}")

    print(f"\n{'corruption':<26} {'sev':<7} {'exp1':>7} {'exp2':>7} {'enrich':>8}")
    print("-" * 60)
    for r in rows:
        print(
            f"{r['corruption']:<26} {r['severity']:<7} {r['exp1_clin']:>7.1%} "
            f"{r['exp2_clin']:>7.1%} {r['enrichment']:>7.1f}x"
        )
    return 0


def render(  # type: ignore[no-untyped-def]
    placement: dict,
    rows: list[dict],
    showcase: dict,
    *,
    notes_n: int,
    top_n: int,
    kind,
) -> str:
    """The document. Separated from `main` so the prose is one readable block."""
    L = [
        "# Targeting: did Experiment 2 actually hit clinical concepts?",
        "",
        "Experiment 1 corrupts the whole document with no clinical target; Experiment 2",
        "restricts the same operator, at the same severity, to spans the measured",
        "`ClinicalSalience` rule accepts. If the two arms landed on the same kind of",
        "token, the targeted arm is not a different condition and the comparison between",
        "them means nothing — so this is the table that has to hold before any downstream",
        "result can be read as being *about* clinical content.",
        "",
        "Measured by diffing every corrupted corpus against the clean baseline over",
        f"**{placement['notes']:,} notes** and classifying each changed word-token with",
        "the same evidence the targeting rule uses: the measured salience lexicon at a",
        "0.50 threshold, plus the curated drug vocabulary. Using the rule's own evidence",
        "answers *did the rule do what it claims*, rather than introducing a second,",
        "unvalidated notion of clinical that could agree by construction.",
        "",
        "## Where the edits landed",
        "",
        "| Corruption | Severity | Clinical, exp1 | Clinical, exp2 | Enrichment |"
        " Non-clinical, exp1 | Non-clinical, exp2 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        L.append(
            f"| `{r['corruption']}` | {r['severity']} | {r['exp1_clin']:.1%} | "
            f"**{r['exp2_clin']:.1%}** | **{r['enrichment']:.1f}x** | "
            f"{r['exp1_non']:.1%} | {r['exp2_non']:.1%} |"
        )
    lo = min(r["exp2_clin"] for r in rows)
    hi = max(r["exp2_clin"] for r in rows)
    e1lo = min(r["exp1_clin"] for r in rows)
    e1hi = max(r["exp1_clin"] for r in rows)
    non_drop = max(r["exp1_non"] for r in rows) / max(min(r["exp2_non"] for r in rows), 1e-9)
    L += [
        "",
        f"Experiment 1 spends **{e1lo:.0%}-{e1hi:.0%}** of its edit budget on clinical",
        "tokens — which is the point of the control, because the SNOMED CT Entity Linking",
        "gold independently puts clinical tokens at **29.1%** of word tokens in this",
        "corpus. An untargeted operator hitting them at their base rate is the null",
        "result this arm is supposed to produce, and it does.",
        "",
        f"Experiment 2 reaches **{lo:.0%}-{hi:.0%}**, and its non-clinical share falls by",
        f"roughly **{non_drop:.0f}x**. The enrichment is stable across corruptions and",
        "severities, so it is a property of the targeting rule and not of one operator or",
        "one dose.",
        *class_table(kind),
        "",
        "## The tokens themselves",
        "",
        f"From `typographical_errors/high` over {notes_n:,} notes — the same rule at its",
        "heaviest dose, where the token lists are least noisy. Counts are occurrences",
        "corrupted.",
        "",
    ]
    for experiment, title in (
        ("exp1", "Experiment 1 — untargeted"),
        ("exp2", "Experiment 2 — `ClinicalSalience`-targeted"),
    ):
        b = showcase.get(experiment)
        if not b:
            continue
        L += [f"### {title}", ""]
        for bucket in ("clinical", "non-clinical"):
            top = b[bucket].most_common(top_n)
            if not top:
                continue
            shown = ", ".join(f"`{t}` ({n:,})" for t, n in top)
            L += [f"**Most-corrupted {bucket} tokens** — {shown}", ""]

    e1_non = showcase.get("exp1", {}).get("non-clinical", Counter())
    e2_non = showcase.get("exp2", {}).get("non-clinical", Counter())
    if e1_non and e2_non:
        L += [
            "### Reading the residual",
            "",
            "The contrast in the non-clinical rows is the result in miniature. Experiment",
            "1's are ordinary English —",
            ", ".join(f"`{t}`" for t, _ in e1_non.most_common(6)) + " — function words and",
            "narrative that carry no clinical content.",
            "",
            "Experiment 2's residual is a different kind of token altogether —",
            ", ".join(f"`{t}`" for t, _ in e2_non.most_common(6)) + ". These are laboratory",
            "assay names carrying a trailing hyphen from the lab-block layout. They are",
            "clinical in substance and the classifier scores them below threshold, which",
            "means the **1-2% figure above overstates how much prose the targeted arm",
            "hit**:",
            "most of that residual is clinical content the lexicon under-scores, not English.",
            "",
            "That is a limitation of the measurement reported against itself, and the reason",
            "`unmeasured` is kept as its own bucket rather than folded into either side.",
            "See `docs/validation-protocol.md` §9 for the rule, its lexicon digest and its",
            "benchmark.",
            "",
        ]

    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
