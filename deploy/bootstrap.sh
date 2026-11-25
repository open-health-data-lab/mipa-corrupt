#!/usr/bin/env bash
#
# First-boot bootstrap. Attach as the instance's `startup-script` and the VM
# brings itself all the way to a running experiment with no SSH session.
#
# Written to be re-runnable: GCE re-executes the startup script on every boot,
# so every step checks for what it is about to create. A reboot mid-run
# therefore reinstalls nothing and simply lets systemd resume.
#
# **The GCS layout is verified, not assumed.** The corpora live at the bucket
# *root* — `baseline/notes.csv` and `exp1/<corruption>/<severity>/notes.csv` —
# confirmed against the live bucket (28 notes.csv, matching the local tree
# exactly). This script re-checks that before downloading and stops with an
# explicit message rather than starting a 25-hour run against a tree that is not
# shaped the way the runner expects.
#
# The OpenRouter key is never handled here. It lives in Secret Manager and is
# read at runtime by the service account.

set -euo pipefail

PROJECT="${MIPA_PROJECT:?set MIPA_PROJECT to your GCP project id}"
BUCKET="${MIPA_BUCKET:?set MIPA_BUCKET to your GCS bucket}"
# The corpora sit at the bucket root (baseline/, exp1/), not under a
# prefix. Verified against the live bucket, not assumed.
PREFIX="${MIPA_GCS_PREFIX:-}"
SRC="gs://${BUCKET}${PREFIX:+/${PREFIX}}"
CODE_TARBALL="${MIPA_CODE_TARBALL:-code/mipa-corrupt.tar.gz}"
ROOT="${MIPA_ROOT:-/opt/mipa-corrupt}"
DATA="${ROOT}/data"
RUNNER_USER="mipa"

say() { printf '\n=== %s ===\n' "$1"; }
die() { printf '\nFATAL: %s\n' "$1" >&2; exit 1; }

say "system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git

id -u "${RUNNER_USER}" >/dev/null 2>&1 || useradd -r -m -d "/home/${RUNNER_USER}" "${RUNNER_USER}"

say "code"
# Shipped as a tarball in the bucket rather than cloned from GitHub. The runner
# is developed alongside uncommitted corpus work, so `git clone` would give the
# VM a tree without the evaluation package at all. The tarball is exactly the
# code that was tested, and `upload-code` refreshes it.
#
# Re-extracted on every boot on purpose: it is the one way to push a fix to a
# running experiment without rebuilding the instance. Data lives outside the
# tree, so extraction never touches the store.
mkdir -p "${ROOT}"
gcloud storage cp "gs://${BUCKET}/${CODE_TARBALL}" /tmp/mipa-corrupt.tar.gz \
  || die "cannot fetch gs://${BUCKET}/${CODE_TARBALL}.
Run \`bash deploy/upload_code.sh\` from the workstation that has the code."
tar -xzf /tmp/mipa-corrupt.tar.gz -C "${ROOT}"
rm -f /tmp/mipa-corrupt.tar.gz

say "python environment"
[[ -x "${ROOT}/.venv/bin/python" ]] || python3 -m venv "${ROOT}/.venv"
"${ROOT}/.venv/bin/pip" install -q --upgrade pip
"${ROOT}/.venv/bin/pip" install -q -e "${ROOT}[cloud]"

say "inspecting ${SRC}"
listing=$(gcloud storage ls "${SRC}/**" 2>/dev/null || true)
[[ -n "${listing}" ]] || die "cannot read ${SRC} — check the instance
service account has roles/storage.objectViewer on the bucket, and that the
corpora were uploaded (\`mipa-exp1 upload --bucket ${BUCKET}\`)."

n_notes=$(grep -c '/notes\.csv$' <<<"${listing}" || true)
echo "found ${n_notes} notes.csv object(s)"
[[ "${n_notes}" -ge 28 ]] || die "expected at least 28 notes.csv objects (baseline + 9
corruptions x 3 severities), found ${n_notes}. The corpus tree in the bucket is
not what the runner expects. Listing:
$(head -40 <<<"${listing}")"

grep -q '/sample\.csv$'        <<<"${listing}" || die "${SRC}/sample.csv is missing.
Run \`mipa-exp1 upload --bucket ${BUCKET}\` from a workstation that has the sample."
grep -q '/golden_labels\.csv$' <<<"${listing}" || die "${SRC}/golden_labels.csv is missing.
Run \`mipa-exp1 upload --bucket ${BUCKET}\` from a workstation that has the sample."

say "downloading corpora"
mkdir -p "${DATA}/mipa_exp1"
# `rsync` not `cp -r`: a reboot part-way through a 450 MB download must resume
# rather than restart, and re-running on an already-synced disk must be a no-op.
# Excludes, each for its own reason:
#   edits/dose.jsonl  1.3 GB of corruption provenance inference never reads
#   results/          our own published output — syncing the bucket root back
#                     would re-download results on every reboot, and could
#                     overwrite a local store with a stale checkpoint
#   .DS_Store         macOS debris that rode along with the upload
gcloud storage rsync -r \
  --exclude='(.*(edits|dose)\.jsonl|results/.*|.*\.DS_Store)$' \
  "${SRC}" "${DATA}/experiments"

# The sample and labels land where the runner expects them, not where rsync put
# them. Copied rather than symlinked so a later rsync cannot rewrite the
# selection underneath a run in progress.
cp "${DATA}/experiments/sample.csv"        "${DATA}/mipa_exp1/sample.csv"
cp "${DATA}/experiments/golden_labels.csv" "${DATA}/golden_labels.csv"

chown -R "${RUNNER_USER}:${RUNNER_USER}" "${DATA}/mipa_exp1"

say "preflight"
export MIPA_PROJECT="${PROJECT}" MIPA_BUCKET="${BUCKET}"
sudo -u "${RUNNER_USER}" \
  MIPA_PROJECT="${PROJECT}" MIPA_BUCKET="${BUCKET}" \
  "${ROOT}/.venv/bin/mipa-exp1" preflight \
    --experiments "${DATA}/experiments" \
    --sample "${DATA}/mipa_exp1/sample.csv" \
    --labels "${DATA}/golden_labels.csv" \
  || die "preflight failed — see the PASS/FAIL lines above. Nothing has been started
and nothing has been spent. Fix the failing check and reboot, or run
\`bash ${ROOT}/deploy/bootstrap.sh\` again."

say "service"
# Site configuration for the unit. 0644 because systemd reads it as root before
# dropping to the `mipa` user; it holds identifiers only, never the API key.
cat > /etc/mipa-exp1.env <<ENVEOF
MIPA_PROJECT=${PROJECT}
MIPA_BUCKET=${BUCKET}
ENVEOF
chmod 0644 /etc/mipa-exp1.env

install -m 0755 "${ROOT}/deploy/run_and_publish.sh" /usr/local/bin/mipa-run-and-publish
install -m 0644 "${ROOT}/deploy/mipa-exp1.service"  /etc/systemd/system/mipa-exp1.service
systemctl daemon-reload
systemctl enable --now mipa-exp1

cat <<EOF

=== running ===

  journalctl -u mipa-exp1 -f          follow progress
  systemctl status mipa-exp1          is it alive
  ${ROOT}/.venv/bin/mipa-exp1 status \\
      --store ${DATA}/mipa_exp1/predictions.sqlite \\
      --sample ${DATA}/mipa_exp1/sample.csv

Results are published to gs://${BUCKET}/results/<experiment>/<run-id>/ when the run
completes. The SQLite store is checkpointed there every condition boundary.
EOF
