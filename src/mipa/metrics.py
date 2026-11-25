"""Turning 672,000 predictions into the four numbers the experiment is about.

MIPA reports per-phenotype F1 and nothing above it — `grep "average='macro'"`
across the repository returns nothing — so the aggregate layer is new. It is
deliberately built from confusion counts rather than from `sklearn`: the
per-phenotype table has to carry tp/fp/tn/fn anyway, every aggregate here is a
ratio of those four integers, and a 2 GB VM should not be carrying 100 MB of
NumPy to divide. `tests/test_mipa_metrics.py` pins every formula against
`sklearn.metrics` on randomised matrices, so the convention is inherited without
the dependency.

Two decisions that change what the numbers mean:

**Parse failures are excluded pairwise, never by note.** MIPA's
`filter_incomplete_parsing` keeps only notes where *every* chunk parsed. Under
corruption that is a trap: corruption causes parse failures, so the filter
quietly evaluates each corrupted arm on the subset of notes that survived
corruption best, and the measured degradation is biased toward zero by the very
thing being measured. Here a failed (note, phenotype) pair drops out on its own
and `parse_failure_rate` is reported beside every metric.

**The delta table is paired on the intersection.** Excluding pairwise is right
for a marginal number but wrong for a difference: if a corrupted arm fails to
parse 3% of pairs, comparing its 97% against the baseline's 100% compares two
different denominators. So `robustness_deltas.csv` scores both arms on exactly
the pairs both answered, and carries `n_paired` and `n_dropped` so the reader can
see the price. `overall_metrics.csv` keeps the honest marginal number. The two
answer different questions and are reported separately rather than blended.
"""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mipa.protocol import PHENOTYPES

BASELINE = "baseline"

#: What the delta table reports, in the order it reports it. Macro first: it is
#: the headline, because it weights the 16 phenotypes equally rather than letting
#: hypertension (67.7% prevalence) speak for the corpus.
DELTA_METRICS: tuple[str, ...] = (
    "macro_f1",
    "micro_f1",
    "accuracy",
    "macro_recall",
    "micro_recall",
)


@dataclass(frozen=True, slots=True)
class Counts:
    """A binary confusion matrix, and every rate derivable from it.

    `zero_division` follows scikit-learn: an undefined ratio is 0.0, not NaN and
    not 1.0. For F1 that is debatable — a phenotype with no positives and no
    positive predictions arguably scores perfectly — but matching the convention
    MIPA's own `Evaluator` inherits matters more than winning the argument, and
    `n_pos` travels on every row so the case is visible rather than silently
    folded into a macro average.
    """

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.tp + other.tp, self.fp + other.fp, self.tn + other.tn, self.fn + other.fn
        )

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def n_pos(self) -> int:
        """Gold positives. The number that says whether an F1 here is interpretable."""
        return self.tp + self.fn

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        return _ratio(2 * self.tp, 2 * self.tp + self.fp + self.fn)

    @property
    def accuracy(self) -> float:
        return _ratio(self.tp + self.tn, self.n)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True, slots=True)
class Pair:
    """One evaluable (document, phenotype) outcome: a gold label and a prediction."""

    document_id: str
    phenotype: str
    y_true: int
    y_pred: int


@dataclass(frozen=True, slots=True)
class Scores:
    """Aggregates over a set of pairs."""

    n: int
    macro_f1: float
    micro_f1: float
    accuracy: float
    macro_recall: float
    micro_recall: float
    macro_precision: float
    micro_precision: float
    #: Phenotypes with no evaluable pair at all. Excluded from the macro means —
    #: averaging in a 0.0 for a phenotype that was never scored would understate
    #: every arm, and would understate the corrupted arms most, since that is
    #: where pairs go missing.
    absent_phenotypes: tuple[str, ...] = ()


#: (y_true, y_pred) -> which cell of the matrix it lands in.
_CELL = {(1, 1): "tp", (0, 1): "fp", (0, 0): "tn", (1, 0): "fn"}


def confusion(pairs: Iterable[Pair]) -> dict[str, Counts]:
    """Per-phenotype confusion matrices."""
    tallies: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    for pair in pairs:
        tallies[pair.phenotype][_CELL[(pair.y_true, pair.y_pred)]] += 1
    return {phenotype: Counts(**cells) for phenotype, cells in tallies.items()}


def score(pairs: Sequence[Pair]) -> Scores:
    """Macro and micro aggregates over one model x condition.

    Macro is the unweighted mean over phenotypes; micro pools every pair into one
    matrix. They answer different questions and diverge sharply here, because
    prevalence spans 2.8% to 67.7% — micro is effectively a hypertension score,
    macro gives `vte_complication` the same vote.
    """
    per = confusion(pairs)
    scored = [per[p] for p in PHENOTYPES if p in per]
    absent = tuple(p for p in PHENOTYPES if p not in per)
    pooled = sum(scored, Counts())

    return Scores(
        n=len(pairs),
        macro_f1=_mean(c.f1 for c in scored),
        micro_f1=pooled.f1,
        accuracy=pooled.accuracy,
        macro_recall=_mean(c.recall for c in scored),
        micro_recall=pooled.recall,
        macro_precision=_mean(c.precision for c in scored),
        micro_precision=pooled.precision,
        absent_phenotypes=absent,
    )


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


# -- assembling pairs from stored predictions -----------------------------


@dataclass(frozen=True, slots=True)
class Arm:
    """One model x condition: what was attempted, and what could be scored."""

    model: str
    condition: str
    corruption: str
    severity: str
    attempted: int
    pairs: tuple[Pair, ...]

    @property
    def parse_failure_rate(self) -> float:
        return _ratio(self.attempted - len(self.pairs), self.attempted)


def build_arms(
    rows: Iterable[Mapping[str, Any]],
    labels: Mapping[str, frozenset[str]],
) -> dict[tuple[str, str], Arm]:
    """Group stored predictions into arms, joining each to its gold label.

    A row whose `document_id` has no gold label is a join failure, not a negative
    — silently scoring it as 0 would invent ground truth — so it raises. The CLI
    checks the join for all 500 sampled notes during `preflight`, well before any
    of them cost an API call.
    """
    attempted: dict[tuple[str, str], int] = defaultdict(int)
    collected: dict[tuple[str, str], list[Pair]] = defaultdict(list)
    facets: dict[tuple[str, str], tuple[str, str]] = {}

    for row in rows:
        key = (row["model"], row["condition"])
        attempted[key] += 1
        facets.setdefault(key, (row.get("corruption", ""), row.get("severity", "")))

        document_id = row["document_id"]
        if document_id not in labels:
            raise KeyError(
                f"no gold label for document {document_id!r}; the prediction store and "
                "the label file disagree about the sample"
            )
        if row["parse_status"] != "ok" or row["y_pred"] is None:
            continue
        collected[key].append(
            Pair(
                document_id=document_id,
                phenotype=row["phenotype"],
                y_true=int(row["phenotype"] in labels[document_id]),
                y_pred=int(row["y_pred"]),
            )
        )

    return {
        key: Arm(
            model=key[0],
            condition=key[1],
            corruption=facets[key][0],
            severity=facets[key][1],
            attempted=attempted[key],
            pairs=tuple(collected[key]),
        )
        for key in attempted
    }


# -- the three output tables ----------------------------------------------


def prediction_rows(
    rows: Iterable[Mapping[str, Any]],
    labels: Mapping[str, frozenset[str]],
) -> Iterator[dict[str, Any]]:
    """One row per prediction, with the gold label joined on.

    The aggregate tables answer "how much did F1 drop"; this answers everything
    else. Any analysis with note-level structure — a paired test across the 500
    notes, a bootstrap CI resampling notes rather than pairs, a mixed-effects
    model with random intercepts per note and per phenotype — needs the
    unaggregated matrix, and cannot recover it from `phenotype_metrics.csv`.

    Failed pairs are kept, with `y_pred` empty and `parse_status` saying why. An
    analyst who wants them gone can filter on `parse_status == "ok"`; one who
    cannot see them has no way to know the denominator moved.
    """
    for row in rows:
        document_id = row["document_id"]
        if document_id not in labels:
            raise KeyError(
                f"no gold label for document {document_id!r}; the prediction store and "
                "the label file disagree about the sample"
            )
        yield {
            "document_id": document_id,
            "model": row["model"],
            "condition": row["condition"],
            "corruption": row["corruption"],
            "severity": row["severity"],
            "phenotype": row["phenotype"],
            "y_true": int(row["phenotype"] in labels[document_id]),
            "y_pred": row["y_pred"],
            "parse_status": row["parse_status"],
        }


def overall_rows(arms: Mapping[tuple[str, str], Arm]) -> list[dict[str, Any]]:
    """`overall_metrics.csv` — each arm on its own evaluable pairs."""
    rows = []
    for arm in sorted(arms.values(), key=lambda a: (a.model, a.condition)):
        scores = score(arm.pairs)
        rows.append(
            {
                "model": arm.model,
                "condition": arm.condition,
                "corruption": arm.corruption,
                "severity": arm.severity,
                "n_attempted": arm.attempted,
                "n_evaluated": scores.n,
                "parse_failure_rate": round(arm.parse_failure_rate, 6),
                "macro_f1": round(scores.macro_f1, 6),
                "micro_f1": round(scores.micro_f1, 6),
                "accuracy": round(scores.accuracy, 6),
                "macro_recall": round(scores.macro_recall, 6),
                "micro_recall": round(scores.micro_recall, 6),
                "macro_precision": round(scores.macro_precision, 6),
                "micro_precision": round(scores.micro_precision, 6),
                "absent_phenotypes": ";".join(scores.absent_phenotypes),
            }
        )
    return rows


def phenotype_rows(arms: Mapping[tuple[str, str], Arm]) -> list[dict[str, Any]]:
    """`phenotype_metrics.csv` — one row per arm x phenotype, with `n_pos`.

    `n_pos` is not decoration. Two phenotypes carry ~30 positives at n=500, and
    an F1 computed on 30 positives moves visibly when three predictions change.
    A reader who cannot see the denominator cannot tell a real degradation from
    a resampled one.
    """
    rows = []
    for arm in sorted(arms.values(), key=lambda a: (a.model, a.condition)):
        per = confusion(arm.pairs)
        for phenotype in PHENOTYPES:
            counts = per.get(phenotype, Counts())
            rows.append(
                {
                    "model": arm.model,
                    "condition": arm.condition,
                    "corruption": arm.corruption,
                    "severity": arm.severity,
                    "phenotype": phenotype,
                    "n": counts.n,
                    "n_pos": counts.n_pos,
                    "tp": counts.tp,
                    "fp": counts.fp,
                    "tn": counts.tn,
                    "fn": counts.fn,
                    "f1": round(counts.f1, 6),
                    "precision": round(counts.precision, 6),
                    "recall": round(counts.recall, 6),
                    "accuracy": round(counts.accuracy, 6),
                }
            )
    return rows


def delta_rows(
    arms: Mapping[tuple[str, str], Arm],
    baseline: str = BASELINE,
) -> list[dict[str, Any]]:
    """`robustness_deltas.csv` — the headline table.

    Each corrupted arm against **its own model's** baseline, scored on the pairs
    both arms answered. Cross-model comparison is not the experiment: a 4b model
    starting lower than a 27b one says nothing about robustness, and the whole
    point of the paired design is that the difference is within-model,
    within-note and within-phenotype.

    `delta` is corrupted minus baseline, so **negative means degradation** —
    the direction a reader expects when the column is headed "delta".
    """
    rows = []
    for (model, condition), arm in sorted(arms.items()):
        if condition == baseline:
            continue
        base = arms.get((model, baseline))
        if base is None:
            raise KeyError(
                f"no {baseline!r} arm for model {model!r}; a robustness delta needs "
                "the uncorrupted reference for the same model"
            )

        shared = {(p.document_id, p.phenotype) for p in arm.pairs} & {
            (p.document_id, p.phenotype) for p in base.pairs
        }
        base_scores = score([p for p in base.pairs if (p.document_id, p.phenotype) in shared])
        arm_scores = score([p for p in arm.pairs if (p.document_id, p.phenotype) in shared])

        for metric in DELTA_METRICS:
            before = getattr(base_scores, metric)
            after = getattr(arm_scores, metric)
            rows.append(
                {
                    "model": model,
                    "corruption": arm.corruption or condition,
                    "severity": arm.severity,
                    "condition": condition,
                    "metric": metric,
                    "baseline": round(before, 6),
                    "corrupted": round(after, 6),
                    "delta": round(after - before, 6),
                    "delta_pct": round(100.0 * (after - before) / before, 4) if before else None,
                    "n_paired": len(shared),
                    "n_dropped": max(len(base.pairs), len(arm.pairs)) - len(shared),
                    "parse_failure_rate": round(arm.parse_failure_rate, 6),
                }
            )
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write rows, taking the header from the first one.

    stdlib `csv`, not pandas: these tables are thousands of rows, the columns are
    fixed, and the runner should not need a dataframe library to write a file it
    already holds as dicts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_csv_gz(path: Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    """Stream rows to a gzipped CSV, taking the header from the first one.

    Gzip because this file is 672,000 rows and compresses roughly tenfold; CSV
    rather than Parquet because the analysis may well happen in R, and a student
    should not need an Arrow install to read a table of integers. Streamed rather
    than materialised so the writer never holds the whole matrix in memory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    writer: csv.DictWriter[str] | None = None
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        for row in rows:
            if writer is None:
                writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
                writer.writeheader()
            writer.writerow(row)
    return path


def summarise(rows: Sequence[Mapping[str, Any]], metric: str = "macro_f1") -> str:
    """The delta table as a readable block, for `analyze` and the run log."""
    selected = [r for r in rows if r["metric"] == metric]
    if not selected:
        return f"no rows for metric {metric!r}"

    width = max(len(str(r["corruption"])) for r in selected)
    lines = [
        f"{metric} — corrupted vs baseline (negative = degradation)",
        f"{'corruption':<{width}}  {'sev':<6} {'base':>7} {'corr':>7} {'delta':>8} {'%':>8}  n",
    ]
    for row in sorted(selected, key=lambda r: (r["model"], r["corruption"], r["severity"])):
        pct = f"{row['delta_pct']:+8.1f}" if row["delta_pct"] is not None else "       -"
        lines.append(
            f"{row['corruption']:<{width}}  {row['severity']:<6} "
            f"{row['baseline']:7.3f} {row['corrupted']:7.3f} {row['delta']:+8.3f} {pct}  "
            f"{row['n_paired']}"
        )
    return "\n".join(lines)


__all__ = [
    "BASELINE",
    "DELTA_METRICS",
    "Arm",
    "Counts",
    "Pair",
    "Scores",
    "build_arms",
    "confusion",
    "delta_rows",
    "overall_rows",
    "phenotype_rows",
    "prediction_rows",
    "score",
    "summarise",
    "write_csv",
    "write_csv_gz",
]
