# MIPA Experiment 1 — downstream robustness runner

Runs the **existing MIPA zero-shot phenotyping protocol** over the Experiment 1
corruption corpora and reports what corruption costs a downstream model.

Nothing here is imported by the corruption engine. `mipa` depends on
`robustehr`; `robustehr` does not depend on `mipa`.

## Scale

| | |
|---|---|
| conditions | 28 — clean baseline + 9 corruptions × 3 severities |
| models | 3 — `google/gemma-3-{4b,12b,27b}-it` |
| notes | 500, stratified, **shared by every condition and model** |
| phenotypes | 16 |
| **predictions** | 28 × 3 × 500 × 16 = **672,000** |
| cost | **~$176** ($48 / $49 / $79 for 4b / 12b / 27b) |
| wall clock | ~25 h at `--concurrency 12`, ~13 h at 24 |

Cost and throughput are measured, not assumed: projected from a live 96-call
smoke run (median latency 1.63 s, 3.32 prompt chars per billed token) applied to
the actual character count of all 28 corpora over the selected 500 notes, priced
from OpenRouter's `/models`. Notes are longer than the original brief assumed —
~5,300 prompt tokens per call against an estimated 3,550 — so the figure is
higher than the $140 first planned. `status` reports spend as it accrues.

The sample is shared so every baseline-vs-corrupted comparison is **paired**:
between-note variance — by far the largest noise source here, since notes run
from 2k to 40k characters — cancels out of every delta.

`google/gemma-4-31b-it` from the original brief does not exist; Gemma 3 is the
current generation. `preflight` verifies all three slugs against OpenRouter's
`/models` before anything costs money.

## Running it

```bash
pip install -e '.[dev]'                 # add ,cloud on the VM

mipa-exp1 sample                   # choose 500 notes, once
mipa-exp1 preflight --live         # must be green before `run`
mipa-exp1 run                      # resumable; safe to kill
mipa-exp1 status                   # progress, cost, parse failures
mipa-exp1 analyze                  # the result tables
```

`run` is built to be killed. Every answer is written the moment it lands, keyed
by `sha256(document_id|model|condition|phenotype)`, so a restart is a
set-difference against the store. There is no run state anywhere else. Rerunning
a finished run issues zero HTTP requests — `tests/test_mipa_exp1.py` asserts that
by counting requests, not by inspecting bookkeeping.

The key is read from `OPENROUTER_API_KEY`, then Secret Manager when `--project`
is set, then `--api-key-file`. It is never logged, never written to an output
file, and never committed.

## Outputs

| file | contents |
|---|---|
| `predictions.csv.gz` | one row per prediction with `y_true` — the unaggregated matrix, for anything with note-level structure (paired tests, bootstrap CIs over notes, mixed-effects models) |
| `overall_metrics.csv` | per model × condition: macro/micro F1, accuracy, recalls, `parse_failure_rate` |
| `phenotype_metrics.csv` | per model × condition × phenotype: f1, precision, recall, tp/fp/tn/fn, **`n_pos`** |
| `robustness_deltas.csv` | **the headline** — baseline vs corrupted vs delta, per model × corruption × severity |
| `parse_failures.csv` | failures with raw output, for adjudication |
| `operational.csv.gz` | latency, attempts, tokens, cost — kept apart from results |
| `run_summary.json` | models, conditions, cost, protocol departures |

No note text appears in any result file. The column sets are frozen by a test,
because the way a note fragment reaches a shipped CSV is a new column nobody
thought about.

## Four decisions that change what the numbers mean

**MIPA's `clean_text` is not applied.** It collapses `\s+` to a single space
before every prompt. Under it, `loss_of_text_structure` becomes byte-identical
to baseline and that arm would report exactly zero degradation *by
construction*. Recorded in `run_summary.json`.

**The system prompt is sent.** MIPA's sync path sends it and its async path
drops it; the asymmetry is a bug, not a design. `SEND_SYSTEM_PROMPT` flips it.

**Parse failures are excluded pairwise, not by note.** MIPA's
`filter_incomplete_parsing` keeps only notes where every chunk parsed — under
corruption that evaluates each arm on the notes that survived corruption best,
biasing the measured degradation toward zero by the very thing being measured.

**The delta table is paired on the intersection.** Excluding pairwise is right
for a marginal number and wrong for a difference: an arm that failed to parse 3%
of pairs would otherwise be compared against a baseline scored on a different
denominator. `n_paired` and `n_dropped` travel with every delta row.

## A transport failure is not a result

`ok` / `no_json` / `no_status` / `bad_value` mean the model answered — final,
never retried, never overwritten. Asking again until the response parsed would be
resampling until the answer was agreeable.

`http_error` / `timeout` / `exhausted` mean the request never produced a
response. Nothing was learned about the model, so the row is kept for the
operational record but the key stays retriable across restarts. Treating these as
answered is how a twenty-minute OpenRouter outage becomes permanent, unrecoverable
"degradation" — landing on whichever conditions happened to be running at the
time, which is a confound with corruption severity itself.

## Layout

| module | |
|---|---|
| `protocol.py` | MIPA's prompts, phenotypes and parser, vendored with per-line provenance and a drift test against MIPA's source |
| `sample.py` | iterative stratification over 16 labels + concept density |
| `corpora.py` | condition discovery and note reading |
| `client.py` | async OpenRouter with jittered backoff and adaptive per-model concurrency |
| `store.py` | SQLite/WAL, content-addressed keys, O(1) resume |
| `metrics.py` | confusion counts → macro/micro aggregates → delta table |
| `cloud.py` | Secret Manager and GCS, imported lazily |
| `exp1.py` | the CLI |

## Deploying

```bash
export MIPA_PROJECT=your-gcp-project
export MIPA_BUCKET=your-bucket

mipa-exp1 upload --bucket "$MIPA_BUCKET"   # corpora + sample + labels
bash deploy/provision.sh                   # SA, secret, bucket IAM, VM
```

`provision.sh` attaches `deploy/bootstrap.sh` as the instance startup script, so
the VM installs itself, pulls the corpora, runs `preflight`, and starts the
service with **no SSH session**. A failing preflight stops it before anything is
spent, with the reason on the serial console.

systemd runs `deploy/run_and_publish.sh`, which is what closes the loop without a
human: `run` → (if complete) `analyze` → publish to
`gs://<bucket>/results/experiment_1/<run-id>/` → write a DONE marker. An
incomplete run exits nonzero so `Restart=on-failure` resumes it; a completed one
exits 0 and stays stopped; a restart after publishing does nothing.

The bucket layout is **discovered and verified**, not assumed — bootstrap counts
`notes.csv` objects and checks for `sample.csv` and `golden_labels.csv`, and dies
with the listing if the tree is not what the runner expects.

The VM does not delete itself when the run finishes. It will keep billing until
`gcloud compute instances delete`.

## Working before the run finishes

`analysis/make_sample_output.py` writes a synthetic copy of every output table at
the real dimensions (672,000 predictions), so downstream analysis can be built and
debugged now. It drives the same `mipa.metrics` functions `analyze` does, so the
schema cannot drift from production. See `sample_output/README.md` — every number
in it is fabricated.
