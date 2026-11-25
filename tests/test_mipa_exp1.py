"""The runner, end to end, against a scripted OpenRouter.

The property this suite exists to protect is **resumability**. A two-day run
will be interrupted — that is a certainty, not a risk — and the failure mode
that matters is not a crash but a quiet one: a restart that recomputes work
already paid for, or worse, one that skips work it never did. Both produce a
results table that looks complete.

So the tests run the real `run` path with a mock transport, kill it partway,
restart it, and count HTTP requests. Counting requests rather than inspecting
state is deliberate: it is the only measurement that cannot be satisfied by
bookkeeping that merely *claims* the work was skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json

import httpx
import pytest

from mipa import corpora as mipa_corpora
from mipa import exp1 as mipa_exp1
from mipa.client import DEFAULT_MODELS, ClientConfig, OpenRouterClient
from mipa.protocol import PHENOTYPES
from mipa.store import PredictionStore

MODEL = DEFAULT_MODELS[0]
REAL_CLIENT = OpenRouterClient

#: The scripted model answers positive only when it sees this exact sentence.
#: The `e` -> `3` corruption destroys it, which is what gives the fixture a real
#: degradation to measure instead of a synthetic one.
TRIGGER = "Patient with hypertension."


# -- fixtures -------------------------------------------------------------


def write_corpus(path, rows, column="note_corrupted"):  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hadm_id", "note_id", column])
        writer.writeheader()
        for hadm_id, note_id, text in rows:
            writer.writerow({"hadm_id": hadm_id, "note_id": note_id, column: text})


@pytest.fixture
def workspace(tmp_path):  # type: ignore[no-untyped-def]
    """A miniature experiment: 2 notes, baseline + one corrupted condition."""
    notes = [("100", "n1", TRIGGER), ("200", "n2", "No relevant history.")]

    write_corpus(tmp_path / "experiments" / "baseline" / "notes.csv", notes, column="note_text")
    write_corpus(
        tmp_path / "experiments" / "exp1" / "typographical_errors" / "low" / "notes.csv",
        [(h, n, t.replace("e", "3")) for h, n, t in notes],
    )

    sample = tmp_path / "sample.csv"
    with sample.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["hadm_id", "note_id", "concepts", "density_band", *PHENOTYPES]
        )
        writer.writeheader()
        for hadm_id, note_id, _ in notes:
            row = dict.fromkeys(PHENOTYPES, 0)
            row["hypertension"] = 1 if hadm_id == "100" else 0
            writer.writerow(
                {"hadm_id": hadm_id, "note_id": note_id, "concepts": 10, "density_band": 0, **row}
            )

    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hadm_id", *PHENOTYPES])
        writer.writeheader()
        for hadm_id, _, _ in notes:
            row = dict.fromkeys(PHENOTYPES, 0)
            row["hypertension"] = 1 if hadm_id == "100" else 0
            writer.writerow({"hadm_id": hadm_id, **row})

    return tmp_path


def make_args(workspace, **overrides):  # type: ignore[no-untyped-def]
    base = {
        "experiments": workspace / "experiments",
        "sample": workspace / "sample.csv",
        "labels": workspace / "labels.csv",
        "store": workspace / "predictions.sqlite",
        "models": [MODEL],
        "bucket": None,
        "project": None,
        "api_key_file": None,
        "gcs_prefix": "",
        "max_notes": None,
        "experiment": "exp1",
        "concurrency": 4,
        "per_model_concurrency": 2,
        "max_per_model_concurrency": 4,
        "conditions": None,
        "run_id": "test",
        "results": workspace / "results",
        "live": False,
    }
    return argparse.Namespace(**{**base, **overrides})


class Server:
    """A scripted OpenRouter that counts what it was asked."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.requests: list[dict] = []
        self.fail_after = fail_after

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.requests.append(payload)
            if self.fail_after is not None and len(self.requests) > self.fail_after:
                raise httpx.ConnectError("scripted outage", request=request)
            # Trigger on the note sentence, not on the word "hypertension" —
            # the prompt itself interpolates the phenotype description, so a
            # bare word match fires on every request and the corrupted arm would
            # look identical to the baseline for reasons having nothing to do
            # with corruption.
            content = payload["messages"][-1]["content"]
            status = "1" if TRIGGER in content else "0"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"phenotype": "x", "status": status})}}
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0001},
                },
            )

        return httpx.MockTransport(handler)


def run_with(args, server, monkeypatch):  # type: ignore[no-untyped-def]
    """Run the real `run` coroutine against a scripted transport.

    `REAL_CLIENT` is bound at import, not read off the module: the resume tests
    call this twice in one test, and reading `mipa_exp1.OpenRouterClient` the
    second time would capture the *first* patch and silently replay the first
    server's scripted outage into the run meant to recover from it.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def patched(api_key, config=None, models=DEFAULT_MODELS, transport=None):  # type: ignore[no-untyped-def]
        return REAL_CLIENT(api_key, config=config, models=models, transport=server.transport())

    monkeypatch.setattr(mipa_exp1, "OpenRouterClient", patched)
    # Backoff off: the outage test would otherwise spend a real minute climbing
    # the retry ladder to assert something that has nothing to do with wall clock.
    monkeypatch.setattr(mipa_exp1, "ClientConfig", fast_config)
    return asyncio.run(mipa_exp1.run(args))


def fast_config(**kw):  # type: ignore[no-untyped-def]
    return ClientConfig(**{**kw, "base_backoff_s": 0.0, "max_backoff_s": 0.0, "max_retries": 2})


# -- condition discovery --------------------------------------------------


def test_discover_finds_baseline_first(workspace) -> None:  # type: ignore[no-untyped-def]
    """Every delta needs the reference arm, so a partial run must produce it first."""
    conditions = mipa_corpora.discover(workspace / "experiments")
    assert [c.name for c in conditions] == ["baseline", "typographical_errors/low"]
    assert conditions[0].is_baseline


def test_condition_carries_its_facets(workspace) -> None:  # type: ignore[no-untyped-def]
    corrupted = mipa_corpora.discover(workspace / "experiments")[1]
    assert corrupted.corruption == "typographical_errors"
    assert corrupted.severity == "low"


def test_both_text_column_names_are_read(workspace) -> None:  # type: ignore[no-untyped-def]
    """Baseline writes `note_text`, corrupted corpora write `note_corrupted`."""
    conditions = mipa_corpora.discover(workspace / "experiments")
    baseline = mipa_corpora.read_notes(conditions[0].notes_csv)
    corrupted = mipa_corpora.read_notes(conditions[1].notes_csv)
    assert baseline["100"] == "Patient with hypertension."
    assert corrupted["100"] == "Pati3nt with hyp3rt3nsion."


def test_ambiguous_text_column_is_an_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two text columns means guessing which text to send. Fail instead."""
    path = tmp_path / "notes.csv"
    path.write_text("hadm_id,note_id,note_text,note_corrupted\n1,n1,a,b\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly one"):
        mipa_corpora.read_notes(path)


def test_reading_notes_filters_to_the_sample(workspace) -> None:  # type: ignore[no-untyped-def]
    conditions = mipa_corpora.discover(workspace / "experiments")
    assert set(mipa_corpora.read_notes(conditions[0].notes_csv, keep={"100"})) == {"100"}


def test_a_corpus_missing_a_sampled_note_is_an_error(workspace) -> None:  # type: ignore[no-untyped-def]
    """The sample and the corpora must have been built from the same corpus."""
    conditions = mipa_corpora.discover(workspace / "experiments")
    with pytest.raises(SystemExit, match="missing 1 sampled note"):
        mipa_corpora.read_notes(conditions[0].notes_csv, keep={"100", "999"})


def test_unknown_condition_is_rejected(workspace) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace, conditions=["typo/nope"])
    with pytest.raises(SystemExit, match="unknown condition"):
        mipa_exp1.select_conditions(args)


def test_no_corpora_is_a_clear_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    args = make_args(tmp_path, experiments=tmp_path / "nothing")
    with pytest.raises(SystemExit, match="no corpora"):
        mipa_exp1.select_conditions(args)


# -- running --------------------------------------------------------------


def test_run_makes_every_prediction(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    server = Server()
    args = make_args(workspace)
    assert run_with(args, server, monkeypatch) == 0

    expected = 2 * 1 * len(PHENOTYPES) * 2  # notes x models x phenotypes x conditions
    assert len(server.requests) == expected

    with PredictionStore(args.store) as store:
        assert store.count() == expected
        assert store.parse_status_counts() == {"ok": expected}


def test_run_records_the_condition_facets(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)

    with PredictionStore(args.store) as store:
        rows = list(store.iter_rows())
    corrupted = [r for r in rows if r["condition"] == "typographical_errors/low"]
    assert {r["corruption"] for r in corrupted} == {"typographical_errors"}
    assert {r["severity"] for r in corrupted} == {"low"}
    assert {r["severity"] for r in rows if r["condition"] == "baseline"} == {"none"}


def test_corrupted_text_is_what_gets_sent(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The whole experiment rests on this: no cleaner between corpus and model.

    MIPA's `clean_text` would collapse whitespace and repair characters; if it
    were applied, several corruption arms would report zero degradation by
    construction rather than by measurement.
    """
    server = Server()
    run_with(args := make_args(workspace), server, monkeypatch)
    del args

    sent = [r["messages"][-1]["content"] for r in server.requests]
    assert any("Pati3nt with hyp3rt3nsion." in s for s in sent)
    assert any("Patient with hypertension." in s for s in sent)


def test_run_is_restricted_by_condition(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace, conditions=["baseline"])
    run_with(args, Server(), monkeypatch)
    with PredictionStore(args.store) as store:
        assert set(c for _, c in store.counts_by_condition()) == {"baseline"}


# -- resume, the property that matters ------------------------------------


def test_resume_does_not_repeat_completed_work(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Rerunning a finished run must issue zero requests.

    Counting HTTP requests, not store rows: a resume that recomputes and then
    discards would leave the store looking identical while costing the run a
    second time.
    """
    args = make_args(workspace)
    first = Server()
    run_with(args, first, monkeypatch)
    assert first.requests

    second = Server()
    assert run_with(args, second, monkeypatch) == 0
    assert second.requests == []


def test_resume_after_an_outage_completes_exactly_the_remainder(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The real failure: OpenRouter dies mid-run, the process restarts.

    Every prediction must end up made exactly once — none lost, none paid for
    twice.
    """
    args = make_args(workspace)
    total = 2 * len(PHENOTYPES) * 2

    broken = Server(fail_after=20)
    assert run_with(args, broken, monkeypatch) == 1, "incomplete run exits nonzero for systemd"

    with PredictionStore(args.store) as store:
        after_outage = store.completed_keys()
    assert 0 < len(after_outage) < total

    healthy = Server()
    assert run_with(args, healthy, monkeypatch) == 0

    with PredictionStore(args.store) as store:
        assert store.count() == total
        assert store.completed_keys() >= after_outage, "nothing already answered was lost"

    ok_requests = sum(1 for _ in healthy.requests)
    assert ok_requests == total - len(after_outage), "the resume redid no completed work"


def test_failed_predictions_are_recorded_not_dropped(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An exhausted retry budget is a result. Silently omitting it would make the
    denominator depend on how badly the provider was behaving."""
    args = make_args(workspace, conditions=["baseline"])

    server = Server()
    server.transport = lambda: httpx.MockTransport(  # type: ignore[method-assign]
        lambda _r: httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]})
    )
    run_with(args, server, monkeypatch)

    with PredictionStore(args.store) as store:
        assert store.count() == 2 * len(PHENOTYPES)
        assert set(store.parse_status_counts()) == {"no_json"}
        assert all(f["raw_output"] == "nope" for f in store.iter_failures())


def test_raw_output_is_kept_only_for_failures(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """672,000 stored model responses about clinical notes is a liability, not an asset."""
    args = make_args(workspace, conditions=["baseline"])
    run_with(args, Server(), monkeypatch)

    with PredictionStore(args.store) as store:
        assert all(r["raw_output"] is None for r in store.iter_rows(with_raw=True))


def test_run_records_the_protocol_departures(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)

    with PredictionStore(args.store) as store:
        recorded = json.loads(store.get_meta("departures") or "[]")
    assert {d["departure"] for d in recorded} == {
        "clean_text_not_applied",
        "system_prompt_sent",
    }


# -- analyze --------------------------------------------------------------


def test_analyze_writes_every_table(workspace, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)
    assert mipa_exp1.analyze_cmd(args) == 0

    # The two per-prediction tables are gzipped: both are 672,000 rows at full
    # scale, and 64 MB of latency integers is not a thing to hand anyone
    # uncompressed.
    for name in (
        "predictions.csv.gz",
        "overall_metrics.csv",
        "phenotype_metrics.csv",
        "robustness_deltas.csv",
        "parse_failures.csv",
        "operational.csv.gz",
        "run_summary.json",
    ):
        assert (args.results / name).exists(), name

    summary = json.loads((args.results / "run_summary.json").read_text())
    assert summary["conditions"] == ["baseline", "typographical_errors/low"]
    assert summary["predictions"] == 2 * len(PHENOTYPES) * 2
    assert len(summary["protocol_departures"]) == 2


def test_analyze_produces_a_delta_for_the_corrupted_arm(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The headline table, end to end.

    The scripted server answers 1 only when the note still contains the literal
    string "hypertension", which the typo corruption destroys — so the corrupted
    arm must show a real drop rather than an empty row.
    """
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)
    mipa_exp1.analyze_cmd(args)

    with (args.results / "robustness_deltas.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    macro = next(r for r in rows if r["metric"] == "macro_f1")
    assert macro["corruption"] == "typographical_errors"
    assert macro["severity"] == "low"
    assert float(macro["baseline"]) > 0
    assert float(macro["delta"]) < 0, "losing the trigger string must cost F1"
    assert int(macro["n_paired"]) == 2 * len(PHENOTYPES)


def test_status_reports_progress(workspace, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)
    assert mipa_exp1.status_cmd(args) == 0

    out = capsys.readouterr().out
    assert "baseline" in out
    assert "typographical_errors/low" in out
    assert "ok" in out


def test_status_without_a_store_says_so(workspace, capsys) -> None:  # type: ignore[no-untyped-def]
    assert mipa_exp1.status_cmd(make_args(workspace)) == 1
    assert "nothing has run yet" in capsys.readouterr().out


# -- preflight ------------------------------------------------------------


def test_preflight_passes_local_checks(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    checks, sample = mipa_exp1.check_local(make_args(workspace))
    by_prefix = {c.message.split(":")[0]: c for c in checks}

    assert len(sample) == 2
    assert by_prefix["sample"].ok
    assert by_prefix["join"].ok
    assert by_prefix["labels"].ok
    # 2 conditions, not 28 — the fixture is deliberately small, and preflight
    # must notice.
    assert not by_prefix["corpora"].ok


def test_preflight_reports_a_missing_key(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    checks = asyncio.run(mipa_exp1.check_api(make_args(workspace), []))
    assert len(checks) == 1
    assert not checks[0].ok
    assert "key:" in checks[0].message


def test_preflight_flags_an_unserved_model(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    served = httpx.MockTransport(lambda _r: httpx.Response(200, json={"data": [{"id": MODEL}]}))
    monkeypatch.setattr(
        mipa_exp1,
        "OpenRouterClient",
        lambda key, **kw: REAL_CLIENT(key, models=kw.get("models", ()), transport=served),
    )

    args = make_args(workspace, models=[MODEL, "google/gemma-4-31b-it"])
    checks = asyncio.run(mipa_exp1.check_api(args, []))
    by_model = {c.message: c.ok for c in checks if c.message.startswith("model:")}
    assert by_model[f"model: {MODEL}"]
    assert not by_model["model: google/gemma-4-31b-it"]


def test_preflight_detects_an_unlabelled_note(workspace) -> None:  # type: ignore[no-untyped-def]
    labels = workspace / "labels.csv"
    rows = list(csv.DictReader(labels.open(encoding="utf-8")))
    with labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hadm_id", *PHENOTYPES])
        writer.writeheader()
        writer.writerows(rows[:1])

    checks, _ = mipa_exp1.check_local(make_args(workspace))
    labels_check = next(c for c in checks if c.message.startswith("labels:"))
    assert not labels_check.ok
    assert "1 sampled notes without a gold label" in labels_check.message


# -- the CLI surface ------------------------------------------------------


def test_every_subcommand_parses() -> None:
    parser = mipa_exp1.build_parser()
    for command in ("preflight", "sample", "upload", "run", "status", "analyze"):
        assert parser.parse_args([command]).command == command


def test_a_subcommand_is_required() -> None:
    with pytest.raises(SystemExit):
        mipa_exp1.build_parser().parse_args([])


def test_defaults_point_at_the_real_layout() -> None:
    args = mipa_exp1.build_parser().parse_args(["run"])
    assert args.experiments.as_posix() == "data/experiments"
    assert args.models == list(DEFAULT_MODELS)
    assert len(args.models) == 3


# -- publishing to the bucket ---------------------------------------------


def test_publish_is_a_noop_without_a_bucket(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Local runs must not need cloud credentials to finish."""
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)
    assert mipa_exp1.analyze_cmd(args) == 0
    assert mipa_exp1.publish_results(args) == []


def test_publish_uploads_every_result_file(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """What makes the run autonomous: results reach the bucket with nobody logged in."""
    # The one test that reaches the `cloud` extra, which the dev install leaves out.
    pytest.importorskip("google.cloud.storage")
    args = make_args(workspace, bucket="test-bucket", project="test-project", run_id="r7")
    run_with(args, Server(), monkeypatch)

    uploaded: list[tuple[str, str]] = []
    from mipa import cloud as mipa_cloud

    def fake_upload(local, ref, project=None):  # type: ignore[no-untyped-def]
        uploaded.append((local.name, ref.prefix))
        return ref.uri

    monkeypatch.setattr(mipa_cloud, "upload", fake_upload)
    assert mipa_exp1.analyze_cmd(args) == 0

    names = {name for name, _ in uploaded}
    assert names == {p.name for p in args.results.iterdir()}
    assert "predictions.csv.gz" in names
    # `results/<experiment>/<run-id>/`. The experiment is in the path because it
    # is what distinguishes the corpora; an earlier build hardcoded
    # `results/experiment_1/` and an Experiment 2 run published under Experiment
    # 1's name.
    assert all(prefix.startswith("results/exp1/r7/") for _, prefix in uploaded)


def test_upload_requires_a_sample(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The VM reads the selection; it never re-derives it. So it must be pushed."""
    from mipa import cloud as mipa_cloud

    monkeypatch.setattr(mipa_cloud, "upload_corpora", lambda *a, **k: [])
    args = make_args(workspace, bucket="test-bucket", sample=workspace / "absent.csv")

    with pytest.raises(SystemExit, match="run `sample` before `upload`"):
        mipa_exp1.upload_cmd(args)


def test_upload_pushes_the_sample_and_labels(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from mipa import cloud as mipa_cloud

    pushed: list[str] = []
    monkeypatch.setattr(mipa_cloud, "upload_corpora", lambda *a, **k: [])
    monkeypatch.setattr(
        mipa_cloud, "upload", lambda local, ref, project=None: pushed.append(ref.prefix) or ref.uri
    )

    assert mipa_exp1.upload_cmd(make_args(workspace, bucket="test-bucket")) == 0
    # Bucket root, not an `experiments/` prefix: that is where the corpora
    # actually live (verified against the run bucket — `baseline/notes.csv`,
    # `exp1/<corruption>/<severity>/notes.csv`).
    assert pushed == ["sample.csv", "golden_labels.csv"]


def test_upload_without_a_bucket_is_a_clear_error(workspace) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit, match="needs --bucket"):
        mipa_exp1.upload_cmd(make_args(workspace))


# -- key hygiene ----------------------------------------------------------


def test_env_key_wins_over_everything(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """How the VM supplies it. Nothing may reach past a key already in hand."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    path = workspace / "key.txt"
    path.write_text("sk-from-file")
    args = make_args(workspace, api_key_file=path, project="some-project")

    assert mipa_exp1.resolve_key(args) == "sk-from-env"


def test_key_file_wins_over_secret_manager(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`--api-key-file` is an instruction.

    Reaching past it to Secret Manager would make a purely local run depend on
    cloud credentials it does not otherwise need — which is exactly the state
    this repository has been in.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = workspace / "key.txt"
    path.write_text("sk-from-file\n")

    from mipa import cloud as mipa_cloud

    def explode(**_kw: object) -> bool:
        raise AssertionError("Secret Manager must not be consulted")

    monkeypatch.setattr(mipa_cloud, "load_key_into_env", explode)

    args = make_args(workspace, api_key_file=path, project="some-project")
    assert mipa_exp1.resolve_key(args) == "sk-from-file"


def test_secret_manager_failure_is_one_redacted_line(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A gRPC traceback inside preflight would discard the checks that passed."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from mipa import cloud as mipa_cloud

    def boom(**_kw: object) -> bool:
        raise RuntimeError("Reauthentication is needed.\nBearer sk-or-v1-secret\nstack frame")

    monkeypatch.setattr(mipa_cloud, "load_key_into_env", boom)

    args = make_args(workspace, project="some-project")
    with pytest.raises(SystemExit) as excinfo:
        mipa_exp1.resolve_key(args)

    message = str(excinfo.value)
    assert "Reauthentication is needed." in message
    assert "stack frame" not in message
    assert "sk-or-v1-secret" not in message


def test_redact_strips_anything_key_shaped() -> None:
    """A gcloud or httpx error can quote the request, and the request has the key."""
    from mipa.cloud import redact

    assert "sk-or-v1-abc123def456" not in redact("Bearer sk-or-v1-abc123def456 failed")
    assert "sk-***" in redact("Bearer sk-or-v1-abc123def456 failed")


def test_no_note_text_reaches_the_result_tables(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """MIMIC-IV notes are restricted under the PhysioNet DUA.

    The scripted notes carry a distinctive string; none of the shipped tables may
    contain it.
    """
    args = make_args(workspace)
    run_with(args, Server(), monkeypatch)
    mipa_exp1.analyze_cmd(args)

    checked = 0
    for path in args.results.iterdir():
        # Decompress rather than skip: a gzipped table is exactly where a leak
        # would hide from a grep, and `predictions.csv.gz` is the widest table
        # shipped.
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            assert TRIGGER not in handle.read(), path
        checked += 1
    assert checked == 7, "every shipped file must be inspected, not just the plain ones"


# -- one slow model must not starve a fast one ----------------------------


def test_a_degraded_model_does_not_starve_a_healthy_one(workspace, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The head-of-line bug that dropped a live run from 4.4/s to 0.3/s.

    DeepInfra's 12b endpoint degraded to 13 s per request and the adaptive
    limiter floored it to one concurrent slot. With a single shared queue every
    worker eventually parked on a 12b unit, and 4b — still answering in 0.4 s —
    could not get a worker. Aggregate throughput collapsed by 14x while half the
    work was against a perfectly healthy provider.

    Asserts the property directly: with one model artificially slow, the fast
    model must still finish its share.
    """
    SLOW, FAST = DEFAULT_MODELS[1], DEFAULT_MODELS[0]
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        order.append(payload["model"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"phenotype":"x","status":"0"}'}}]},
        )

    server = Server()
    server.transport = lambda: httpx.MockTransport(handler)  # type: ignore[method-assign]

    args = make_args(workspace, models=[FAST, SLOW], conditions=["baseline"], concurrency=4)
    # Squeeze the slow model to a single slot, which is what the limiter does
    # under sustained 429s.
    monkeypatch.setattr(
        mipa_exp1,
        "ClientConfig",
        lambda **kw: ClientConfig(
            **{**kw, "base_backoff_s": 0.0, "max_backoff_s": 0.0, "per_model_concurrency": 1}
        ),
    )
    run_with(args, server, monkeypatch)

    with PredictionStore(args.store) as store:
        counts = {m: n for (m, _), n in store.counts_by_condition().items()}
    expected = 2 * len(PHENOTYPES)
    assert counts[FAST] == expected, "the healthy model must complete its share"
    assert counts[SLOW] == expected

    # Interleaving is the observable signature: with a shared queue the fast
    # model's requests bunch at the end, behind the slow one's.
    first_half = order[: len(order) // 2]
    assert FAST in first_half, "the fast model must make progress from the start"
