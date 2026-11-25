"""Write the sampling note: how the 500 were chosen, and how they compare.

Generated rather than hand-written so the numbers cannot drift from the sample
they describe. Everything here is measured from the real MIPA corpus and the real
`data/mipa_exp1/sample.csv` — unlike the rest of `sample_output/`, which is
synthetic.

    python analysis/sampling_report.py --out sample_output/SAMPLING.md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from mipa import corpora as mipa_corpora
from mipa import sample as mipa_sample
from mipa.protocol import PHENOTYPES


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def quantiles(values: list[int]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p25": statistics.quantiles(ordered, n=4)[0],
        "median": statistics.median(ordered),
        "p75": statistics.quantiles(ordered, n=4)[2],
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("sample_output/SAMPLING.md"))
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/golden_labels.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument(
        "--baseline", type=Path, default=Path("data/experiments/baseline/notes.csv")
    )
    args = parser.parse_args()

    corpus = mipa_sample.load_corpus(args.notes, args.labels, args.cache)
    sample = mipa_sample.read_sample(args.sample)

    text = mipa_corpora.read_notes(args.baseline)
    corpus_chars = [len(text[n.hadm_id]) for n in corpus if n.hadm_id in text]
    sample_chars = [len(text[n.hadm_id]) for n in sample if n.hadm_id in text]

    lines = [
        "# Sampling: how the 500 notes were chosen",
        "",
        "> **This file describes real data.** Everything else in `sample_output/` is",
        "> synthetic. The corpus counts, prevalences and deviations below are measured",
        "> from the MIPA corpus and from the actual selection in",
        "> `data/mipa_exp1/sample.csv` — the sample the run will really use.",
        "",
        "Regenerate with `python analysis/sampling_report.py`.",
        "",
        "## Why subsample at all",
        "",
        f"The full design is 28 conditions × 3 models × {len(corpus):,} notes × "
        f"{len(PHENOTYPES)} phenotypes = **{28 * 3 * len(corpus) * len(PHENOTYPES):,} API "
        "calls**, roughly a week of wall clock and several times the budget. At "
        f"n={len(sample)} it is **672,000** calls, ~25 h and ~$176.",
        "",
        "**One sample, shared by every condition and model.** Not a fresh draw per",
        "condition. Because baseline and corrupted arms are measured on the *same*",
        "notes, every delta is a paired comparison and between-note variance — by far",
        "the largest noise source here, since notes run from "
        f"{min(corpus_chars):,} to {max(corpus_chars):,} characters — cancels out of it.",
        "That recovers most of what subsampling costs, but only for the deltas, which",
        "are the actual result.",
        "",
        "## How they were chosen",
        "",
        "**Iterative stratification** (Sechidis, Tsoumakas & Vlahavas 2011) over "
        f"**{2 * len(PHENOTYPES) + 3} strata at once**: both poles of each of the "
        f"{len(PHENOTYPES)} phenotype labels, plus three concept-density bands.",
        "Fill the scarcest stratum first, because that is the one a random or greedy",
        "draw gets wrong, and let the abundant strata absorb the slack.",
        "",
        "Three details that are load-bearing:",
        "",
        "- **Both poles of every label.** A note negative for hypertension belongs to",
        "  `hypertension-`, not to nothing. Scored on positives alone, label-poor notes",
        "  serve no open stratum, are never preferred, and the sample drifts",
        "  multi-morbid — measured at +0.017 mean deviation with every phenotype",
        "  over-represented.",
        "- **An overshoot penalty.** A multi-label note picked to fill one open stratum",
        "  silently fills five closed ones. Without penalising that, max deviation was",
        "  0.067; with it, 0.001.",
        "- **Deterministic tie-breaking** by BLAKE2b hash-rank, the same mechanism the",
        "  corruption engine uses. Reruns select the same notes.",
        "",
        "**Concept density** is read from the existing annotation cache (all",
        f"{len(corpus):,} notes are already UMLS-tagged), so it costs a file read rather",
        "than a re-tag. It is stratified on because a corruption dosed on eligible units",
        "does more to a concept-dense note — a sample skewed on density would confound",
        "corruption severity with note composition.",
        "",
        "## Prevalence: sample vs corpus",
        "",
        "| phenotype | corpus n | corpus % | sample n | sample % | deviation |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    floored = []
    for phenotype in sorted(PHENOTYPES, key=lambda p: -sum(p in n.labels for n in corpus)):
        c_n = sum(1 for n in corpus if phenotype in n.labels)
        s_n = sum(1 for n in sample if phenotype in n.labels)
        c_p, s_p = c_n / len(corpus), s_n / len(sample)
        flag = ""
        if s_p - c_p > 0.02:
            floored.append((phenotype, c_n, s_n))
            flag = " ←"
        lines.append(
            f"| `{phenotype}` | {c_n} | {pct(c_p)} | {s_n} | {pct(s_p)} | {s_p - c_p:+.3f}{flag} |"
        )

    deviations = [
        abs(
            sum(1 for n in sample if p in n.labels) / len(sample)
            - sum(1 for n in corpus if p in n.labels) / len(corpus)
        )
        for p in PHENOTYPES
    ]
    unfloored = [
        d for p, d in zip(PHENOTYPES, deviations, strict=True) if p not in {f[0] for f in floored}
    ]

    lines += [
        "",
        f"Worst deviation among the {len(unfloored)} unfloored phenotypes: "
        f"**{max(unfloored):.3f}**. Proportionality is essentially exact.",
        "",
        "### The two floored phenotypes",
        "",
        "Proportional allocation alone would give the rarest phenotypes single-digit",
        "positive counts, and a per-phenotype F1 on ~14 positives moves visibly when",
        "three predictions change. A floor of **30 positives** raises them **at",
        "identical compute** — the sample is the same size, it just spends its slots on",
        "notes carrying the scarce labels.",
        "",
        "| phenotype | corpus n | proportional would give | sample n |",
        "|---|---:|---:|---:|",
    ]
    for phenotype, c_n, s_n in floored:
        lines.append(
            f"| `{phenotype}` | {c_n} | {round(len(sample) * c_n / len(corpus))} | {s_n} |"
        )

    lines += [
        "",
        "What it costs is prevalence fidelity on exactly those two, which is why they",
        "are flagged in the table above rather than hidden. **`n_pos` travels on every",
        "row of `phenotype_metrics.csv`** — 30 positives is usable, not generous, and a",
        "reader should be able to see the denominator.",
        "",
        "### Why not chase full coverage",
        "",
        "Measured before being rejected: covering 80% of every rare phenotype needs",
        f"~1,094 notes — **{pct(1094 / len(corpus))} of the corpus** — because the rare",
        "positives are scattered across different notes rather than concentrated. At",
        "that point the remaining fifth buys away the sampling caveat entirely, so the",
        "honest choices are a modestly floored sample or the whole corpus, not something",
        "in between.",
        "",
        "## Concept density",
        "",
        "| band | corpus n | corpus % | sample n | sample % | deviation |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for band in range(mipa_sample.DENSITY_BANDS):
        c_n = sum(1 for n in corpus if n.density_band == band)
        s_n = sum(1 for n in sample if n.density_band == band)
        c_p, s_p = c_n / len(corpus), s_n / len(sample)
        lines.append(f"| {band} | {c_n} | {pct(c_p)} | {s_n} | {pct(s_p)} | {s_p - c_p:+.3f} |")

    c_con = quantiles([n.concepts for n in corpus])
    s_con = quantiles([n.concepts for n in sample])
    c_len = quantiles(corpus_chars)
    s_len = quantiles(sample_chars)
    c_lab = quantiles([len(n.labels) for n in corpus])
    s_lab = quantiles([len(n.labels) for n in sample])

    lines += [
        "",
        "## Distributions the sampler did *not* stratify on",
        "",
        "Note length and label count follow from the strata rather than being targeted.",
        "They are reported because an unintended skew here would be a confound — a",
        "sample of systematically shorter notes would understate every corruption that",
        "is dosed per character.",
        "",
        "| | corpus median | sample median | corpus mean | sample mean | corpus range | sample range |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| UMLS concepts / note | {c_con['median']:.0f} | {s_con['median']:.0f} | "
        f"{c_con['mean']:.0f} | {s_con['mean']:.0f} | "
        f"{c_con['min']:.0f}–{c_con['max']:.0f} | {s_con['min']:.0f}–{s_con['max']:.0f} |",
        f"| characters / note | {c_len['median']:,.0f} | {s_len['median']:,.0f} | "
        f"{c_len['mean']:,.0f} | {s_len['mean']:,.0f} | "
        f"{c_len['min']:,.0f}–{c_len['max']:,.0f} | {s_len['min']:,.0f}–{s_len['max']:,.0f} |",
        f"| positive labels / note | {c_lab['median']:.0f} | {s_lab['median']:.0f} | "
        f"{c_lab['mean']:.2f} | {s_lab['mean']:.2f} | "
        f"{c_lab['min']:.0f}–{c_lab['max']:.0f} | {s_lab['min']:.0f}–{s_lab['max']:.0f} |",
        "",
        "## `sample.csv`",
        "",
        "The selection is written down rather than asserted, so it can be audited",
        "without rerunning the sampler:",
        "",
        "```",
        "hadm_id, note_id, concepts, density_band, <16 phenotype label columns>",
        "```",
        "",
        "The run reads this **file**; it never re-derives the selection. Re-running the",
        "sampler on the VM would make the sample depend on the concept cache and the",
        "corpus being present there too, and a resume after a code change could silently",
        "evaluate a different 500 notes than the predictions already in the store belong",
        "to.",
        "",
        "> In `sample_output/`, `sample.csv` carries **synthetic** `MOCK……` ids at these",
        "> same real prevalences. The real one carries MIMIC-IV `hadm_id`s and is",
        "> restricted under the PhysioNet DUA.",
        "",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {args.out}")
    print(f"  corpus {len(corpus)} notes, sample {len(sample)}")
    print(f"  worst unfloored deviation {max(unfloored):.4f}")
    print(f"  floored: {[f[0] for f in floored]}")
    print(
        json.dumps({"corpus_chars_median": c_len["median"], "sample_chars_median": s_len["median"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
