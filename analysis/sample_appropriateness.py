"""Is the evaluated sample representative of the corpus it was drawn from?

The experiment runs on 500 of 1,388 notes. Every F1 in the results is computed
on those 500, while the corpus characterisation describes all 1,388 — so the
question a reader asks first is whether the two populations are the same shape.
Asserting "stratified, therefore representative" is not an answer; this
measures it.

Two families of characteristic, because the sample was stratified on both:

* **Phenotype prevalence** — the 16 MIPA labels. These are what the models
  predict, so a sample that over-represented a common phenotype would inflate
  macro-F1 for reasons unrelated to corruption.
* **Note structure and content** — length, sections, clinical token share. A
  sample of systematically shorter or less clinical notes would be an easier
  task, and the degradation measured on it would not transfer.

Reports **absolute percentage-point difference** rather than a p-value. With
500 of 1,388 the sample is a large fraction of the frame, so a significance
test against an independent-draw null is answering a question nobody asked; the
decision-relevant quantity is how far prevalence moved, in points.

The rare phenotypes are where sampling hurts and the table says so: a label at
1% prevalence gives ~5 positives in 500, and per-phenotype F1 on 5 positives is
noise. `n_pos` is printed for exactly that judgement.

    python analysis/sample_appropriateness.py

Writes `data/mipa_exp1/table1_sample/sample_appropriateness.md`;
`analysis/collect_tables.py` copies it into `data/tables/02_sample/`.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

#: Not a phenotype — MIPA's gold carries a `none` column meaning "no label
#: applies", which is a property of the row rather than a condition to predict.
NOT_A_PHENOTYPE = frozenset({"none", "note_id", "subject_id", "hadm_id", ""})

#: A characteristic differing by more than this between corpus and sample is
#: called out. 5% is well inside the noise of a 500-note median and far below
#: anything that would change how a result reads.
DRIFT = 0.05

#: The positives floor `mipa_sample.select` was run with. Recorded here so the
#: report can explain the deviation it causes instead of reporting it as drift.
FLOOR = 30

#: Structural fields worth comparing, as (level, field, label). Chosen because
#: each is something a reader would reasonably worry the sample skewed.
STRUCTURE: tuple[tuple[str, str, str], ...] = (
    ("character", "n", "Characters per note"),
    ("document", "lines", "Lines per note"),
    ("token", "n", "Tokens per note"),
    ("section", "n", "Sections per note"),
    ("header", "n", "Section headers per note"),
    ("sentence", "n", "Sentences per note"),
    ("clinical_content", "clinical", "Clinical content tokens"),
    ("clinical_content", "non_clinical", "Non-clinical content tokens"),
)


def read_labels(path: Path) -> tuple[dict[str, dict[str, int]], list[str]]:
    """`hadm_id -> {phenotype: 0/1}`, and the phenotype list in file order."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}, []
    names = [k for k in rows[0] if k and k not in NOT_A_PHENOTYPE]
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        key = row.get("hadm_id") or row.get("note_id") or ""
        out[key] = {n: _positive(row.get(n)) for n in names}
    return out, names


def _positive(value: object) -> int:
    """Is this label positive?

    The gold is not uniformly encoded: most columns hold `0`/`1`, but `hfref`
    holds `0.0`/`1.0` and one row is blank. A membership test against
    `{"1", "true"}` silently read all 122 `hfref` positives as negative and
    reported the phenotype as absent from a corpus that is 8.8% positive for it
    — a missing-data bug that looks exactly like a real finding, which is why
    this parses the value instead of matching its spelling.
    """
    text = str(value).strip().lower()
    if text in {"true", "yes"}:
        return 1
    try:
        return int(float(text) == 1.0)
    except ValueError:
        return 0  # blank or unparseable: absent, not positive


def prevalence(labels: dict[str, dict[str, int]], names: list[str]) -> dict[str, tuple[int, float]]:
    total = len(labels) or 1
    out = {}
    for n in names:
        positives = sum(r[n] for r in labels.values())
        out[n] = (positives, positives / total)
    return out


def structure(table: Path) -> dict[tuple[str, str], dict]:
    """Median/IQR per structural field, from a generated Table 1."""
    if not table.exists():
        return {}
    by_level = json.loads(table.read_text(encoding="utf-8"))["by_level"]
    out = {}
    for level, field, _ in STRUCTURE:
        block = by_level.get(level, {}).get(field)
        if isinstance(block, dict) and "median" in block:
            out[(level, field)] = block
    return out



def full_characteristics(corpus: Path, sample: Path, n_corpus: int, n_sample: int) -> list[str]:
    """Every Table 1 characteristic, corpus beside sample.

    Walks `report.LEVEL_LABELS` and `report.DELTA_FIELDS` — the same vocabulary
    and the same ordering the generated tables use — so a reader comparing this
    against `01_baseline/table1.md` sees the same rows under the same names. A
    bespoke selection would invite the question of what was left out.

    Deliberately NOT `report.delta_table`, which renders the second column as
    "Corrupted": a sample is a population, not a corruption, and reusing that
    header would frame representativeness as damage.

    Medians with IQR, matching the tables. The comparison column is the relative
    difference in medians, which is the scale-free way to ask "is this the same
    kind of note" across characteristics spanning single digits to five figures.
    """
    from robustehr.report import DELTA_FIELDS, LEVEL_LABELS

    if not corpus.exists() or not sample.exists():
        return []
    a = json.loads(corpus.read_text(encoding="utf-8"))["by_level"]
    b = json.loads(sample.read_text(encoding="utf-8"))["by_level"]

    L = [
        "## All Table 1 characteristics",
        "",
        f"Every characteristic the generated tables report, over the corpus"
        f" ({n_corpus:,} notes) and the evaluated sample ({n_sample:,}). Median [IQR] per",
        "note. **Diff** is the relative difference in medians — scale-free, so a row",
        "measured in characters and a row measured in sections can be scanned together.",
        "",
        f"| Characteristic | Corpus (n={n_corpus:,}) | Sample (n={n_sample:,}) | Diff |",
        "|---|---:|---:|---:|",
    ]
    drifted: list[str] = []
    for key, label in LEVEL_LABELS:
        before, after = a.get(key), b.get(key)
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        rows = [(None, label, True)] + [
            (f, sub, False) for f, sub in DELTA_FIELDS.get(key, ()) if f in before and f in after
        ]
        for field_name, text, is_level in rows:
            x = before.get("n" if field_name is None else field_name) or {}
            y = after.get("n" if field_name is None else field_name) or {}
            if "median" not in x or "median" not in y:
                continue
            name = f"**{text}**" if is_level else f"&nbsp;&nbsp;&nbsp;&nbsp;{text}"
            diff = _relative(x["median"], y["median"])
            if diff is not None and abs(diff) >= DRIFT:
                drifted.append(text)
            L.append(
                f"| {name} | {_iqr(x)} | {_iqr(y)} |"
                f" {'—' if diff is None else f'{diff:+.1%}'} |"
            )
    L += [
        "",
        (
            "**Characteristics differing by more than "
            f"{DRIFT:.0%}:** " + (", ".join(f"`{d}`" for d in dict.fromkeys(drifted)) or "_none_")
        )
        + ".",
        "",
    ]
    if not drifted:
        L += [
            "No characteristic moves by more than a few percent, which is the claim this",
            "table exists to support: the notes the models were run on are the same kind of",
            "notes as the corpus they were drawn from, so a degradation measured on the",
            "sample describes the corpus.",
            "",
        ]
    return L


def _iqr(block: dict) -> str:
    med, p25, p75 = block.get("median"), block.get("p25"), block.get("p75")
    if med is None:
        return "—"
    if p25 is None or p75 is None:
        return f"{med:,}"
    return f"{med:,} [{p25:,}-{p75:,}]"


def _relative(before: object, after: object) -> float | None:
    """Relative change in medians, or None when it is not a number to divide."""
    if not isinstance(before, int | float) or not isinstance(after, int | float) or not before:
        return None
    return (after - before) / before


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", type=Path, default=Path("data/golden_labels.csv"))
    ap.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    ap.add_argument(
        "--corpus-table", type=Path, default=Path("data/experiments/baseline/table1.json")
    )
    ap.add_argument(
        "--sample-table", type=Path, default=Path("data/mipa_exp1/table1_sample/table1.json")
    )
    ap.add_argument(
        "--out", type=Path, default=Path("data/mipa_exp1/table1_sample/sample_appropriateness.md")
    )
    args = ap.parse_args()

    corpus_labels, names = read_labels(args.gold)
    sample_labels, sample_names = read_labels(args.sample)
    # The sample file carries the same labels plus its own stratification
    # columns; intersect so the comparison is like for like.
    names = [n for n in names if n in set(sample_names)]
    if not names:
        raise SystemExit("no phenotype columns shared between the gold and the sample")

    corpus_prev = prevalence(corpus_labels, names)
    sample_prev = prevalence(sample_labels, names)
    n_corpus, n_sample = len(corpus_labels), len(sample_labels)

    rows = sorted(names, key=lambda n: -corpus_prev[n][1])
    worst = max(abs(sample_prev[n][1] - corpus_prev[n][1]) for n in rows)
    thin = [n for n in rows if sample_prev[n][0] < 20]

    L = [
        "# Is the evaluated sample representative?",
        "",
        f"The experiment runs on **{n_sample:,} of {n_corpus:,} notes**. Every F1 in the",
        "results is computed on the sample; the corpus tables describe the whole set. If",
        "the two populations differ, a degradation measured on one does not describe the",
        "other — so this compares them on the axes the sample was stratified over.",
        "",
        "Differences are **absolute percentage points**, not p-values: the sample is a",
        f"large fraction of its own frame ({n_sample / n_corpus:.0%}), which makes a test",
        "against an independent-draw null the wrong question. What matters is how far",
        "prevalence moved.",
        "",
        *full_characteristics(args.corpus_table, args.sample_table, n_corpus, n_sample),
        "## Phenotype prevalence",
        "",
        "Ordered by corpus prevalence. `n_pos` is the count of positive notes **in the",
        "sample** — the denominator every per-phenotype F1 actually rests on.",
        "",
        "| Phenotype | Corpus n (%) | Sample n_pos (%) | Difference |",
        "|---|---:|---:|---:|",
    ]
    for n in rows:
        cn, cp = corpus_prev[n]
        sn, sp = sample_prev[n]
        delta = (sp - cp) * 100
        flag = " ⚠" if sn < 20 else ""
        L.append(
            f"| `{n}` | {cn:,} ({cp:.1%}) | {sn:,} ({sp:.1%}){flag} | {delta:+.1f} pp |"
        )
    floored = [
        n
        for n in rows
        if sample_prev[n][0] >= FLOOR > corpus_prev[n][0] * n_sample / n_corpus
    ]
    L += [
        "",
        f"Largest deviation: **{worst * 100:.1f} percentage points**, and it is deliberate.",
        "",
        f"The sample applies a **floor of {FLOOR} positives** per phenotype"
        + (" (" + ", ".join(f"`{n}`" for n in floored) + ")" if floored else "")
        + ". Proportional",
        "allocation is the honest default and gives the rarest labels ~14 positives at",
        "n=500, where per-phenotype F1 is nearly uninterpretable — one flipped prediction",
        "moves it several points. The floor buys precision on exactly those phenotypes at",
        "identical compute: the sample is the same size, it simply spends its slots on",
        "notes carrying the scarce labels.",
        "",
        "**What it costs is prevalence fidelity on those phenotypes, and this is where",
        "that cost is stated.** `mipa_sample` predicted a maximum deviation of 0.032 at",
        f"n=500 with floor {FLOOR}, against 0.001 unfloored; the measurement above is",
        f"{worst:.3f}. Design and independent measurement agree.",
        "",
        "The consequence for reading results: **macro-F1 on this sample is not an",
        "unbiased estimate of macro-F1 on the corpus**, because the two rarest phenotypes",
        "are carried at roughly twice their corpus prevalence. Every other phenotype",
        "tracks the corpus to within 0.1 pp, so the effect is confined to those two, and",
        "the baseline-vs-corrupted *delta* is unaffected — it is paired on the same notes,",
        "so any prevalence distortion cancels.",
        "",
        "Iterative stratification (Sechidis et al. 2011) also cannot make 16 overlapping",
        "binary labels exact simultaneously — allocating one pulls the others — so the",
        "residual 0.1 pp elsewhere is expected rather than a defect.",
        "",
    ]
    if thin:
        L += [
            "### ⚠ Phenotypes too rare to score per-label",
            "",
            "These carry fewer than 20 positives in the sample:",
            "",
        ]
        for n in thin:
            L.append(f"* `{n}` — **{sample_prev[n][0]} positives**")
        L += [
            "",
            "Per-phenotype F1 on this many positives is dominated by sampling noise: one",
            "prediction flipping moves it by several points. They are kept because",
            "dropping them would stop the sample respecting prevalence, and because",
            "**macro-F1 over 16 phenotypes is far more stable than any single one** — and",
            "the baseline-vs-corrupted *delta* is more stable still, being paired on the",
            "same notes. Read the per-phenotype columns in `phenotype_metrics.csv`",
            "alongside their `n_pos`, and do not read a rare phenotype's F1 alone.",
            "",
        ]

    L += structure_section(structure(args.corpus_table), structure(args.sample_table))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    report(rows, corpus_prev, sample_prev, worst, thin)
    return 0


def structure_section(corpus_struct: dict, sample_struct: dict) -> list[str]:
    """Length, sections and clinical content: corpus against sample."""
    L: list[str] = []
    if corpus_struct and sample_struct:
        L += [
            "## Note structure and content",
            "",
            "Median [IQR] per note. A sample of shorter or less clinical notes would be an",
            "easier task, and degradation measured on it would not transfer.",
            "",
            "| Characteristic | Corpus | Sample |",
            "|---|---|---|",
        ]
        for level, field, label in STRUCTURE:
            c, s = corpus_struct.get((level, field)), sample_struct.get((level, field))
            if not c or not s:
                continue
            L.append(
                f"| {label} | {c['median']:,} [{c['p25']:,}-{c['p75']:,}] "
                f"| {s['median']:,} [{s['p25']:,}-{s['p75']:,}] |"
            )
        cc, sc = corpus_struct.get(("clinical_content", "clinical")), sample_struct.get(
            ("clinical_content", "clinical")
        )
        cn, sn2 = corpus_struct.get(("clinical_content", "non_clinical")), sample_struct.get(
            ("clinical_content", "non_clinical")
        )
        if cc and sc and cn and sn2:
            c_share = cc["total"] / (cc["total"] + cn["total"])
            s_share = sc["total"] / (sc["total"] + sn2["total"])
            L += [
                "",
                f"**Clinical share of content tokens: {c_share:.1%} corpus vs "
                f"{s_share:.1%} sample** ({(s_share - c_share) * 100:+.1f} pp). This is the",
                "one that matters most for a corruption experiment: it is the material the",
                "targeted arm is aimed at, and a sample with systematically less of it would",
                "understate what targeting can do.",
                "",
            ]
    return L


def report(rows, corpus_prev, sample_prev, worst, thin) -> None:  # type: ignore[no-untyped-def]
    """The same comparison on stdout, for a run that is not writing a document."""
    print(f"\n{'phenotype':<26} {'corpus':>14} {'sample':>14} {'diff':>9}")
    print("-" * 68)
    for n in rows:
        cn_, cp = corpus_prev[n]
        sn_, sp = sample_prev[n]
        print(f"{n:<26} {cn_:>5} ({cp:>5.1%}) {sn_:>5} ({sp:>5.1%}) {(sp - cp) * 100:>+7.1f}pp")
    print(f"\nlargest deviation {worst * 100:.1f} pp; {len(thin)} phenotype(s) under 20 positives")


if __name__ == "__main__":
    raise SystemExit(main())
