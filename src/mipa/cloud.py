"""GCS and Secret Manager, kept in one place and imported lazily.

Everything here is optional. The whole experiment runs locally with none of it,
and `pytest` must not require `google-cloud-*` to be installed — so the imports
live inside the functions and their absence is a clear message rather than a
collection error.

**The OpenRouter key never touches disk, git, a log line or a result file.**
Secret Manager hands it to the process; the process puts it in one Authorization
header. `redact` exists for the one place that is easy to get wrong — echoing a
command or an error that happens to contain it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: The secret's *name*, which `deploy/provision.sh` creates under the same
#: string. Only the name: the project it lives in and the bucket beside it are
#: site configuration, supplied by `--project` / `--bucket` or `MIPA_PROJECT` /
#: `MIPA_BUCKET`. Baking either one in here would compile one deployment's
#: infrastructure into every copy of a repository that ships with the paper.
SECRET_NAME = "openrouter-api-key"

#: Files a condition directory holds that inference does not need. `edits.jsonl`
#: is 46 MB per condition — 1.3 GB across the experiment — of character offsets
#: used to *build* the corpora and never to evaluate them.
INFERENCE_INPUTS = ("notes.csv", "manifest.json")

#: OpenRouter keys are `sk-or-v1-<hex>`. Matched loosely on purpose: a redactor
#: that only catches the exact current format is the one that fails the day the
#: format changes.
_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def redact(text: str) -> str:
    """Strip anything shaped like an API key before it reaches a log."""
    return _KEY_PATTERN.sub("sk-***", text)


def missing_dependency(package: str) -> SystemExit:
    return SystemExit(
        f"{package} is not installed. Cloud steps need it:\n"
        "    pip install -e '.[cloud]'\n"
        "Everything except `upload` and `--bucket` runs without it."
    )


# -- Secret Manager -------------------------------------------------------


def read_secret(
    project: str,
    name: str = SECRET_NAME,
    version: str = "latest",
) -> str:
    """Fetch the OpenRouter key from Secret Manager.

    Returned, never printed and never written. The caller puts it straight into
    the environment for `load_api_key` to pick up.

    `project` is required rather than defaulted. Every caller already knows it —
    the CLI resolves it from `--project` or `MIPA_PROJECT` — so a default would
    buy nothing and would name a real GCP project in the source.
    """
    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise missing_dependency("google-cloud-secret-manager") from exc

    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project}/secrets/{name}/versions/{version}"
    response = client.access_secret_version(request={"name": path})
    return str(response.payload.data.decode("utf-8")).strip()


def load_key_into_env(project: str, name: str = SECRET_NAME) -> bool:
    """Populate `OPENROUTER_API_KEY` from Secret Manager if it is not already set.

    An environment variable already present wins: it is how a local run and the
    smoke test work, and re-fetching would make the VM the only place the run
    behaves the same.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return False
    os.environ["OPENROUTER_API_KEY"] = read_secret(project=project, name=name)
    return True


# -- Cloud Storage --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BucketRef:
    bucket: str
    prefix: str = ""

    @property
    def uri(self) -> str:
        return f"gs://{self.bucket}/{self.prefix}".rstrip("/")

    def child(self, *parts: str) -> BucketRef:
        joined = "/".join([self.prefix, *parts]).strip("/")
        return BucketRef(self.bucket, joined)


def _client(project: str | None = None):  # type: ignore[no-untyped-def]
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise missing_dependency("google-cloud-storage") from exc
    return storage.Client(project=project)


def list_blobs(ref: BucketRef, project: str | None = None) -> list[str]:
    """Blob names under a prefix. `preflight` uses this to see what is really there."""
    client = _client(project)
    return [b.name for b in client.list_blobs(ref.bucket, prefix=ref.prefix)]


def upload(local: Path, ref: BucketRef, project: str | None = None) -> str:
    """Upload one file, returning its `gs://` URI."""
    client = _client(project)
    blob = client.bucket(ref.bucket).blob(ref.prefix)
    blob.upload_from_filename(str(local))
    return f"gs://{ref.bucket}/{ref.prefix}"


#: Directories under the experiments root that `upload` will push. Anything else
#: — a cancelled experiment, a scratch tree — stays local.
#:
#: An explicit allowlist rather than "everything present", because the failure is
#: silent and one-directional: uploading a stray tree costs bandwidth, makes the
#: VM download corpora it will never evaluate, and leaves objects in a shared
#: bucket that look like results. Deleting them afterwards is the awkward part.
UPLOADED_TREES = ("baseline", "exp1", "exp2")


def upload_corpora(
    root: Path,
    ref: BucketRef,
    *,
    names: Iterable[str] = INFERENCE_INPUTS,
    project: str | None = None,
    skip_existing: bool = True,
    trees: Iterable[str] = UPLOADED_TREES,
) -> list[str]:
    """Push the inference inputs, and only those.

    Deliberately not a directory sync, in two dimensions. `edits.jsonl` and
    `dose.jsonl` are the corruption engine's provenance — 1.3 GB of offsets that
    reproduce the corpora but contribute nothing to running a model over them.
    And only `baseline/` and `exp1/` are walked: `data/experiments/` also holds a
    partial `exp2/` from a cancelled run, which the runner never reads and the VM
    should never download.
    """
    client = _client(project)
    bucket = client.bucket(ref.bucket)
    wanted = set(names)
    allowed = set(trees)
    uploaded = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name not in wanted:
            continue
        parts = path.relative_to(root).parts
        if parts[0] not in allowed:
            continue
        target = ref.child(*parts)
        blob = bucket.blob(target.prefix)
        if skip_existing and blob.exists():
            continue
        blob.upload_from_filename(str(path))
        uploaded.append(target.uri)
    return uploaded


def download(ref: BucketRef, local: Path, project: str | None = None) -> Path:
    client = _client(project)
    local.parent.mkdir(parents=True, exist_ok=True)
    client.bucket(ref.bucket).blob(ref.prefix).download_to_filename(str(local))
    return local


__all__ = [
    "INFERENCE_INPUTS",
    "SECRET_NAME",
    "UPLOADED_TREES",
    "BucketRef",
    "download",
    "list_blobs",
    "load_key_into_env",
    "read_secret",
    "redact",
    "upload",
    "upload_corpora",
]
