"""Metrics are the part of this pipeline that can be quietly, plausibly wrong.

A retry bug announces itself; a macro average that silently excludes the wrong
phenotype, or a delta computed against mismatched denominators, produces a
number that looks entirely reasonable and is not. So the arithmetic is pinned
against `sklearn.metrics` on randomised matrices rather than on hand-picked
examples, and the two design decisions that change what the numbers *mean* —
pairwise parse-failure exclusion, and pairing the delta on the intersection —
each get a test that fails if the decision is reverted.

`sklearn` is a test-only dependency. Pinning against it here is what lets the
runtime module do the arithmetic itself, which is what keeps 100 MB of NumPy off
a 2 GB VM.
"""

from __future__ import annotations

import csv
import random

import pytest

from mipa.metrics import (
    DELTA_METRICS,
    Arm,
    Counts,
    Pair,
    build_arms,
    confusion,
    delta_rows,
    overall_rows,
    phenotype_rows,
    prediction_rows,
    score,
    summarise,
    write_csv,
    write_csv_gz,
)
from mipa.protocol import PHENOTYPES

sklearn_metrics = pytest.importorskip(
    "sklearn.metrics", reason="scikit-learn is the reference implementation for these formulas"
)


def pairs_from(matrix: dict[str, list[tuple[int, int]]]) -> list[Pair]:
    """`{phenotype: [(y_true, y_pred), ...]}` -> pairs with distinct document ids."""
    out = []
    for phenotype, outcomes in matrix.items():
        for i, (y_true, y_pred) in enumerate(outcomes):
            out.append(Pair(f"doc{i}", phenotype, y_true, y_pred))
    return out


def random_matrix(seed: int, n_phenotypes: int = 6, n_docs: int = 40) -> list[Pair]:
    """Skewed toward negatives, the way real phenotype prevalence is."""
    rng = random.Random(seed)
    out = []
    for phenotype in PHENOTYPES[:n_phenotypes]:
        prevalence = rng.choice([0.03, 0.15, 0.5, 0.7])
        for i in range(n_docs):
            y_true = int(rng.random() < prevalence)
            y_pred = y_true if rng.random() < 0.8 else 1 - y_true
            out.append(Pair(f"doc{i}", phenotype, y_true, y_pred))
    return out


# -- the confusion matrix -------------------------------------------------


def test_cells_are_assigned_correctly() -> None:
    counts = confusion(
        pairs_from({"hypertension": [(1, 1), (1, 1), (0, 1), (0, 0), (0, 0), (0, 0), (1, 0)]})
    )["hypertension"]
    assert (counts.tp, counts.fp, counts.tn, counts.fn) == (2, 1, 3, 1)
    assert counts.n == 7
    assert counts.n_pos == 3


def test_counts_add() -> None:
    total = Counts(1, 2, 3, 4) + Counts(10, 20, 30, 40)
    assert (total.tp, total.fp, total.tn, total.fn) == (11, 22, 33, 44)


@pytest.mark.parametrize("seed", range(12))
def test_per_phenotype_matches_sklearn(seed: int) -> None:
    pairs = random_matrix(seed)
    per = confusion(pairs)
    for phenotype, counts in per.items():
        subset = [p for p in pairs if p.phenotype == phenotype]
        y_true = [p.y_true for p in subset]
        y_pred = [p.y_pred for p in subset]
        assert counts.f1 == pytest.approx(sklearn_metrics.f1_score(y_true, y_pred, zero_division=0))
        assert counts.precision == pytest.approx(
            sklearn_metrics.precision_score(y_true, y_pred, zero_division=0)
        )
        assert counts.recall == pytest.approx(
            sklearn_metrics.recall_score(y_true, y_pred, zero_division=0)
        )
        assert counts.accuracy == pytest.approx(sklearn_metrics.accuracy_score(y_true, y_pred))


@pytest.mark.parametrize(
    ("tp", "fp", "tn", "fn"),
    [(0, 0, 5, 0), (0, 0, 0, 0), (0, 3, 5, 0), (0, 0, 5, 3)],
)
def test_undefined_ratios_are_zero_like_sklearn(tp: int, fp: int, tn: int, fn: int) -> None:
    """A phenotype with no positives anywhere is the case `n_pos` exists to expose."""
    counts = Counts(tp, fp, tn, fn)
    y_true = [1] * tp + [0] * fp + [0] * tn + [1] * fn
    y_pred = [1] * tp + [1] * fp + [0] * tn + [0] * fn
    if y_true:
        assert counts.f1 == pytest.approx(sklearn_metrics.f1_score(y_true, y_pred, zero_division=0))
    else:
        assert counts.f1 == 0.0


# -- macro and micro ------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_macro_and_micro_match_sklearn(seed: int) -> None:
    """Macro over phenotypes, micro pooled — the two must not be swapped.

    They are close on balanced data and far apart here, so an accidental swap
    would survive a hand-picked example and change every headline number.
    """
    pairs = random_matrix(seed)
    scores = score(pairs)

    present = [p for p in PHENOTYPES if any(x.phenotype == p for x in pairs)]
    per_f1 = []
    for phenotype in present:
        subset = [p for p in pairs if p.phenotype == phenotype]
        per_f1.append(
            sklearn_metrics.f1_score(
                [p.y_true for p in subset], [p.y_pred for p in subset], zero_division=0
            )
        )
    assert scores.macro_f1 == pytest.approx(sum(per_f1) / len(per_f1))

    y_true = [p.y_true for p in pairs]
    y_pred = [p.y_pred for p in pairs]
    assert scores.micro_f1 == pytest.approx(
        sklearn_metrics.f1_score(y_true, y_pred, average="binary", zero_division=0)
    )
    assert scores.accuracy == pytest.approx(sklearn_metrics.accuracy_score(y_true, y_pred))
    assert scores.micro_recall == pytest.approx(
        sklearn_metrics.recall_score(y_true, y_pred, zero_division=0)
    )


def test_macro_weights_phenotypes_equally() -> None:
    """The reason macro is the headline: prevalence spans 2.8% to 67.7%."""
    common = [(1, 1)] * 90 + [(0, 0)] * 10  # perfect on the abundant phenotype
    rare = [(1, 0)] * 3 + [(0, 0)] * 97  # missed entirely on the rare one
    scores = score(pairs_from({"hypertension": common, "vte_complication": rare}))

    assert scores.macro_f1 == pytest.approx(0.5), "one perfect, one zero"
    assert scores.micro_f1 > 0.95, "pooling lets the abundant phenotype speak for the corpus"


def test_absent_phenotypes_are_excluded_not_zeroed() -> None:
    """Averaging in a 0.0 for a phenotype nobody scored would understate every arm.

    It would understate the corrupted arms most, since that is where pairs go
    missing to parse failures — turning a reporting artifact into apparent
    degradation.
    """
    scores = score(pairs_from({"hypertension": [(1, 1)] * 10}))
    assert scores.macro_f1 == pytest.approx(1.0)
    assert len(scores.absent_phenotypes) == len(PHENOTYPES) - 1
    assert "hypertension" not in scores.absent_phenotypes


def test_empty_input_does_not_divide_by_zero() -> None:
    scores = score([])
    assert scores.n == 0
    assert scores.macro_f1 == 0.0
    assert len(scores.absent_phenotypes) == len(PHENOTYPES)


# -- assembling arms from stored rows -------------------------------------


LABELS = {
    "doc1": frozenset({"hypertension"}),
    "doc2": frozenset(),
}


def row(**kw: object) -> dict[str, object]:
    base = {
        "document_id": "doc1",
        "model": "m",
        "condition": "baseline",
        "corruption": "none",
        "severity": "none",
        "phenotype": "hypertension",
        "y_pred": 1,
        "parse_status": "ok",
    }
    return {**base, **kw}


def test_gold_labels_join_by_document() -> None:
    arms = build_arms([row(document_id="doc1"), row(document_id="doc2")], LABELS)
    pairs = arms[("m", "baseline")].pairs
    assert {p.document_id: p.y_true for p in pairs} == {"doc1": 1, "doc2": 0}


def test_missing_gold_label_raises() -> None:
    """A join failure is not a negative. Scoring it as 0 would invent ground truth."""
    with pytest.raises(KeyError, match="no gold label"):
        build_arms([row(document_id="ghost")], LABELS)


def test_parse_failures_are_excluded_pairwise(caplog: pytest.LogCaptureFixture) -> None:
    """Not by note, which is where MIPA's `filter_incomplete_parsing` goes wrong.

    Dropping the whole note would remove `doc1`'s good `hypertension` answer too,
    evaluating the arm on whatever survived corruption best.
    """
    rows = [
        row(document_id="doc1", phenotype="hypertension", y_pred=1),
        row(document_id="doc1", phenotype="diabetes", y_pred=None, parse_status="no_json"),
    ]
    arm = build_arms(rows, LABELS)[("m", "baseline")]

    assert arm.attempted == 2
    assert len(arm.pairs) == 1
    assert arm.pairs[0].phenotype == "hypertension"
    assert arm.parse_failure_rate == pytest.approx(0.5)


def test_arms_are_split_by_model_and_condition() -> None:
    rows = [
        row(model="a", condition="baseline"),
        row(model="a", condition="typo/low"),
        row(model="b", condition="baseline"),
    ]
    assert set(build_arms(rows, LABELS)) == {
        ("a", "baseline"),
        ("a", "typo/low"),
        ("b", "baseline"),
    }


# -- the delta table ------------------------------------------------------


def make_arm(model: str, condition: str, pairs: list[Pair], attempted: int | None = None) -> Arm:
    return Arm(
        model=model,
        condition=condition,
        corruption="typographical_errors" if condition != "baseline" else "none",
        severity="low" if condition != "baseline" else "none",
        attempted=attempted if attempted is not None else len(pairs),
        pairs=tuple(pairs),
    )


def test_delta_is_corrupted_minus_baseline() -> None:
    """Negative means degradation — the direction a column headed "delta" implies."""
    perfect = pairs_from({"hypertension": [(1, 1)] * 5 + [(0, 0)] * 5})
    poor = pairs_from({"hypertension": [(1, 0)] * 5 + [(0, 0)] * 5})
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", perfect),
        ("m", "typo/low"): make_arm("m", "typo/low", poor),
    }
    rows = {r["metric"]: r for r in delta_rows(arms)}
    assert rows["macro_f1"]["baseline"] == pytest.approx(1.0)
    assert rows["macro_f1"]["corrupted"] == pytest.approx(0.0)
    assert rows["macro_f1"]["delta"] == pytest.approx(-1.0)
    assert rows["macro_f1"]["delta_pct"] == pytest.approx(-100.0)


def test_baseline_is_not_compared_to_itself() -> None:
    arms = {("m", "baseline"): make_arm("m", "baseline", pairs_from({"hypertension": [(1, 1)]}))}
    assert delta_rows(arms) == []


def test_every_delta_metric_is_reported() -> None:
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", random_matrix(1)),
        ("m", "typo/low"): make_arm("m", "typo/low", random_matrix(2)),
    }
    assert {r["metric"] for r in delta_rows(arms)} == set(DELTA_METRICS)


def test_delta_uses_each_model_s_own_baseline() -> None:
    """A 4b model starting lower than a 27b one says nothing about robustness."""
    good = pairs_from({"hypertension": [(1, 1)] * 10})
    bad = pairs_from({"hypertension": [(1, 0)] * 10})
    arms = {
        ("small", "baseline"): make_arm("small", "baseline", bad),
        ("small", "typo/low"): make_arm("small", "typo/low", bad),
        ("large", "baseline"): make_arm("large", "baseline", good),
        ("large", "typo/low"): make_arm("large", "typo/low", bad),
    }
    by_model = {r["model"]: r for r in delta_rows(arms) if r["metric"] == "macro_f1"}
    assert by_model["small"]["delta"] == pytest.approx(0.0), (
        "already bad, corruption changed nothing"
    )
    assert by_model["large"]["delta"] == pytest.approx(-1.0)


def test_missing_baseline_raises() -> None:
    arms = {("m", "typo/low"): make_arm("m", "typo/low", random_matrix(1))}
    with pytest.raises(KeyError, match="no 'baseline' arm"):
        delta_rows(arms)


def test_delta_is_paired_on_the_intersection() -> None:
    """The confound this pairing exists to remove.

    The corrupted arm loses its two *hard* pairs to parse failures. Scored on its
    own surviving pairs it looks perfect and the delta reads as no degradation.
    Scored on what both arms answered, the delta reflects the pairs actually
    compared — and `n_dropped` shows what went missing.
    """
    baseline_pairs = [
        Pair("doc1", "hypertension", 1, 1),
        Pair("doc2", "hypertension", 1, 1),
        Pair("hard1", "hypertension", 1, 1),
        Pair("hard2", "hypertension", 1, 1),
    ]
    corrupted_pairs = [
        Pair("doc1", "hypertension", 1, 1),
        Pair("doc2", "hypertension", 1, 1),
    ]
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", baseline_pairs),
        ("m", "typo/low"): make_arm("m", "typo/low", corrupted_pairs, attempted=4),
    }
    row_ = next(r for r in delta_rows(arms) if r["metric"] == "macro_f1")

    assert row_["n_paired"] == 2
    assert row_["n_dropped"] == 2
    assert row_["parse_failure_rate"] == pytest.approx(0.5)
    assert row_["baseline"] == pytest.approx(row_["corrupted"]), (
        "both arms scored on the same two pairs"
    )


def test_pairing_changes_the_answer_when_failures_are_biased() -> None:
    """If the dropped pairs were the ones the baseline got wrong, pairing matters.

    Unpaired, the corrupted arm would be compared against a baseline dragged down
    by pairs the corrupted arm never had to answer — inventing an improvement.
    """
    baseline_pairs = [
        Pair("easy", "hypertension", 1, 1),
        Pair("hard", "hypertension", 1, 0),
    ]
    corrupted_pairs = [Pair("easy", "hypertension", 1, 1)]
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", baseline_pairs),
        ("m", "typo/low"): make_arm("m", "typo/low", corrupted_pairs, attempted=2),
    }
    row_ = next(r for r in delta_rows(arms) if r["metric"] == "macro_f1")

    unpaired_delta = score(corrupted_pairs).macro_f1 - score(baseline_pairs).macro_f1
    assert unpaired_delta > 0, "the naive comparison would report an improvement"
    assert row_["delta"] == pytest.approx(0.0), "paired, there is no change to report"


def test_delta_pct_is_null_rather_than_infinite() -> None:
    zero = pairs_from({"hypertension": [(1, 0)] * 5})
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", zero),
        ("m", "typo/low"): make_arm("m", "typo/low", zero),
    }
    row_ = next(r for r in delta_rows(arms) if r["metric"] == "macro_f1")
    assert row_["baseline"] == 0.0
    assert row_["delta_pct"] is None


# -- output tables --------------------------------------------------------


def test_overall_rows_carry_the_parse_failure_rate() -> None:
    arms = build_arms(
        [
            row(phenotype="hypertension"),
            row(phenotype="diabetes", y_pred=None, parse_status="timeout"),
        ],
        LABELS,
    )
    [record] = overall_rows(arms)
    assert record["n_attempted"] == 2
    assert record["n_evaluated"] == 1
    assert record["parse_failure_rate"] == pytest.approx(0.5)


def test_phenotype_rows_cover_all_sixteen() -> None:
    """Including the ones with no pairs — a missing row reads as an oversight."""
    arms = build_arms([row()], LABELS)
    records = phenotype_rows(arms)
    assert len(records) == len(PHENOTYPES)
    assert {r["phenotype"] for r in records} == set(PHENOTYPES)
    empty = next(r for r in records if r["phenotype"] == "dementia")
    assert empty["n"] == 0 and empty["n_pos"] == 0


def test_phenotype_rows_carry_n_pos() -> None:
    arms = build_arms(
        [row(document_id="doc1"), row(document_id="doc2")],
        LABELS,
    )
    record = next(r for r in phenotype_rows(arms) if r["phenotype"] == "hypertension")
    assert record["n"] == 2
    assert record["n_pos"] == 1
    assert record["tp"] == 1 and record["fp"] == 1


def test_write_csv_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    arms = build_arms([row()], LABELS)
    path = write_csv(tmp_path / "overall_metrics.csv", overall_rows(arms))
    with path.open(encoding="utf-8") as handle:
        [record] = list(csv.DictReader(handle))
    assert record["model"] == "m"
    assert float(record["macro_f1"]) == pytest.approx(1.0)


def test_write_csv_of_nothing_is_an_empty_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write_csv(tmp_path / "empty.csv", [])
    assert path.read_text() == ""


# -- the unaggregated matrix ----------------------------------------------


def test_prediction_rows_join_the_gold_label() -> None:
    records = list(prediction_rows([row(document_id="doc1"), row(document_id="doc2")], LABELS))
    assert [r["y_true"] for r in records] == [1, 0]
    assert [r["y_pred"] for r in records] == [1, 1]


def test_prediction_rows_keep_failures_with_an_empty_prediction() -> None:
    """A dropped failure hides that the denominator moved.

    An analyst who wants them gone can filter on `parse_status`; one who cannot
    see them has no way to know they existed.
    """
    records = list(prediction_rows([row(y_pred=None, parse_status="no_json")], LABELS))
    assert records[0]["y_pred"] is None
    assert records[0]["parse_status"] == "no_json"
    assert records[0]["y_true"] == 1


def test_prediction_rows_have_the_documented_columns() -> None:
    """The contract the downstream pipeline is written against."""
    [record] = list(prediction_rows([row()], LABELS))
    assert list(record) == [
        "document_id",
        "model",
        "condition",
        "corruption",
        "severity",
        "phenotype",
        "y_true",
        "y_pred",
        "parse_status",
    ]


def test_prediction_rows_reject_an_unlabelled_document() -> None:
    with pytest.raises(KeyError, match="no gold label"):
        list(prediction_rows([row(document_id="ghost")], LABELS))


def test_write_csv_gz_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import gzip

    path = write_csv_gz(tmp_path / "predictions.csv.gz", prediction_rows([row()], LABELS))
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        [record] = list(csv.DictReader(handle))
    assert record["document_id"] == "doc1"
    assert record["y_true"] == "1"


def test_write_csv_gz_streams_rather_than_materialising(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """672,000 rows must not be held in memory to be written.

    Asserted by handing it a generator that would raise if the writer tried to
    consume it twice or take its length.
    """
    consumed = 0

    def once():  # type: ignore[no-untyped-def]
        nonlocal consumed
        for record in prediction_rows([row()], LABELS):
            consumed += 1
            yield record

    write_csv_gz(tmp_path / "streamed.csv.gz", once())
    assert consumed == 1


def test_write_csv_gz_of_nothing_is_a_valid_empty_archive(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import gzip

    path = write_csv_gz(tmp_path / "empty.csv.gz", [])
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert handle.read() == ""


def test_result_tables_have_a_fixed_column_set() -> None:
    """MIMIC-IV note text is restricted under the PhysioNet DUA and must not travel.

    A whitelist rather than a heuristic: these tables carry identifiers and
    arithmetic and nothing else, so the way a note fragment gets into a shipped
    CSV is a *new column* someone added without thinking about it. Freezing the
    column set makes that a test failure instead of a data release.
    """
    arms = build_arms([row()], LABELS)

    assert set(overall_rows(arms)[0]) == {
        "model",
        "condition",
        "corruption",
        "severity",
        "n_attempted",
        "n_evaluated",
        "parse_failure_rate",
        "macro_f1",
        "micro_f1",
        "accuracy",
        "macro_recall",
        "micro_recall",
        "macro_precision",
        "micro_precision",
        "absent_phenotypes",
    }
    assert set(phenotype_rows(arms)[0]) == {
        "model",
        "condition",
        "corruption",
        "severity",
        "phenotype",
        "n",
        "n_pos",
        "tp",
        "fp",
        "tn",
        "fn",
        "f1",
        "precision",
        "recall",
        "accuracy",
    }
    assert set(delta_rows({**arms, ("m", "typo/low"): make_arm("m", "typo/low", [])})[0]) == {
        "model",
        "corruption",
        "severity",
        "condition",
        "metric",
        "baseline",
        "corrupted",
        "delta",
        "delta_pct",
        "n_paired",
        "n_dropped",
        "parse_failure_rate",
    }


def test_free_text_columns_only_ever_hold_known_vocabulary() -> None:
    """Every string a result table carries must come from a closed set.

    `absent_phenotypes` is the only column that concatenates values, and the
    values are phenotype keys — never anything read from a note.
    """
    arms = build_arms([row()], LABELS)
    absent = overall_rows(arms)[0]["absent_phenotypes"]
    assert set(absent.split(";")) <= set(PHENOTYPES)


def test_summarise_renders_the_delta_table() -> None:
    arms = {
        ("m", "baseline"): make_arm("m", "baseline", pairs_from({"hypertension": [(1, 1)] * 4})),
        ("m", "typo/low"): make_arm("m", "typo/low", pairs_from({"hypertension": [(1, 0)] * 4})),
    }
    text = summarise(delta_rows(arms))
    assert "macro_f1" in text
    assert "typographical_errors" in text
    assert "-1.000" in text


def test_summarise_reports_an_unknown_metric_plainly() -> None:
    assert "no rows" in summarise([], metric="macro_f1")


# -- the schema contract handed to downstream analysis --------------------
#
# `sample_output/` exists so a statistical pipeline can be written before the
# real run finishes. That is only safe if the mock's columns are exactly the
# real run's columns — the numbers are admittedly fabricated, so the schema is
# the entire value of the artifact. These freeze it.


PREDICTION_COLUMNS = [
    "document_id",
    "model",
    "condition",
    "corruption",
    "severity",
    "phenotype",
    "y_true",
    "y_pred",
    "parse_status",
]
OVERALL_COLUMNS = [
    "model",
    "condition",
    "corruption",
    "severity",
    "n_attempted",
    "n_evaluated",
    "parse_failure_rate",
    "macro_f1",
    "micro_f1",
    "accuracy",
    "macro_recall",
    "micro_recall",
    "macro_precision",
    "micro_precision",
    "absent_phenotypes",
]
PHENOTYPE_COLUMNS = [
    "model",
    "condition",
    "corruption",
    "severity",
    "phenotype",
    "n",
    "n_pos",
    "tp",
    "fp",
    "tn",
    "fn",
    "f1",
    "precision",
    "recall",
    "accuracy",
]
DELTA_COLUMNS = [
    "model",
    "corruption",
    "severity",
    "condition",
    "metric",
    "baseline",
    "corrupted",
    "delta",
    "delta_pct",
    "n_paired",
    "n_dropped",
    "parse_failure_rate",
]


def test_prediction_column_order_is_frozen() -> None:
    """Order, not just membership: a positional reader must not silently shift."""
    [record] = list(prediction_rows([row()], LABELS))
    assert list(record) == PREDICTION_COLUMNS


def test_aggregate_column_order_is_frozen() -> None:
    arms = build_arms([row()], LABELS)
    assert list(overall_rows(arms)[0]) == OVERALL_COLUMNS
    assert list(phenotype_rows(arms)[0]) == PHENOTYPE_COLUMNS

    with_corrupted = {**arms, ("m", "typo/low"): Arm("m", "typo/low", "typo", "low", 0, ())}
    assert list(delta_rows(with_corrupted)[0]) == DELTA_COLUMNS


def test_the_published_sample_output_matches_the_contract() -> None:
    """The artifact actually handed to the student, checked against the code.

    Skipped when `sample_output/` is absent — it is a generated directory, not a
    source file — but when it is there it must agree, because a mock that has
    drifted from production is worse than no mock at all.
    """
    import csv as _csv
    import gzip as _gzip
    from pathlib import Path

    out = Path(__file__).resolve().parents[1] / "sample_output"
    if not out.exists():
        pytest.skip("sample_output/ not generated")

    def header(stem: str) -> list[str]:
        # Either compression form: the generator writes `.csv.gz`, but a reader
        # who gunzipped the file locally to poke at it has not broken anything
        # the contract is about. Columns are the contract; bytes are not.
        path = next(p for p in (out / f"{stem}.csv.gz", out / f"{stem}.csv") if p.exists())
        opener = _gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            return next(_csv.reader(handle))

    assert header("predictions") == PREDICTION_COLUMNS
    assert header("overall_metrics") == OVERALL_COLUMNS
    assert header("phenotype_metrics") == PHENOTYPE_COLUMNS
    assert header("robustness_deltas") == DELTA_COLUMNS
