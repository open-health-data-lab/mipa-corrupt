"""Experiment 3's results, in the same three CSVs Experiments 1 and 2 emit.

Exp3 was computed directly rather than run through the MIPA runner, so it
produced one JSON of finished arms instead of `overall_metrics.csv`,
`phenotype_metrics.csv` and `robustness_deltas.csv`. The numbers are complete;
the packaging is not, and a result nobody can open in the same tool as its
siblings does not get compared to them.

**The confusion matrix is reconstructed, not invented.** The JSON reports F1 and
recall; those two plus the positive count determine the whole table:

    precision = F1 * R / (2R - F1)          # invert the F1 definition
    tp = R * n_pos                          # recall's own definition
    fp = tp * (1/precision - 1)
    fn = n_pos - tp
    tn = n - tp - fp - fn

`n_pos` comes from the sample's gold labels, and exp3 evaluates all 500 sampled
notes, so it is the same denominator. Every reconstruction is checked against
the reported F1 and the run aborts if any disagrees — algebra that silently
drifts is worse than no table.

**What is genuinely absent stays empty**, never zero: `parse_failure_rate` was
not recorded by the direct analysis, and writing 0.0 would assert a clean run
nobody measured.

**Exp3 evaluates ONE phenotype per condition**, so its "overall" metrics are
that phenotype's — macro and micro over a one-element set are both just it.
That is a definition, not an approximation, but it means an exp3 `macro_f1` is
not comparable to an exp1 `macro_f1` over 16 phenotypes. The `experiment` and
`measured_phenotype` columns are appended so the two can never be silently
pooled.

    python experiments/exp3/exp3_to_csv.py
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

TOLERANCE = 1e-5

#: Exp1/exp2 column orders, reproduced exactly. Exp3-specific columns are
#: APPENDED so a concatenation lines up and the extra context is not lost.
OVERALL = [
    "model", "condition", "corruption", "severity", "n_attempted", "n_evaluated",
    "parse_failure_rate", "macro_f1", "micro_f1", "accuracy", "macro_recall", "micro_recall",
    "macro_precision", "micro_precision", "absent_phenotypes",
]
PHENOTYPE = [
    "model", "condition", "corruption", "severity", "phenotype", "n", "n_pos",
    "tp", "fp", "tn", "fn", "f1", "precision", "recall", "accuracy",
]
DELTAS = [
    "model", "corruption", "severity", "condition", "metric", "baseline", "corrupted",
    "delta", "delta_pct", "n_paired", "n_dropped", "parse_failure_rate",
]

EXTRA = ["experiment", "measured_phenotype", "target_phenotype"]


def _num(value: object) -> str:
    """Format, or empty when the quantity is genuinely undetermined."""
    if value is None:
        return ""
    return f"{value:.6f}" if isinstance(value, float) else str(value)


class Reconstruction(dict):
    """A single arm's confusion matrix, derived from F1 and recall."""


def reconstruct(f1: float, recall: float, n_pos: int, n: int) -> Reconstruction | None:
    """tp/fp/tn/fn from the two reported rates, or None when undetermined.

    Total collapse is a real outcome, not a failure to reconstruct: when the
    model stops predicting a phenotype entirely, F1 and recall are both 0, so
    tp=0 and fn=n_pos are known exactly while fp is underdetermined — every
    false-positive count yields F1=0. Those fields are returned as None and
    written empty. Dropping the arm instead would delete the strongest result
    in the experiment (`dementia` on 4b, 0.520 -> 0.000).
    """
    if f1 == 0 and recall == 0 and n_pos:
        return Reconstruction(
            tp=0, fp=None, tn=None, fn=n_pos, precision=None, recall=0.0, f1=0.0, accuracy=None
        )
    determined = n_pos and recall > 0 and f1 > 0 and (2 * recall - f1) > 0
    if not determined:
        return None
    precision = f1 * recall / (2 * recall - f1)
    tp = round(recall * n_pos)
    fp = round(tp * (1 / precision - 1)) if precision > 0 else -1
    fn = n_pos - tp
    tn = n - tp - fp - fn
    check = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
    if min(tp, fp, fn, tn) < 0 or abs(check - f1) > TOLERANCE:
        return None
    return Reconstruction(
        tp=tp, fp=fp, tn=tn, fn=fn, precision=precision, recall=recall, f1=f1,
        accuracy=(tp + tn) / n if n else 0.0,
    )


#: Every corruption-arm prefix the experiments emit, across exp3, exp3bis and
#: exp3_corrected. A name missing here silently yields an empty target column.
CORRUPTIONS = (
    "homoglyph_substitutions",
    "typographical_errors",
    "ocr_capped",
)


def split_condition(condition: str) -> tuple[str, str, str]:
    """`exp3/homoglyph_substitutions_hfpef/full` -> corruption, target, severity.

    Anchored on the known corruption prefixes rather than the last underscore,
    which would turn `typographical_errors_type_2_diabetes` into a corruption
    called `typographical_errors_type_2`.

    Longest prefix first, so a name that is a prefix of another cannot claim a
    condition belonging to it. Unknown prefixes fall through to a corruption with
    no target rather than raising, which is how an arm from a newer experiment
    used to disappear into an empty target column without saying so.
    """
    _, middle, severity = condition.split("/")
    for corruption in sorted(CORRUPTIONS, key=len, reverse=True):
        if middle.startswith(corruption + "_"):
            return corruption, middle[len(corruption) + 1 :], severity
    return middle, "", severity


def positives(sample: Path) -> dict[str, int]:
    """Positive count per phenotype over the evaluated notes."""
    with sample.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    counts: dict[str, int] = {}
    for name in rows[0] if rows else {}:
        if name in {"hadm_id", "note_id", "concepts", "density_band"}:
            continue
        counts[name] = sum(
            1 for r in rows if str(r.get(name, "")).strip() not in {"", "0", "0.0", "False"}
        )
    return counts



#: Fields the direct analysis actually reported, in its own vocabulary.
NATIVE = [
    "experiment", "model", "corruption", "target_phenotype", "severity", "condition",
    "measured_phenotype", "n_compared", "baseline_f1", "corrupted_f1", "delta_f1",
    "baseline_recall", "corrupted_recall", "delta_recall",
    "flips", "lost_positive_pred", "gained_positive_pred", "lost_positive_pred_and_label",
]


def write_original(out: Path, source: Path, payload: dict, prepared: list) -> None:
    """The measurement as exp3 reported it, before any reshaping.

    The sibling files reshape exp3 into exp1/exp2's schema and reconstruct a
    confusion matrix to fill it. Both steps are sound and both are steps away
    from what was measured, so the unreshaped form is kept beside them:
    **nothing in here is derived**. If the reconstruction is ever found wrong,
    this is what it has to be re-derived from, and the JSON is copied verbatim
    for the same reason.
    """
    out.mkdir(parents=True, exist_ok=True)
    (out / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    with (out / "exp3_arms.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(NATIVE)
        for arm, corruption, target, severity, _n_pos, _b, _c in prepared:
            w.writerow(
                [
                    "exp3", arm["model"], corruption, target, severity, arm["condition"],
                    arm["phenotype"], arm["compared"],
                    _num(arm["baseline_f1"]), _num(arm["corrupted_f1"]), _num(arm["delta_f1"]),
                    _num(arm["baseline_recall"]), _num(arm["corrupted_recall"]),
                    _num(arm["corrupted_recall"] - arm["baseline_recall"]),
                    arm.get("flips", ""), arm.get("lost_positive_pred", ""),
                    arm.get("gained_positive_pred", ""),
                    arm.get("lost_positive_pred_and_label", ""),
                ]
            )

    (out / "README.md").write_text(
        "# Exp3 as measured\n\n"
        "`exp3_arms.csv` is one row per arm in the direct analysis's own vocabulary, and\n"
        "`" + source.name + "` is that analysis's output copied verbatim. **No value in this\n"
        "directory is derived.**\n\n"
        "The files in the parent directory reshape this into the schema Experiments 1 and\n"
        "2 use, which requires reconstructing a confusion matrix from the reported F1 and\n"
        "recall. That reconstruction is exact and verified, but it is an inference; this\n"
        "is what it was inferred from.\n\n"
        "| Column | |\n|---|---|\n"
        "| `baseline_f1`, `corrupted_f1`, `delta_f1` | paired against run1's baseline "
        "predictions for the same question, notes and models |\n"
        "| `flips` | predictions that changed between baseline and corrupted |\n"
        "| `lost_positive_pred` | flips that dropped a positive prediction |\n"
        "| `lost_positive_pred_and_label` | ...where the gold label was also positive — "
        "the corruption doing what the experiment predicts |\n\n"
        f"Noise floor: {payload.get('noise_floor', 'n/a')}.\n",
        encoding="utf-8",
    )


def main() -> int:  # noqa: PLR0912, PLR0915 - four file writers, one pass each
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=Path("results/measurements/exp3_results.json"))
    ap.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    ap.add_argument("--out", type=Path, default=Path("results/exp3/run1"))
    args = ap.parse_args()

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    arms = payload["arms"]
    n_pos_by_phenotype = positives(args.sample)
    args.out.mkdir(parents=True, exist_ok=True)

    prepared, failed = [], []
    for arm in arms:
        corruption, target, severity = split_condition(arm["condition"])
        n, phenotype = arm["compared"], arm["phenotype"]
        n_pos = n_pos_by_phenotype.get(phenotype, 0)
        base = reconstruct(arm["baseline_f1"], arm["baseline_recall"], n_pos, n)
        corr = reconstruct(arm["corrupted_f1"], arm["corrupted_recall"], n_pos, n)
        if base is None or corr is None:
            failed.append(f"{arm['model']} {arm['condition']}")
        prepared.append((arm, corruption, target, severity, n_pos, base, corr))

    with (args.out / "phenotype_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow([*PHENOTYPE, *EXTRA])
        for arm, corruption, target, severity, n_pos, _base, corr in prepared:
            if corr is None:
                continue
            w.writerow(
                [
                    arm["model"], arm["condition"], corruption, severity, arm["phenotype"],
                    arm["compared"], n_pos, _num(corr["tp"]), _num(corr["fp"]),
                    _num(corr["tn"]), _num(corr["fn"]), _num(corr["f1"]),
                    _num(corr["precision"]), _num(corr["recall"]), _num(corr["accuracy"]),
                    "exp3", arm["phenotype"], target,
                ]
            )

    with (args.out / "overall_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow([*OVERALL, *EXTRA])
        for arm, corruption, target, severity, _n_pos, _base, corr in prepared:
            if corr is None:
                continue
            # One phenotype is evaluated, so macro and micro coincide with it by
            # definition. `parse_failure_rate` is left empty: the direct
            # analysis did not record it.
            w.writerow(
                [
                    arm["model"], arm["condition"], corruption, severity,
                    arm["compared"], arm["compared"], "",
                    _num(corr["f1"]), _num(corr["f1"]), _num(corr["accuracy"]),
                    _num(corr["recall"]), _num(corr["recall"]),
                    _num(corr["precision"]), _num(corr["precision"]), 0,
                    "exp3", arm["phenotype"], target,
                ]
            )

    metrics = (("macro_f1", "f1"), ("micro_f1", "f1"), ("accuracy", "accuracy"),
               ("macro_recall", "recall"), ("micro_recall", "recall"))
    with (args.out / "robustness_deltas.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow([*DELTAS, *EXTRA])
        for arm, corruption, target, severity, _n_pos, base, corr in prepared:
            if base is None or corr is None:
                continue
            for name, key in metrics:
                b, c = base[key], corr[key]
                if b is None or c is None:
                    continue  # underdetermined on one side; no delta to state
                w.writerow(
                    [
                        arm["model"], corruption, severity, arm["condition"], name,
                        f"{b:.6f}", f"{c:.6f}", f"{c - b:.6f}",
                        f"{(c - b) / b:+.4f}" if b else "", arm["compared"], 0, "",
                        "exp3", arm["phenotype"], target,
                    ]
                )

    write_original(args.out / "_original", args.results, payload, prepared)

    with (args.out / "exp3_flips.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        fields = ("flips", "lost_positive_pred", "gained_positive_pred",
                  "lost_positive_pred_and_label")
        w.writerow(["experiment", "model", "corruption", "target_phenotype", "severity",
                    "condition", "measured_phenotype", "n_compared", *fields])
        for arm, corruption, target, severity, _n_pos, _b, _c in prepared:
            w.writerow(["exp3", arm["model"], corruption, target, severity, arm["condition"],
                        arm["phenotype"], arm["compared"], *[arm.get(f, "") for f in fields]])

    (args.out / "run_summary.json").write_text(
        json.dumps(
            {
                "experiment": "exp3",
                "question": payload.get("question"),
                "design": payload.get("design"),
                "noise_floor": payload.get("noise_floor"),
                "models": payload.get("models"),
                "cost_usd": payload.get("cost"),
                "arms": len(arms),
                "set_digests": payload.get("set_digests"),
                "source": str(args.results),
                "derivation": (
                    "tp/fp/tn/fn reconstructed from the reported F1 and recall plus the "
                    "sample's positive counts; every reconstruction verified against the "
                    "reported F1. macro and micro coincide because one phenotype is "
                    "evaluated per condition, so an exp3 macro_f1 is NOT comparable to an "
                    "exp1 macro_f1 over 16 phenotypes. parse_failure_rate was not recorded "
                    "and is left empty rather than assumed zero."
                ),
            },
            indent=2, sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    ok = sum(1 for *_, corr in prepared if corr is not None)
    print(f"{ok}/{len(arms)} arms reconstructed and verified")
    for name in ("overall_metrics.csv", "phenotype_metrics.csv", "robustness_deltas.csv",
                 "exp3_flips.csv", "run_summary.json"):
        print(f"  wrote {args.out / name}")
    for name in ("exp3_arms.csv", args.results.name, "README.md"):
        print(f"  wrote {args.out / '_original' / name}")
    if failed:
        print(f"\n{len(failed)} arm(s) could NOT be reconstructed and were omitted:")
        for name in failed:
            print(f"  {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
