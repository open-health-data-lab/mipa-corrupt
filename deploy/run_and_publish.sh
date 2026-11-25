#!/usr/bin/env bash
#
# What systemd actually runs: predict, then analyse, then publish.
#
# `mipa-exp1 run` exits 0 only when every prediction is answered and
# nonzero otherwise, which is what lets `Restart=on-failure` mean "resume".
# This wrapper preserves that contract exactly — a nonzero run exits nonzero
# here too, so systemd retries — and adds the finishing steps that turn a
# complete run into results in the bucket without anybody logging in.
#
# The DONE marker is what stops the loop from re-analysing on every restart
# after completion. It is not the source of truth for completeness — the SQLite
# store is — it is just a cheap guard against redoing work that is already
# published.

set -uo pipefail

ROOT="${MIPA_ROOT:-/opt/mipa-corrupt}"
BIN="${ROOT}/.venv/bin/mipa-exp1"
DATA="${ROOT}/data/mipa_exp1"
RUN_ID="${MIPA_RUN_ID:-run1}"
# Which corruption tree to evaluate, and which store to write. Parameterised so
# a second experiment reuses this wrapper rather than forking it — and so the
# store is an explicit choice: Experiment 2's conditions are namespaced
# (`exp2/typographical_errors/low`), so they can share a store with Experiment 1
# without key collision, and sharing means the clean baseline is answered once
# rather than paid for twice.
EXPERIMENT="${MIPA_EXPERIMENT:-exp1}"
STORE="${MIPA_STORE:-${DATA}/predictions.sqlite}"
# Keyed on experiment AND run-id. Run-ids are per-experiment — Experiment 1 and
# Experiment 2 both call their first run `run1` — so a marker keyed on run-id
# alone lets one experiment's completion silently cancel another's start. That
# is not hypothetical: exp2 was launched, found exp1's `.published-run1`, and
# exited "nothing to do" without making a single prediction.
DONE="${DATA}/.published-${EXPERIMENT}-${RUN_ID}"

# MIPA_MODELS restricts the run. Unset means all three. Because the store is
# keyed per (document, model, condition, phenotype), running a subset now and
# the rest later is a resume, not a rerun — the second pass fills the gap and
# repeats nothing.
models=()
if [[ -n "${MIPA_MODELS:-}" ]]; then
  read -r -a models <<< "${MIPA_MODELS}"
  models=(--models "${models[@]}")
fi

common=(
  --experiments "${ROOT}/data/experiments"
  --sample      "${DATA}/sample.csv"
  --labels      "${ROOT}/data/golden_labels.csv"
  --store       "${STORE}"
  --experiment  "${EXPERIMENT}"
)

if [[ -f "${DONE}" ]]; then
  echo "already published ${RUN_ID}; nothing to do."
  echo "to force a re-analysis: rm ${DONE} && systemctl restart mipa-exp1"
  exit 0
fi

echo "=== run (resumable) ==="
# `${models[@]+...}` rather than `"${models[@]}"`: under `set -u` an empty
# array is an unbound variable on older bash, and this file also gets
# syntax-checked on a macOS 3.2 shell.
"${BIN}" run "${common[@]}" ${models[@]+"${models[@]}"} \
  --concurrency "${MIPA_CONCURRENCY:-12}" \
  --per-model-concurrency "${MIPA_PER_MODEL:-3}" \
  --max-per-model-concurrency "${MIPA_MAX_PER_MODEL:-16}" \
  --run-id "${RUN_ID}"
status=$?

if [[ ${status} -ne 0 ]]; then
  # Incomplete. Exit nonzero so systemd restarts us after RestartSec and the
  # store's completed-key set makes the retry a pure remainder.
  echo "run incomplete (exit ${status}); systemd will resume."
  exit "${status}"
fi

echo "=== analyze ==="
"${BIN}" analyze "${common[@]}" \
  --results "${DATA}/results" \
  --run-id "${RUN_ID}" || exit $?

# Only now: analysis succeeded and `analyze` published to GCS itself.
date -u +"%Y-%m-%dT%H:%M:%SZ" > "${DONE}"
echo "=== complete: results published for ${RUN_ID} ==="
