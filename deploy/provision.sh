#!/usr/bin/env bash
#
# Provision the Experiment 1 runner on GCP.
#
# Run this from a workstation with working gcloud credentials. It is idempotent:
# every step checks for what it is about to create, so re-running after a partial
# failure resumes rather than duplicating.
#
# The instance is deliberately small. The workload is 672,000 HTTPS requests to
# OpenRouter; inference happens on their hardware. The VM holds one condition's
# notes, an asyncio loop and a SQLite file, so paying for cores it will spend
# waiting on the network is pure waste.
#
# The OpenRouter key goes into Secret Manager and is read at runtime by the VM's
# service account. It is never baked into the image, the unit file, the instance
# metadata, or a startup script — all of which are readable by anyone with
# project-level view access.

set -euo pipefail

PROJECT="${MIPA_PROJECT:?set MIPA_PROJECT to your GCP project id}"
BUCKET="${MIPA_BUCKET:?set MIPA_BUCKET to your GCS bucket}"
INSTANCE="${MIPA_INSTANCE:-mipa-exp1}"
ZONE="${MIPA_ZONE:-us-central1-a}"
MACHINE="${MIPA_MACHINE:-e2-small}"
SECRET="openrouter-api-key"
SA_NAME="mipa-runner"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

say() { printf '\n=== %s ===\n' "$1"; }

say "preconditions"
gcloud config set project "$PROJECT" >/dev/null
gcloud storage ls "gs://${BUCKET}" >/dev/null || {
  echo "cannot read gs://${BUCKET}. Fix credentials first:" >&2
  echo "    gcloud auth login --force && gcloud auth application-default login" >&2
  exit 1
}
echo "project=${PROJECT} bucket=${BUCKET} ok"

say "code"
# The VM fetches the runner from the bucket, so it has to be there before the
# instance boots — otherwise bootstrap dies on a missing tarball.
bash "$(dirname "$0")/upload_code.sh"

say "apis"
gcloud services enable \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com

say "service account"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="MIPA Experiment 1 runner"

# A freshly created service account is not immediately visible to the IAM API —
# binding it right away fails with "does not exist". Wait for propagation rather
# than making the operator re-run and wonder which half applied.
for attempt in $(seq 1 12); do
  if gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then break; fi
  echo "  waiting for ${SA_NAME} to propagate (${attempt}/12)"; sleep 5
done

# Object-level roles rather than project-level: the runner reads corpora and
# writes checkpoints, and has no reason to create or delete buckets.
#
# Two roles, because one is not enough and the gap is not obvious:
#   objectAdmin          read/write the objects themselves
#   legacyBucketReader   `storage.buckets.get` — bucket *metadata*
#
# `gcloud storage ls` needs only the first, so a bootstrap can enumerate the
# corpora and report "found 28 notes.csv", then die on the very next line when
# `rsync` resolves the bucket. Observed exactly that on the first launch.
for attempt in $(seq 1 12); do
  if gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
       --member="serviceAccount:${SA}" --role=roles/storage.objectAdmin >/dev/null 2>&1 &&
     gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
       --member="serviceAccount:${SA}" --role=roles/storage.legacyBucketReader \
       >/dev/null 2>&1; then
    echo "  bucket bindings ok (objectAdmin + legacyBucketReader)"; break
  fi
  [[ ${attempt} -eq 12 ]] && { echo "could not bind ${SA} to gs://${BUCKET}" >&2; exit 1; }
  echo "  retrying bucket IAM binding (${attempt}/12)"; sleep 5
done

say "secret"
if ! gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  # `--data-file` always, never `--data-value`: a value on the command line is
  # visible in `ps` to every user on the box and lands in shell history.
  if [[ -n "${MIPA_KEY_FILE:-}" ]]; then
    [[ -r "${MIPA_KEY_FILE}" ]] || { echo "cannot read ${MIPA_KEY_FILE}" >&2; exit 1; }
    gcloud secrets create "$SECRET" --replication-policy=automatic \
      --data-file="${MIPA_KEY_FILE}"
    echo "created ${SECRET} from ${MIPA_KEY_FILE} (contents not echoed)"
  else
    echo "Creating ${SECRET}. Paste the OpenRouter key, then press Ctrl-D."
    echo "Or re-run with MIPA_KEY_FILE=/path/to/key.txt to avoid the prompt."
    gcloud secrets create "$SECRET" --replication-policy=automatic --data-file=-
  fi
fi
for attempt in $(seq 1 12); do
  if gcloud secrets add-iam-policy-binding "$SECRET" \
       --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor \
       >/dev/null 2>&1; then
    echo "  secret binding ok"; break
  fi
  [[ ${attempt} -eq 12 ]] && { echo "could not grant ${SA} access to ${SECRET}" >&2; exit 1; }
  echo "  retrying secret IAM binding (${attempt}/12)"; sleep 5
done

say "instance"
# `bootstrap.sh` is attached as the startup script, so the VM installs itself,
# pulls the corpora, preflights and starts the run with no SSH session. GCE
# re-runs a startup script on every boot, which is why bootstrap is written to be
# idempotent — a reboot reinstalls nothing and simply lets systemd resume.
if gcloud compute instances describe "$INSTANCE" --zone "$ZONE" >/dev/null 2>&1; then
  echo "instance ${INSTANCE} already exists; leaving it alone."
  echo "To re-bootstrap it in place:"
  echo "    gcloud compute ssh ${INSTANCE} --zone ${ZONE} --command \\"
  echo "      'sudo google_metadata_script_runner startup'"
else
  gcloud compute instances create "$INSTANCE" \
    --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-balanced \
    --service-account="$SA" \
    --scopes=https://www.googleapis.com/auth/cloud-platform \
    --labels=purpose=mipa-exp1 \
    --metadata="MIPA_PROJECT=${PROJECT},MIPA_BUCKET=${BUCKET}" \
    --metadata-from-file="startup-script=$(dirname "$0")/bootstrap.sh"
fi

cat <<EOF

=== the VM is bootstrapping itself ===

It installs, pulls the corpora from gs://${BUCKET}, runs preflight,
and starts the run — no SSH needed. Preflight failing stops it before anything is
spent, and the reason lands in the serial console.

Watch it come up (~5 min):

  gcloud compute instances get-serial-port-output ${INSTANCE} --zone ${ZONE} | tail -40

Then follow the run:

  gcloud compute ssh ${INSTANCE} --zone ${ZONE} --command 'journalctl -u mipa-exp1 -f'

Progress and spend at any time:

  gcloud compute ssh ${INSTANCE} --zone ${ZONE} --command \\
    '/opt/mipa-corrupt/.venv/bin/mipa-exp1 status \\
       --store /opt/mipa-corrupt/data/mipa_exp1/predictions.sqlite \\
       --sample /opt/mipa-corrupt/data/mipa_exp1/sample.csv'

Results appear at gs://${BUCKET}/results/<experiment>/<run-id>/ when it finishes
(exp1/run1 by default).

When it is done — the run does not stop the VM, so it will bill until you do:

  gcloud compute instances delete ${INSTANCE} --zone ${ZONE}
EOF
