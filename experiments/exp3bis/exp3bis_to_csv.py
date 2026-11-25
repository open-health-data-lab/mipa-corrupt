#!/usr/bin/env python
"""Experiment 3 bis' results, in the same files Experiments 1, 2 and 3 emit.

Exp3 had to *reconstruct* its confusion matrices: it was computed directly rather
than through the MIPA runner, so `exp3_to_csv.py` inverts F1 and recall back into
tp/fp/tn/fn and aborts if the algebra disagrees with the reported F1. Exp3bis does
not need that. It ran through `run_exp3.py`, so every prediction is in a store and
every count here is a **direct tally over 18,000 rows** rather than an inversion.

Two places where that shows, and both are improvements rather than format drift:

* `parse_failure_rate` is **0.0**, not empty. Exp3 left it blank because the direct
  analysis never recorded it, and writing a zero would have asserted a clean run
  nobody measured. Exp3bis measured it: all 18,000 predictions parsed.
* `parse_failures.csv` carries its header rather than being a zero-byte file, so
  reading it does not raise `EmptyDataError` on an empty result.

**One phenotype is evaluated per condition**, as in exp3, so macro and micro over a
one-element set are the same number. That is a definition, not an approximation,
and it means an exp3bis `macro_f1` is not comparable to an exp1 `macro_f1` over 16
phenotypes. The `experiment`, `measured_phenotype` and `target_phenotype` columns
are appended so the two can never be silently pooled.

    python experiments/exp3bis/exp3bis_to_csv.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

EXPERIMENT = "exp3bis"
ARM = "ocr_capped"

PRED_COLS = [
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
OPS_COLS = [
    "document_id",
    "model",
    "condition",
    "phenotype",
    "attempts",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "cost",
]
PHENO_COLS = [
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
    "experiment",
    "measured_phenotype",
    "target_phenotype",
]
OVERALL_COLS = [
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
    "experiment",
    "measured_phenotype",
    "target_phenotype",
]
DELTA_COLS = [
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
    "experiment",
    "measured_phenotype",
    "target_phenotype",
]
FLIP_COLS = [
    "experiment",
    "model",
    "corruption",
    "target_phenotype",
    "severity",
    "condition",
    "measured_phenotype",
    "n_compared",
    "flips",
    "lost_positive_pred",
    "gained_positive_pred",
    "lost_positive_pred_and_label",
]
#: The five paired metrics exp1 reports deltas for. Macro and micro coincide here.
DELTA_METRICS = ("macro_f1", "micro_f1", "accuracy", "macro_recall", "micro_recall")


def num(value: float) -> str:
    return f"{value:.6f}"


def rows_of(store: Path, condition: str | None = None) -> list[sqlite3.Row]:
    con = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if condition is None:
            return con.execute("select * from predictions").fetchall()
        return con.execute("select * from predictions where condition = ?", (condition,)).fetchall()
    finally:
        con.close()


def split_condition(condition: str) -> tuple[str, str, str]:
    """`exp3bis/ocr_capped_hfpef/full` -> (corruption dir, arm, phenotype)."""
    corruption = condition.split("/")[1]
    return corruption, ARM, corruption[len(ARM) + 1 :]


def score(pairs: list[tuple[int, int]]) -> dict[str, float | int]:
    """tp/fp/tn/fn and the four rates, from (y_true, y_pred) pairs."""
    tp = sum(1 for t, p in pairs if t == 1 and p == 1)
    fp = sum(1 for t, p in pairs if t == 0 and p == 1)
    tn = sum(1 for t, p in pairs if t == 0 and p == 0)
    fn = sum(1 for t, p in pairs if t == 1 and p == 0)
    n = len(pairs)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    return {
        "n": n,
        "n_pos": tp + fn,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "f1": f1,
        "precision": prec,
        "recall": rec,
        "accuracy": (tp + tn) / n if n else 0.0,
    }


def pair_against_baseline(group, base, labels, model, question):
    """Pair one arm's predictions with the baseline, dropping cells either side lacks.

    Returns the two (y_true, y_pred) sequences and the four flip counts. Kept apart
    from `main` because it is the only place a prediction is matched to its clean
    counterpart, and that is the step every number downstream rests on.
    """
    pairs, base_pairs = [], []
    flips = lost = gained = lost_and_label = 0
    for r in group:
        b = base.get((r["document_id"], model, question))
        if b is None or r["y_pred"] is None or b["y_pred"] is None:
            continue
        truth = int(question in labels[r["document_id"]])
        pairs.append((truth, r["y_pred"]))
        base_pairs.append((truth, b["y_pred"]))
        if r["y_pred"] != b["y_pred"]:
            flips += 1
            if b["y_pred"] == 1:
                lost += 1
                lost_and_label += truth
            else:
                gained += 1
    return pairs, base_pairs, flips, lost, gained, lost_and_label


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, default=Path("data/mipa_exp3bis/predictions.sqlite"))
    parser.add_argument(
        "--baseline-store",
        type=Path,
        default=Path("data/mipa_exp1/results_run1/predictions.sqlite"),
    )
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/mipa_exp3bis/run1"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from mipa.sample import read_labels

    labels = read_labels(args.sample)
    rows = rows_of(args.store)
    base = {
        (r["document_id"], r["model"], r["phenotype"]): r
        for r in rows_of(args.baseline_store, "baseline")
    }
    print(f"{len(rows)} predictions, {len(base)} baseline cells")

    # ---------------------------------------------------- predictions + operational
    with gzip.open(args.out / "predictions.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PRED_COLS)
        for r in rows:
            corruption, _, _ = split_condition(r["condition"])
            w.writerow(
                [
                    r["document_id"],
                    r["model"],
                    r["condition"],
                    corruption,
                    r["severity"],
                    r["phenotype"],
                    int(r["phenotype"] in labels[r["document_id"]]),
                    "" if r["y_pred"] is None else r["y_pred"],
                    r["parse_status"],
                ]
            )
    with gzip.open(args.out / "operational.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(OPS_COLS)
        for r in rows:
            w.writerow(
                [
                    r["document_id"],
                    r["model"],
                    r["condition"],
                    r["phenotype"],
                    r["attempts"],
                    r["latency_ms"],
                    r["prompt_tokens"],
                    r["completion_tokens"],
                    r["cost"],
                ]
            )

    # ---------------------------------------------------------------- parse failures
    with (args.out / "parse_failures.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "document_id",
                "model",
                "condition",
                "phenotype",
                "parse_status",
                "attempts",
                "raw_output",
            ]
        )
        for r in rows:
            if r["parse_status"] != "ok":
                w.writerow(
                    [
                        r["document_id"],
                        r["model"],
                        r["condition"],
                        r["phenotype"],
                        r["parse_status"],
                        r["attempts"],
                        r["raw_output"] or "",
                    ]
                )

    # --------------------------------------------- group by arm, then score directly
    arms: dict[tuple[str, str, str], list] = defaultdict(list)
    for r in rows:
        arms[(r["model"], r["condition"], r["phenotype"])].append(r)

    pheno_rows, overall_rows, delta_rows, flip_rows = [], [], [], []
    for (model, condition, question), group in sorted(arms.items()):
        corruption, arm, target = split_condition(condition)
        pairs, base_pairs, flips, lost, gained, lost_and_label = pair_against_baseline(
            group, base, labels, model, question
        )
        cur, ref = score(pairs), score(base_pairs)
        tail = [EXPERIMENT, question, target]
        pheno_rows.append(
            [
                model,
                condition,
                arm,
                "full",
                question,
                cur["n"],
                cur["n_pos"],
                cur["tp"],
                cur["fp"],
                cur["tn"],
                cur["fn"],
                num(cur["f1"]),
                num(cur["precision"]),
                num(cur["recall"]),
                num(cur["accuracy"]),
                *tail,
            ]
        )
        overall_rows.append(
            [
                model,
                condition,
                arm,
                "full",
                len(group),
                cur["n"],
                "0.0",
                num(cur["f1"]),
                num(cur["f1"]),
                num(cur["accuracy"]),
                num(cur["recall"]),
                num(cur["recall"]),
                num(cur["precision"]),
                num(cur["precision"]),
                0,
                *tail,
            ]
        )
        for metric in DELTA_METRICS:
            key = {
                "macro_f1": "f1",
                "micro_f1": "f1",
                "accuracy": "accuracy",
                "macro_recall": "recall",
                "micro_recall": "recall",
            }[metric]
            b_val, c_val = ref[key], cur[key]
            pct = (c_val - b_val) / b_val * 100 if b_val else 0.0
            delta_rows.append(
                [
                    model,
                    arm,
                    "full",
                    condition,
                    metric,
                    num(b_val),
                    num(c_val),
                    num(c_val - b_val),
                    f"{pct:.4f}",
                    len(pairs),
                    len(group) - len(pairs),
                    "0.0",
                    *tail,
                ]
            )
        flip_rows.append(
            [
                EXPERIMENT,
                model,
                arm,
                target,
                "full",
                condition,
                question,
                len(pairs),
                flips,
                lost,
                gained,
                lost_and_label,
            ]
        )

    for name, header, body in (
        ("phenotype_metrics.csv", PHENO_COLS, pheno_rows),
        ("overall_metrics.csv", OVERALL_COLS, overall_rows),
        ("robustness_deltas.csv", DELTA_COLS, delta_rows),
        (f"{EXPERIMENT}_flips.csv", FLIP_COLS, flip_rows),
    ):
        with (args.out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(body)
        print(f"  {name:<28} {len(body):>5} rows")

    summary = {
        "experiment": EXPERIMENT,
        "arms": len(arms),
        "models": sorted({r["model"] for r in rows}),
        "conditions": sorted({r["condition"] for r in rows}),
        "predictions": len(rows),
        "parse_status": {"ok": sum(1 for r in rows if r["parse_status"] == "ok")},
        "cost_usd": round(sum(r["cost"] or 0.0 for r in rows), 6),
        "question": (
            "does corruption of one phenotype's concept evidence, capped at one "
            "misread per token, change that phenotype's F1 on the evaluated sample?"
        ),
        "design": (
            "exp3's phenotype-evidence target with input.ocr_confusion at "
            "max_edits_per_token=1, over all 500 sampled notes, paired against the "
            "run1 baseline predictions for the same question, notes and models. "
            "Dose-matched to exp3's typo arm, which at rate 1.00 also makes one edit "
            "per eligible unit."
        ),
        "derivation": (
            "tp/fp/tn/fn tallied directly from the prediction store; nothing is "
            "reconstructed from reported rates, as exp3's packaging had to do. macro "
            "and micro coincide because one phenotype is evaluated per condition, so "
            "an exp3bis macro_f1 is NOT comparable to an exp1 macro_f1 over 16 "
            "phenotypes. parse_failure_rate is a measured 0.0, not an assumed one."
        ),
        "source": str(args.store),
        "baseline": str(args.baseline_store),
    }
    (args.out / "run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
