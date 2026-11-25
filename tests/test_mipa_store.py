"""The store's only job is to make a nine-hour run interruptible.

So the tests are about identity and durability, not about SQL: does a key
identify exactly one prediction, does a resume skip what is already answered,
and can a second process read while the runner writes.
"""

from __future__ import annotations

import sqlite3

import pytest

from mipa.store import (
    SCHEMA_VERSION,
    Prediction,
    PredictionStore,
    prediction_key,
)


def make(
    *,
    document_id: str = "doc1",
    model: str = "google/gemma-3-4b-it",
    condition: str = "baseline",
    corruption: str = "none",
    severity: str = "none",
    phenotype: str = "hypertension",
    y_pred: int | None = 1,
    parse_status: str = "ok",
    raw_output: str | None = None,
    attempts: int = 1,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
) -> Prediction:
    return Prediction(
        document_id=document_id,
        model=model,
        condition=condition,
        corruption=corruption,
        severity=severity,
        phenotype=phenotype,
        y_pred=y_pred,
        parse_status=parse_status,
        raw_output=raw_output,
        attempts=attempts,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=cost,
    )


@pytest.fixture
def store(tmp_path):  # type: ignore[no-untyped-def]
    with PredictionStore(tmp_path / "predictions.sqlite") as s:
        yield s


# -- key identity ---------------------------------------------------------


def test_key_is_stable() -> None:
    a = prediction_key("doc1", "m", "baseline", "hypertension")
    b = prediction_key("doc1", "m", "baseline", "hypertension")
    assert a == b
    assert len(a) == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"document_id": "doc2"},
        {"model": "google/gemma-3-27b-it"},
        {"condition": "typo/0.10"},
        {"phenotype": "diabetes"},
    ],
)
def test_key_changes_with_every_field(changed: dict[str, str]) -> None:
    base = dict(document_id="doc1", model="m", condition="baseline", phenotype="hypertension")
    assert prediction_key(**base) != prediction_key(**{**base, **changed})


def test_key_resists_reassociation() -> None:
    """`a|bc` and `ab|c` must not collide.

    Model ids and condition names both contain hyphens and slashes, so plain
    concatenation would let a boundary shift produce the same key for two
    different predictions. The unit separator makes that impossible.
    """
    assert prediction_key("d", "gemma-3", "4b-it", "p") != prediction_key(
        "d", "gemma", "3-4b-it", "p"
    )


# -- resume ---------------------------------------------------------------


def test_completed_keys_round_trip(store: PredictionStore) -> None:
    store.put(make(phenotype="hypertension"))
    store.put(make(phenotype="diabetes"))
    keys = store.completed_keys()
    assert len(keys) == 2
    assert make(phenotype="hypertension").key in keys


def test_resume_skips_only_what_is_done(store: PredictionStore) -> None:
    """The resume contract: work already answered is skipped, the rest is not."""
    units = [make(phenotype=p) for p in ("hypertension", "diabetes", "aki")]
    store.put_many(units[:2])

    done = store.completed_keys()
    remaining = [u for u in units if u.key not in done]

    assert [u.phenotype for u in remaining] == ["aki"]


def test_put_many_is_idempotent(store: PredictionStore) -> None:
    inserted_first = store.put_many([make()])
    inserted_again = store.put_many([make()])
    assert inserted_first == 1
    assert inserted_again == 0
    assert store.count() == 1


def test_reinsert_does_not_overwrite_an_answer(store: PredictionStore) -> None:
    """A prediction is what the model said the first time it was asked.

    Never `REPLACE` on an answered row — otherwise the artifact would depend on
    how many times the run happened to be resumed, and a rerun after a code
    change could silently rewrite history.
    """
    store.put(make(y_pred=1, parse_status="ok"))
    store.put(make(y_pred=0, parse_status="no_json"))

    row = next(store.iter_rows())
    assert row["y_pred"] == 1
    assert row["parse_status"] == "ok"


# -- transport failures are not answers -----------------------------------
#
# The distinction this block defends is the one that made a scripted OpenRouter
# outage silently permanent: `http_error` rows were stored, counted as done, and
# never retried — so an infrastructure blip became measured "degradation",
# landing on whichever conditions happened to be running at the time. That is a
# confound with corruption severity itself.


@pytest.mark.parametrize("status", ["ok", "no_json", "no_status", "bad_value"])
def test_a_model_response_is_final(store: PredictionStore, status: str) -> None:
    """The model was asked and answered. Asking again would be resampling."""
    store.put(make(parse_status=status, y_pred=1 if status == "ok" else None))
    assert make().key in store.completed_keys()
    assert store.completed_count() == 1


@pytest.mark.parametrize("status", ["http_error", "timeout", "exhausted"])
def test_a_transport_failure_stays_retriable(store: PredictionStore, status: str) -> None:
    """Nothing was learned about the model, so the key must not count as done."""
    store.put(make(parse_status=status, y_pred=None))

    assert store.count() == 1, "the row is kept for the operational record"
    assert store.completed_keys() == set(), "but the key is not treated as answered"
    assert store.completed_count() == 0


def test_a_real_answer_replaces_a_transport_failure(store: PredictionStore) -> None:
    """The recovery path: after the outage, the retry's answer must win."""
    store.put(make(parse_status="http_error", y_pred=None, attempts=8))
    store.put(make(parse_status="ok", y_pred=1, attempts=1))

    row = next(store.iter_rows())
    assert row["parse_status"] == "ok"
    assert row["y_pred"] == 1
    assert store.count() == 1, "replaced, not duplicated"
    assert store.completed_count() == 1


def test_completed_count_is_scoped_to_the_run_that_asks(store: PredictionStore) -> None:
    """One store holds every experiment; a run must count only its own work.

    Unscoped, exp2 counted exp1's 448,000 rows and reported
    `451,293/64,000 answered; -387,293 remain`. The process exit code is derived
    from that number, so an unscoped count is a wrong completion signal, not
    just a cosmetic one.
    """
    store.put(make(document_id="d1", condition="exp1/typographical_errors/heavy"))
    store.put(make(document_id="d2", condition="exp2/typographical_errors/heavy"))
    store.put(make(document_id="d3", condition="exp2/homoglyph_substitutions/heavy"))

    assert store.completed_count() == 3, "unscoped still counts everything"
    assert store.completed_count({"exp2/typographical_errors/heavy"}) == 1
    assert (
        store.completed_count(
            {"exp2/typographical_errors/heavy", "exp2/homoglyph_substitutions/heavy"}
        )
        == 2
    )


def test_completed_count_scopes_by_model_too(store: PredictionStore) -> None:
    """`expected` multiplies by the model count, so the count must divide by it."""
    store.put(make(model="google/gemma-3-4b-it"))
    store.put(make(model="google/gemma-3-12b-it"))

    assert store.completed_count(models={"google/gemma-3-4b-it"}) == 1
    assert store.completed_count(models={"google/gemma-3-4b-it", "google/gemma-3-12b-it"}) == 2


def test_an_empty_filter_selects_nothing(store: PredictionStore) -> None:
    """A run with no conditions has answered nothing — not answered everything.

    The SQL degrades to a bare `WHERE parse_status IN (...)` if an empty tuple
    is spliced in, which would report a full store as this run's own progress.
    """
    store.put(make())
    assert store.completed_count(set()) == 0
    assert store.completed_count(models=set()) == 0


def test_attempts_accumulate_across_the_retry(store: PredictionStore) -> None:
    """How much a prediction really cost, not how much its last attempt did."""
    store.put(make(parse_status="timeout", y_pred=None, attempts=8))
    store.put(make(parse_status="ok", y_pred=1, attempts=2))
    assert next(store.operational_rows())["attempts"] == 10


def test_put_many_empty_is_a_noop(store: PredictionStore) -> None:
    assert store.put_many([]) == 0
    assert store.count() == 0


def test_store_survives_reopen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A reboot is just a reopen. The completed set has to come back intact."""
    path = tmp_path / "predictions.sqlite"
    with PredictionStore(path) as first:
        first.put_many([make(phenotype=p) for p in ("hypertension", "diabetes")])
        expected = first.completed_keys()

    with PredictionStore(path) as second:
        assert second.completed_keys() == expected
        assert second.get_meta("schema_version") == str(SCHEMA_VERSION)


# -- durability -----------------------------------------------------------


def test_wal_allows_concurrent_read(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`status` and the GCS checkpointer read while the runner writes.

    Without WAL the reader takes a shared lock the writer cannot pass, and a
    15-minute checkpoint would stall the run. This asserts a second connection
    can read a committed row while the store is still open for writing.
    """
    path = tmp_path / "predictions.sqlite"
    with PredictionStore(path) as writer:
        writer.put(make())

        reader = sqlite3.connect(path)
        try:
            mode = reader.execute("PRAGMA journal_mode").fetchone()[0]
            count = reader.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        finally:
            reader.close()

    assert mode.lower() == "wal"
    assert count == 1


def test_created_at_is_recorded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "predictions.sqlite"
    with PredictionStore(path) as store:
        store.put(make())
        stamp = store.conn.execute("SELECT created_at FROM predictions").fetchone()[0]
    assert stamp.endswith("+00:00")


# -- reporting ------------------------------------------------------------


def test_counts_by_condition(store: PredictionStore) -> None:
    store.put_many(
        [
            make(condition="baseline", phenotype="hypertension"),
            make(condition="baseline", phenotype="diabetes"),
            make(condition="typo/0.10", phenotype="hypertension"),
        ]
    )
    counts = store.counts_by_condition()
    assert counts[("google/gemma-3-4b-it", "baseline")] == 2
    assert counts[("google/gemma-3-4b-it", "typo/0.10")] == 1


def test_parse_status_counts_and_failures(store: PredictionStore) -> None:
    store.put_many(
        [
            make(phenotype="hypertension", parse_status="ok"),
            make(phenotype="diabetes", parse_status="no_json", y_pred=None, raw_output="sorry"),
            make(phenotype="aki", parse_status="timeout", y_pred=None),
        ]
    )
    assert store.parse_status_counts() == {"ok": 1, "no_json": 1, "timeout": 1}

    failures = list(store.iter_failures())
    assert {f["parse_status"] for f in failures} == {"no_json", "timeout"}
    assert any(f["raw_output"] == "sorry" for f in failures)


def test_results_rows_carry_no_raw_output_by_default(store: PredictionStore) -> None:
    """Model prose about a clinical note has no place in a results table."""
    store.put(make(raw_output='{"phenotype": "hypertension", "status": "1"}'))

    assert "raw_output" not in next(store.iter_rows())
    assert "raw_output" in next(store.iter_rows(with_raw=True))


def test_operational_columns_are_separate_from_results(store: PredictionStore) -> None:
    store.put(make(latency_ms=1234, prompt_tokens=3550, completion_tokens=12, cost=0.0002))

    result = next(store.iter_rows())
    assert "latency_ms" not in result and "cost" not in result

    ops = next(store.operational_rows())
    assert ops["latency_ms"] == 1234
    assert ops["prompt_tokens"] == 3550
    assert "y_pred" not in ops


def test_cost_so_far_tolerates_missing_costs(store: PredictionStore) -> None:
    """Not every provider returns `usage.cost`; a null must not poison the sum."""
    store.put_many(
        [
            make(phenotype="hypertension", cost=0.001),
            make(phenotype="diabetes", cost=None),
        ]
    )
    assert store.cost_so_far() == pytest.approx(0.001)


def test_cost_so_far_is_zero_on_an_empty_store(store: PredictionStore) -> None:
    assert store.cost_so_far() == 0.0


def test_meta_is_upsertable(store: PredictionStore) -> None:
    store.set_meta("run_id", "r1")
    store.set_meta("run_id", "r2")
    assert store.get_meta("run_id") == "r2"
    assert store.get_meta("absent") is None


def test_has_matches_completed_keys(store: PredictionStore) -> None:
    store.put(make())
    assert store.has(make().key)
    assert not store.has(make(phenotype="diabetes").key)
