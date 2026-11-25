# mipa-corrupt

**What controlled corruption of clinical notes does to a language model's
phenotyping, measured end to end.**

This repository is the pipeline of one study. It corrupts MIMIC-IV discharge
summaries in three ways, asks a language model the same phenotype questions of
the clean and the corrupted notes, and counts what changed. The corruption
itself is done by a separate, public package,
[RobustEHR](https://github.com/open-health-data-lab/RobustEHR), which this
repository installs as a dependency.

The split is deliberate. `robustehr` decides what changed in a note and by how
much; this repository decides what a model then said about it. Neither can
reach into the other, so a corruption cannot be tuned to a result and a result
cannot be explained by an undisclosed corruption.

The paper's tables and figures are built from this pipeline's outputs in a
separate analysis repository and are not part of this one.

## The three experiments

All three use the same two operators, typographical errors and
optical-character-recognition (OCR) errors. What differs is where the errors
are allowed to land.

| Experiment | Errors land on | Coverage | Notes |
|---|---|---|---|
| 1 | any word of the note | 5%, 10%, 15% of words | 1,388 corrupted, 500 scored |
| 2 | clinical words only | 5%, 10%, 15% of clinical words | 1,388 corrupted, 500 scored |
| 3 | the words that are evidence for one phenotype | every such word, one character each | 500, once per phenotype (15 phenotypes) |

Experiment 1 also runs seven structural corruptions (headers deleted or
renamed, lists flattened, line breaks and spaces removed, sections duplicated,
numerals spelled out).

The model is asked the 16 questions of the
[MIPA](https://github.com/open-health-data-lab/MIPA) zero-shot protocol,
unchanged, through OpenRouter. The study reports Gemma 3 12B and Gemma 3 4B;
the runner's default list also includes Gemma 3 27B, and `--models` selects.

## Install

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

This installs RobustEHR 0.2.0 from its public release tag; no checkout of it is
needed. `requirements-lock.txt` lists the exact versions of every package in
the environment the pipeline was last verified in:

```bash
uv pip install -r requirements-lock.txt && uv pip install -e . --no-deps
```

Add `".[cloud]"` only for the Google Cloud runner in `deploy/`.

## Try it without data

```bash
pytest
```

The tests run against `sample_output/`, a synthetic copy of the pipeline's
outputs in which every value is fabricated and labelled as such. They need no
MIMIC-IV access, no UMLS licence and no API key.

## Run it

The inputs are licensed and are not in this repository. [`data/README.md`](data/README.md)
says what they are, where to get them and what the pipeline writes. Run every
command from a directory that holds `data/`.

| # | Step | Command | Writes |
|---|---|---|---|
| 1 | Corrupt: Experiments 1 and 2 | `python experiments/exp1_exp2/run_experiments.py` | `data/experiments/exp1/`, `exp2/`: one corpus per corruption and severity |
| 2 | Draw the scored sample | `mipa-exp1 sample` | `data/mipa_exp1/sample.csv`, 500 notes stratified by phenotype |
| 3 | Score Experiments 1 and 2 | `mipa-exp1 preflight`, `mipa-exp1 run`, `mipa-exp1 analyze` | predictions; `overall_metrics.csv`, `phenotype_metrics.csv`, `robustness_deltas.csv` |
| 4 | Corrupt: Experiment 3 | `python experiments/exp3_corrected/gen_exp3_corrected_dataset.py` | `data/experiments/exp3_corrected/`: 30 corpora, 15 phenotypes × 2 operators |
| 5 | Score Experiment 3 | `python experiments/exp3/run_exp3.py --experiment exp3_corrected --all-questions` | predictions; `results/measurements/exp3_corrected_results.json` |
| 6 | Tabulate Experiment 3 | `python experiments/exp3/exp3_to_csv.py`, then `python experiments/exp3/render_exp3_tables.py` | per-question deltas and label changes |
| 7 | Describe the corpora | `python experiments/exp1_exp2/sample_table1.py`; `python analysis/table1_short.py`; `python analysis/sample_appropriateness.py` | corpus characteristics; how the 500 compare with the 1,388 |
| 8 | Check where edits landed | `python analysis/edit_placement.py`; `python analysis/targeting_showcase.py` | share of edits on clinical words, by experiment |
| 9 | Check Experiment 3's reach | `python experiments/exp3_corrected/label_coverage.py --experiments data/experiments/exp3_corrected --notes data/golden_notes.csv --labels data/golden_labels.csv` | how many labelled cases each phenotype's target edited |

Every script documents its flags in its docstring and under `--help`. The
models, the salt (`rep0`), the concept-cache digest and the sampling seed are
defaults in the scripts, so running a step with no flags runs the study's
configuration. Predictions are stored by content, so rerunning a finished step
costs nothing. [`experiments/exp3_corrected/README.md`](experiments/exp3_corrected/README.md)
has the exact commands for Experiment 3, and
[`docs/quickstart.md`](docs/quickstart.md) walks one corpus through RobustEHR
by hand.

To read what a corruption did, `python experiments/exp3_corrected/sample_notes.py`
writes five notes per phenotype, each as the clean note, the two corrupted
versions and a table of only the words that changed.

## What reproduces, and how

**The corrupted corpora reproduce by replay.** Each corpus is stored with an
edit script and a SHA-256 per note. `robustehr replay` applies the script to
your own copy of the notes and checks every hash.
[`release/README.md`](release/README.md) explains how the scripts are exported
for sharing with credentialed users, and what was checked.

**Regenerating from the seed gives the same design with different draws, with
one exception.** The corpora were generated on pre-release builds of RobustEHR.
Every random draw is seeded with the package's seed specification and the
operator's version; the package was renamed after Experiments 1 and 2 were
generated, and the OCR operator's version moved after Experiment 3. The
typographical-error corpora of Experiment 3 are the exception: regenerated
with RobustEHR 0.2.0, the hypertension corpus is byte-identical to the study's
on all 500 notes.

**The model's answers do not reproduce exactly, by design of the protocol.**
MIPA's settings are kept: temperature 0.5, no seed, served by whichever
provider OpenRouter routes to. Two runs on identical notes disagree on a small
share of answers, and the study measures that share and reports it as the
floor against which a corruption's effect is read. The stored predictions are
the record of the study.

## Layout

| Path | What it is |
|---|---|
| `src/mipa/` | The scoring harness: the MIPA protocol, the OpenRouter client, the prediction store, metrics, the sampler |
| `experiments/exp1_exp2/` | Corpus generation for Experiments 1 and 2 |
| `experiments/exp3_corrected/` | Experiment 3: corpus generation, the checks on its phenotype targets, and the reading sample |
| `experiments/exp3/` | The prediction runner and table renderers Experiment 3 uses |
| `analysis/` | Corpus description, edit placement, the concept-list export, and the synthetic sample output |
| `release/` | Exports the study's edit scripts in shareable form and checks that each replays |
| `docs/` | A walkthrough, the phenotype concept sets as UMLS identifiers, and the method note for Experiments 4 and 5 |
| `deploy/` | Scripts to run the scoring on a Google Cloud VM |
| `sample_output/` | Synthetic example output. Every number in it is fabricated |
| `tests/` | The test suite |

**The paper's Experiment 3 is `experiments/exp3_corrected/`.** Experiment 3
was run three times and only the third is reported; `exp3bis` is the second,
superseded version, not the one in the paper.
[`experiments/README.md`](experiments/README.md) sets the three side by side.

Earlier and later work is kept for the record and is not part of the study's
reported results: `experiments/exp3/gen_exp3_dataset.py` and
`experiments/exp3bis/` are the first two versions of Experiment 3, superseded
because their targets missed most written diagnoses and the first one's OCR
arm replaced whole words; `experiments/exp4/`, `experiments/exp5/` and
`experiments/causal_probe/` corrupt negation and other assertion cues, and
probe whether targeted corruption moves the model's answer.

## Configuration and secrets

No project id, bucket name or service-account address is written into any
file. The deploy scripts read them from the environment:

```bash
export MIPA_PROJECT=your-gcp-project
export MIPA_BUCKET=your-bucket
bash deploy/provision.sh
```

The OpenRouter key is never in this repository. Locally, set
`OPENROUTER_API_KEY`; on the VM it is fetched from Secret Manager at run time.

`tests/test_mipa_protocol.py` checks that the prompts here match MIPA's
character for character. It needs a MIPA checkout and skips without one:

```bash
export MIPA_SOURCE_ROOT=/path/to/MIPA
```

## Data and licence

The code is Apache-2.0.

Everything under `data/` and `results/` is ignored by git and must stay out of
it: MIMIC-IV note text under the PhysioNet Credentialed Health Data Use
Agreement, the UMLS Metathesaurus under its licence, and everything derived
from either, including corrupted notes, prediction stores and edit scripts.
The phenotype concept sets in `docs/appendix/` are UMLS identifiers only;
resolving them to names needs your own UMLS licence.
