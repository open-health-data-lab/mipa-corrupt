# Sampling: how the 500 notes were chosen

> **This file describes real data.** Everything else in `sample_output/` is
> synthetic. The corpus counts, prevalences and deviations below are measured
> from the MIPA corpus and from the actual selection in
> `data/mipa_exp1/sample.csv` — the sample the run will really use.

Regenerate with `python analysis/sampling_report.py`.

## Why subsample at all

The full design is 28 conditions × 3 models × 1,388 notes × 16 phenotypes = **1,865,472 API calls**, roughly a week of wall clock and several times the budget. At n=500 it is **672,000** calls, ~25 h and ~$176.

**One sample, shared by every condition and model.** Not a fresh draw per
condition. Because baseline and corrupted arms are measured on the *same*
notes, every delta is a paired comparison and between-note variance — by far
the largest noise source here, since notes run from 2,824 to 33,641 characters — cancels out of it.
That recovers most of what subsampling costs, but only for the deltas, which
are the actual result.

## How they were chosen

**Iterative stratification** (Sechidis, Tsoumakas & Vlahavas 2011) over **35 strata at once**: both poles of each of the 16 phenotype labels, plus three concept-density bands.
Fill the scarcest stratum first, because that is the one a random or greedy
draw gets wrong, and let the abundant strata absorb the slack.

Three details that are load-bearing:

- **Both poles of every label.** A note negative for hypertension belongs to
  `hypertension-`, not to nothing. Scored on positives alone, label-poor notes
  serve no open stratum, are never preferred, and the sample drifts
  multi-morbid — measured at +0.017 mean deviation with every phenotype
  over-represented.
- **An overshoot penalty.** A multi-label note picked to fill one open stratum
  silently fills five closed ones. Without penalising that, max deviation was
  0.067; with it, 0.001.
- **Deterministic tie-breaking** by BLAKE2b hash-rank, the same mechanism the
  corruption engine uses. Reruns select the same notes.

**Concept density** is read from the existing annotation cache (all
1,388 notes are already UMLS-tagged), so it costs a file read rather
than a re-tag. It is stratified on because a corruption dosed on eligible units
does more to a concept-dense note — a sample skewed on density would confound
corruption severity with note composition.

## Prevalence: sample vs corpus

| phenotype | corpus n | corpus % | sample n | sample % | deviation |
|---|---:|---:|---:|---:|---:|
| `hypertension` | 940 | 67.7% | 339 | 67.8% | +0.001 |
| `depression` | 679 | 48.9% | 245 | 49.0% | +0.001 |
| `diabetes_type_2` | 393 | 28.3% | 142 | 28.4% | +0.001 |
| `vte_past` | 312 | 22.5% | 112 | 22.4% | -0.001 |
| `obesity` | 286 | 20.6% | 103 | 20.6% | -0.000 |
| `hfpef` | 217 | 15.6% | 78 | 15.6% | -0.000 |
| `metastatic_cancer` | 168 | 12.1% | 61 | 12.2% | +0.001 |
| `rheumatoid_arthritis` | 164 | 11.8% | 59 | 11.8% | -0.000 |
| `alcohol_abuse` | 155 | 11.2% | 56 | 11.2% | +0.000 |
| `diabetes_type_1` | 135 | 9.7% | 49 | 9.8% | +0.001 |
| `hfref` | 122 | 8.8% | 44 | 8.8% | +0.000 |
| `sle` | 113 | 8.1% | 41 | 8.2% | +0.001 |
| `dementia` | 102 | 7.3% | 37 | 7.4% | +0.001 |
| `c_diff_past` | 101 | 7.3% | 36 | 7.2% | -0.001 |
| `c_diff_complication` | 42 | 3.0% | 30 | 6.0% | +0.030 ← |
| `vte_complication` | 39 | 2.8% | 30 | 6.0% | +0.032 ← |

Worst deviation among the 14 unfloored phenotypes: **0.001**. Proportionality is essentially exact.

### The two floored phenotypes

Proportional allocation alone would give the rarest phenotypes single-digit
positive counts, and a per-phenotype F1 on ~14 positives moves visibly when
three predictions change. A floor of **30 positives** raises them **at
identical compute** — the sample is the same size, it just spends its slots on
notes carrying the scarce labels.

| phenotype | corpus n | proportional would give | sample n |
|---|---:|---:|---:|
| `c_diff_complication` | 42 | 15 | 30 |
| `vte_complication` | 39 | 14 | 30 |

What it costs is prevalence fidelity on exactly those two, which is why they
are flagged in the table above rather than hidden. **`n_pos` travels on every
row of `phenotype_metrics.csv`** — 30 positives is usable, not generous, and a
reader should be able to see the denominator.

### Why not chase full coverage

Measured before being rejected: covering 80% of every rare phenotype needs
~1,094 notes — **78.8% of the corpus** — because the rare
positives are scattered across different notes rather than concentrated. At
that point the remaining fifth buys away the sampling caveat entirely, so the
honest choices are a modestly floored sample or the whole corpus, not something
in between.

## Concept density

| band | corpus n | corpus % | sample n | sample % | deviation |
|---|---:|---:|---:|---:|---:|
| 0 | 461 | 33.2% | 166 | 33.2% | -0.000 |
| 1 | 461 | 33.2% | 166 | 33.2% | -0.000 |
| 2 | 466 | 33.6% | 168 | 33.6% | +0.000 |

## Distributions the sampler did *not* stratify on

Note length and label count follow from the strata rather than being targeted.
They are reported because an unintended skew here would be a confound — a
sample of systematically shorter notes would understate every corruption that
is dosed per character.

| | corpus median | sample median | corpus mean | sample mean | corpus range | sample range |
|---|---:|---:|---:|---:|---:|---:|
| UMLS concepts / note | 622 | 634 | 642 | 647 | 152–1716 | 172–1716 |
| characters / note | 11,546 | 11,746 | 12,054 | 12,206 | 2,824–33,641 | 3,301–33,641 |
| positive labels / note | 3 | 3 | 2.86 | 2.92 | 0–8 | 0–8 |

## `sample.csv`

The selection is written down rather than asserted, so it can be audited
without rerunning the sampler:

```
hadm_id, note_id, concepts, density_band, <16 phenotype label columns>
```

The run reads this **file**; it never re-derives the selection. Re-running the
sampler on the VM would make the sample depend on the concept cache and the
corpus being present there too, and a resume after a code change could silently
evaluate a different 500 notes than the predictions already in the store belong
to.

> In `sample_output/`, `sample.csv` carries **synthetic** `MOCK……` ids at these
> same real prevalences. The real one carries MIMIC-IV `hadm_id`s and is
> restricted under the PhysioNet DUA.
