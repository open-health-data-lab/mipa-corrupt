#!/usr/bin/env bash
#
# Ship the runner to the bucket as a tarball.
#
# Not `git clone` on the VM, for a reason that matters here: the evaluation
# package is developed alongside uncommitted corpus work, and the remote does
# not carry it. A VM cloning `main` would come up with no runner at all — or,
# worse, an older one that looks like it works. The tarball is exactly the tree
# that was tested locally.
#
# Re-run this after any code change and reboot the instance (or re-run its
# startup script) to pick it up. `bootstrap.sh` re-extracts on every boot.
#
# **No data.** `data/` holds MIMIC-IV note text, restricted under the PhysioNet
# DUA; the corpora reach the VM through the bucket's own corpus tree, which is
# access-controlled. Nothing here should ever carry a note.

set -euo pipefail

BUCKET="${MIPA_BUCKET:?set MIPA_BUCKET to your GCS bucket}"
PROJECT="${MIPA_PROJECT:?set MIPA_PROJECT to your GCP project id}"
TARBALL="${MIPA_CODE_TARBALL:-code/mipa-corrupt.tar.gz}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

staged=$(mktemp -d)
trap 'rm -rf "${staged}"' EXIT

# An allowlist, not an exclude list: an exclude list silently ships whatever
# nobody thought to exclude, and in this repository that is patient data.
for item in src pyproject.toml deploy README.md; do
  [[ -e "${ROOT}/${item}" ]] || { echo "missing ${item}" >&2; exit 1; }
  cp -R "${ROOT}/${item}" "${staged}/"
done

find "${staged}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${staged}" -name '*.pyc' -delete 2>/dev/null || true

if find "${staged}" -name '*.csv' | grep -q .; then
  echo "FATAL: a .csv reached the staging tree — refusing to upload." >&2
  find "${staged}" -name '*.csv' >&2
  exit 1
fi

tar -czf "${staged}/mipa-corrupt.tar.gz" -C "${staged}" src pyproject.toml deploy README.md
size=$(du -h "${staged}/mipa-corrupt.tar.gz" | cut -f1)

gcloud storage cp "${staged}/mipa-corrupt.tar.gz" "gs://${BUCKET}/${TARBALL}" --project "${PROJECT}"
echo "uploaded ${size} -> gs://${BUCKET}/${TARBALL}"
echo
echo "To pick it up on a running instance:"
echo "  gcloud compute ssh mipa-exp1 --zone us-central1-a --command \\"
echo "    'sudo google_metadata_script_runner startup'"
