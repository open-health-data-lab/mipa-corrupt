# Data: what the pipeline reads, and where it comes from

Nothing in this directory is committed except this file. The inputs are
licensed, and everything derived from them carries the same licence: a
corrupted MIMIC-IV note is still a MIMIC-IV note, and a prediction keyed by an
admission identifier is patient-level data.

## What you need

| Input | File | Where it comes from | Licence |
|---|---|---|---|
| Discharge summaries | `golden_notes.csv` with columns `subject_id`, `hadm_id`, `note_id`, `text` | MIMIC-IV-Note, restricted to the 1,388 admissions annotated in the MIMIC-IV Phenotype Atlas (MIPA). The extraction query is `data/notes.sql` in [RobustEHR](https://github.com/open-health-data-lab/RobustEHR) | PhysioNet Credentialed Health Data Use Agreement |
| Reference labels | `golden_labels.csv`: `note_id`, `hadm_id`, and one 0/1 column per question (16 questions) | [MIPA](https://github.com/open-health-data-lab/MIPA) | PhysioNet, as above |
| UMLS release | `umls/` (2026AA was used) | [UMLS Terminology Services](https://uts.nlm.nih.gov/) | UMLS Metathesaurus License |
| Concept index | `quickumls_index/` | built from the UMLS release; RobustEHR `data/quickumls_index/README.md` | UMLS |
| Hierarchy and crosswalk | `umls_isa_mth.json`, `snomed_el/`, `umls_facets.json` | built from the UMLS release with `robustehr concepts`; RobustEHR `data/README.md` | UMLS |
| Concept cache | `concept_cache/` | written by the first run that tags the notes; later runs read it | UMLS and PhysioNet |
| Model access | environment variable `OPENROUTER_API_KEY` | your own [OpenRouter](https://openrouter.ai/) account | — |

Experiments 1 and 2 need the notes and, for Experiment 2, the concept index.
Experiment 3 needs the notes, the hierarchy and crosswalk, and the concept
cache. Scoring needs the labels and model access.

Sending MIMIC-IV text to an online model service is governed by PhysioNet's
policy on responsible use of credentialed data. Check that your provider
settings satisfy it before running any prediction step.

## What the pipeline writes here

| Path | Written by | Holds |
|---|---|---|
| `experiments/exp1/`, `experiments/exp2/` | `experiments/exp1_exp2/run_experiments.py` | one directory per corruption and severity: `notes.csv` (corrupted text), `edits.jsonl`, `dose.jsonl`, `manifest.json` |
| `experiments/exp3_corrected/` | `experiments/exp3_corrected/gen_exp3_corrected_dataset.py` | the same, one directory per phenotype and operator |
| `mipa_exp1/` | `mipa-exp1 sample`, `run`, `analyze` | the 500-note sample, the prediction store, metric tables |
| `mipa_exp3_corrected/` | `experiments/exp3/run_exp3.py --experiment exp3_corrected` | predictions and per-question deltas for Experiment 3 |
| `release_ledgers/` | `release/export_ledgers.py` | edit scripts in shareable form, each checked by replay |
| `exp3_samples/` | `experiments/exp3_corrected/sample_notes.py` | clean and corrupted notes side by side, for reading |

Aggregate results that carry no note text and no identifier are written under
`results/measurements/`, which is also ignored.

## Running without any of it

`sample_output/` at the repository root is a synthetic copy of the pipeline's
outputs, every value fabricated and labelled as such. The test suite runs
against it, so `pytest` needs no data, no licence and no key.
