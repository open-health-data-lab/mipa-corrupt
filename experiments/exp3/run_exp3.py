#!/usr/bin/env python
"""Run experiment 3: targeted-question predictions over the exp3 corpora.

**One question per condition.** Each exp3 condition corrupts exactly one
phenotype's evidence (`experiments/exp3/gen_exp3_dataset.py`), so each is scored on
exactly that phenotype's protocol question — over ALL 500 sampled notes,
positives and negatives, edited and untouched — which is what makes the
per-condition F1 computable and directly comparable to the run1 baseline F1
for the same question, notes and models. The untouched notes double as a
within-condition control: their flip rate against baseline should sit at the
measured 0.4% test-retest noise floor.

**Nothing new is invented.** Predictions go through the same client and
protocol as run1 (`mipa_client.classify`, one call per note-question), land in
a `PredictionStore` keyed the same way (restart = set difference), and the
metrics come from `mipa_metrics.build_arms` — the same Counts/F1 code that
produced `run1/phenotype_metrics.csv`. Baseline rows are read from the run1
store, never re-predicted.

Outputs:
* `data/mipa_exp3/predictions.sqlite` — the store (note-derived, stays in data/)
* `data/mipa_exp3/phenotype_metrics.csv` — one row per model x condition
* `data/mipa_exp3/deltas.csv` — corrupted vs baseline per arm, with paired
  flip counts split by direction and by label stratum
* `results/measurements/exp3_results.json` — aggregates only, licence-safe
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
import warnings
from importlib.resources import files
from pathlib import Path
from typing import Any

from mipa import corpora as mipa_corpora
from mipa import metrics as mipa_metrics
from mipa import sample as mipa_sample
from mipa.store import Prediction, PredictionStore, prediction_key

#: RobustEHR's packaged resources, located through the installed `robustehr`
#: package rather than through `src/robustehr/resources/...`. This repository is
#: independent of RobustEHR's checkout layout, and the relative path only ever
#: resolved when the process happened to be running from inside that source tree.
ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: The condition's target concept set -> the protocol question(s) scored on it.
#:
#: **A tuple, because concept identity does not determine the question.** MIPA
#: splits two conditions by temporality rather than by concept: `c_diff_past` is
#: C. difficile before or during the stay, `c_diff_complication` is C. difficile
#: arising AS a complication of it, and both are asserted with the same
#: concepts. Corrupting the C. diff evidence degrades both, so both are scored.
#:
#: The first version mapped each target to one question and picked the `_past`
#: variant, leaving `c_diff_complication` and `vte_complication` unmeasured —
#: which is 2 of MIPA's 16 phenotypes, and precisely the two the sampler floored
#: to 30 positives so they WOULD be estimable.
#:
#: `deep_vein_thrombosis` and `pulmonary_embolism` both score the VTE pair: they
#: are two different concept sets whose corruption attacks the same outcomes, so
#: their arms are not independent phenotype results and must not be counted as
#: such in an aggregate over exp3.
QUESTION: dict[str, tuple[str, ...]] = {
    "hypertension": ("hypertension",),
    "obesity": ("obesity",),
    "dementia": ("dementia",),
    "depression": ("depression",),
    "rheumatoid_arthritis": ("rheumatoid_arthritis",),
    "systemic_lupus_erythematosus": ("sle",),
    "alcohol_use_disorder": ("alcohol_abuse",),
    "type_1_diabetes": ("diabetes_type_1",),
    "type_2_diabetes": ("diabetes_type_2",),
    "hfpef": ("hfpef",),
    "hfref": ("hfref",),
    "metastatic_cancer": ("metastatic_cancer",),
    "clostridioides_difficile": ("c_diff_past", "c_diff_complication"),
    "deep_vein_thrombosis": ("vte_past", "vte_complication"),
    "pulmonary_embolism": ("vte_past", "vte_complication"),
}

DEFAULT_MODELS = ("google/gemma-3-4b-it", "google/gemma-3-12b-it")


def corpus_digests(root: Path) -> dict[str, str]:
    """The digests the GENERATOR recorded, from any one arm's manifest.

    Every arm of a run carries the same set, so the first readable one answers
    for all of them. Falls back to recomputing from the installed resources
    when a corpus predates the manifest field, and says which it did.
    """
    for manifest in sorted(root.glob("*/*/manifest.json")):
        try:
            found = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        digests = found.get("set_digests") or (found.get("extra") or {}).get("set_digests")
        if digests:
            return dict(digests)
    return {
        name: hashlib.sha256((ROBUSTEHR_RESOURCES / name).read_bytes()).hexdigest()[:16]
        for name in ("phenotype_vetting.yaml", "phenotype_closure.yaml")
        if (ROBUSTEHR_RESOURCES / name).exists()
    }


def phenotype_of(condition_name: str) -> str:
    """`exp3/typographical_errors_hfpef/full` -> `hfpef`."""
    corruption = condition_name.split("/")[1]
    for name in sorted(QUESTION, key=len, reverse=True):
        if corruption.endswith(f"_{name}"):
            return name
    raise ValueError(f"no phenotype in condition {condition_name!r}")


async def predict_all(
    tasks: list[dict[str, Any]], models: tuple[str, ...], store: PredictionStore
) -> None:
    from mipa.client import ClientConfig, OpenRouterClient, load_api_key

    key = load_api_key(
        None, Path("openrouterapi.txt") if Path("openrouterapi.txt").exists() else None
    )
    config = ClientConfig(global_concurrency=16, per_model_concurrency=8)
    done = 0
    async with OpenRouterClient(key, config, models=models) as client:

        async def one(task: dict[str, Any]) -> None:
            nonlocal done
            attempt = await client.classify(task["model"], task["phenotype"], task["text"])
            store.put(
                Prediction(
                    document_id=task["document_id"],
                    model=task["model"],
                    condition=task["condition"],
                    corruption=task["corruption"],
                    severity=task["severity"],
                    phenotype=task["phenotype"],
                    y_pred=attempt.y_pred,
                    parse_status=str(attempt.parse_status.value)
                    if hasattr(attempt.parse_status, "value")
                    else str(attempt.parse_status),
                    attempts=attempt.attempts,
                    latency_ms=attempt.latency_ms,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                    cost=attempt.cost,
                )
            )
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(tasks)} predictions", file=sys.stderr)

        await asyncio.gather(*(one(t) for t in tasks))


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912, PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiments", type=Path, default=Path("data/experiments"))
    parser.add_argument(
        "--experiment",
        default="exp3",
        help=(
            "which experiment tree under --experiments to score. exp3bis carries "
            "the same phenotype targets with the OCR arm capped at one misread "
            "per token; the condition names differ, so its predictions land on "
            "their own keys in the store rather than colliding with exp3's."
        ),
    )
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--store", type=Path, default=Path("data/mipa_exp3/predictions.sqlite"))
    parser.add_argument("--baseline-store", type=Path, default=Path("run1/predictions.sqlite"))
    parser.add_argument("--out", type=Path, default=Path("data/mipa_exp3"))
    parser.add_argument("--results", type=Path, default=Path("results/measurements/exp3_results.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--all-questions",
        action="store_true",
        help=(
            "score every phenotype question on every condition rather than the "
            "ones its name names. Experiment 4 pools its aim across the panel, "
            "so no phenotype can be recovered from a condition name and all 16 "
            "questions apply; exp3 and exp3bis leave this off and are unchanged."
        ),
    )
    args = parser.parse_args(argv)

    conditions = [
        c for c in mipa_corpora.discover(args.experiments, args.experiment) if c.name != "baseline"
    ]
    labels = mipa_sample.read_labels(args.sample)
    sample_ids = set(labels)
    print(f"{len(conditions)} conditions, {len(sample_ids)} notes, models: {args.models}")

    args.store.parent.mkdir(parents=True, exist_ok=True)
    store = PredictionStore(args.store)
    completed = store.completed_keys()
    tasks: list[dict[str, Any]] = []
    all_questions = sorted({q for qs in QUESTION.values() for q in qs})
    for cond in conditions:
        # An arm aimed at one phenotype is scored on that phenotype's questions;
        # an arm aimed at a whole panel has no single phenotype to recover from
        # its name and is scored on all sixteen, which is what makes its macro-F1
        # comparable to experiments 1 and 2.
        questions = all_questions if args.all_questions else QUESTION[phenotype_of(cond.name)]
        notes = mipa_corpora.read_notes(cond.notes_csv, keep=sample_ids)
        for hadm_id, text in notes.items():
            for model in args.models:
                for question in questions:
                    if prediction_key(hadm_id, model, cond.name, question) in completed:
                        continue
                    tasks.append(
                        {
                            "document_id": hadm_id,
                            "model": model,
                            "condition": cond.name,
                            "corruption": cond.corruption,
                            "severity": cond.severity,
                            "phenotype": question,
                            "text": text,
                        }
                    )
    print(f"{len(tasks)} predictions to fetch ({len(completed)} already stored)")
    if args.dry_run:
        return 0
    if tasks:
        asyncio.run(predict_all(tasks, tuple(args.models), store))

    # -- metrics: same machinery as run1 -----------------------------------
    wanted_models = set(args.models)
    exp3_rows = [r for r in store.iter_rows() if r["model"] in wanted_models]
    arms = mipa_metrics.build_arms(exp3_rows, labels)
    # phenotype_rows emits one row per PROTOCOL phenotype per arm, zero-filled
    # for questions the arm never asked; exp3 asks exactly one per condition, so
    # the zero-filled rest are dropped. Under --all-questions every row was
    # actually asked and none may be dropped -- and the condition name carries no
    # phenotype to filter on, so calling phenotype_of here would raise.
    metric_rows = [
        r
        for r in mipa_metrics.phenotype_rows(arms)
        if args.all_questions or r["phenotype"] in QUESTION[phenotype_of(r["condition"])]
    ]
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "phenotype_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metric_rows[0].keys()))
        writer.writeheader()
        writer.writerows(metric_rows)

    # Baseline rows for the questions exp3 asks, from the run1 store.
    import sqlite3

    questions = sorted({q for qs in QUESTION.values() for q in qs})
    con = sqlite3.connect(args.baseline_store)
    con.row_factory = sqlite3.Row
    marks = ",".join("?" for _ in questions)
    baseline_rows = [
        dict(r)
        for r in con.execute(
            f"SELECT document_id, model, condition, corruption, severity, phenotype, "
            f"y_pred, parse_status FROM predictions "
            f"WHERE condition='baseline' AND phenotype IN ({marks}) "
            f"AND model IN ({','.join('?' for _ in wanted_models)})",
            [*questions, *sorted(wanted_models)],
        )
    ]
    base_arms = mipa_metrics.build_arms(baseline_rows, labels)
    base_f1: dict[tuple[str, str], dict[str, Any]] = {}
    for row in mipa_metrics.phenotype_rows(base_arms):
        base_f1[(row["model"], row["phenotype"])] = row
    base_pred: dict[tuple[str, str, str], int | None] = {
        (r["document_id"], r["model"], r["phenotype"]): r["y_pred"]
        for r in baseline_rows
        if r["parse_status"] == "ok"
    }

    exp3_pred: dict[tuple[str, str, str, str], int | None] = {
        (r["condition"], r["document_id"], r["model"], r["phenotype"]): r["y_pred"]
        for r in exp3_rows
        if r["parse_status"] == "ok" and r["y_pred"] is not None
    }
    delta_rows: list[dict[str, Any]] = []
    for row in metric_rows:
        model, condition, question = row["model"], row["condition"], row["phenotype"]
        base = base_f1.get((model, question), {})
        flips = lost = gained = lost_pos = compared = 0
        for hadm_id in sorted(sample_ids):
            b = base_pred.get((hadm_id, model, question))
            c = exp3_pred.get((condition, hadm_id, model, question))
            if b is None or c is None:
                continue
            compared += 1
            if b != c:
                flips += 1
                if b == 1:
                    lost += 1
                    lost_pos += question in labels[hadm_id]
                else:
                    gained += 1
        delta_rows.append(
            {
                "model": model,
                "condition": condition,
                "phenotype": question,
                "baseline_f1": base.get("f1"),
                "corrupted_f1": row["f1"],
                "delta_f1": (
                    round(row["f1"] - base["f1"], 6) if base.get("f1") is not None else None
                ),
                "baseline_recall": base.get("recall"),
                "corrupted_recall": row["recall"],
                "compared": compared,
                "flips": flips,
                "lost_positive_pred": lost,
                "lost_positive_pred_and_label": lost_pos,
                "gained_positive_pred": gained,
            }
        )
    with (args.out / "deltas.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(delta_rows[0].keys()))
        writer.writeheader()
        writer.writerows(delta_rows)

    payload = {
        "question": (
            "does full-dose corruption of one phenotype's concept evidence "
            "change that phenotype's F1 on the evaluated sample?"
        ),
        "design": (
            "one protocol question per condition, all 500 sampled notes "
            "(positives, negatives, untouched notes included), paired against "
            "the run1 baseline predictions for the same question/notes/models. "
            "Untouched notes are the within-condition control: their flip rate "
            "should match the 0.4% test-retest noise floor."
        ),
        "models": args.models,
        "noise_floor": "5/1125 = 0.4% (causal_probe_retest.json)",
        # Read from the CORPUS, not recomputed from the installed resources.
        #
        # Recomputing describes whatever is on disk when scoring runs, which is
        # not necessarily what generated the corpus — and the two diverge
        # exactly when it matters, after a resource has been rebuilt. The
        # generator already recorded what it used in every arm's manifest, so
        # that is the authoritative record and this copies it.
        #
        # It also keeps the set complete. `validation/protocol.md` §10 requires
        # a result naming a `pheno=` target to report the anchor and specificity
        # digests alongside the closure and vetting ones; hardcoding two of them
        # here silently produced a non-compliant artifact.
        "set_digests": corpus_digests(args.experiments / args.experiment),
        "cost": store.cost_so_far(),
        "arms": delta_rows,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    width = max(len(r["condition"]) for r in delta_rows)
    print(
        f"{'condition':<{width}} {'model':<12} {'question':<20} "
        f"{'base F1':>8} {'corr F1':>8} {'ΔF1':>8} {'lost+':>6}"
    )
    for r in sorted(delta_rows, key=lambda x: (x["condition"], x["model"])):
        model_short = r["model"].split("/")[-1].replace("gemma-3-", "")
        print(
            f"{r['condition']:<{width}} {model_short:<12} {r['phenotype']:<20} "
            f"{r['baseline_f1'] if r['baseline_f1'] is not None else '—':>8} "
            f"{r['corrupted_f1']:>8} "
            f"{r['delta_f1'] if r['delta_f1'] is not None else '—':>8} {r['lost_positive_pred']:>6}"
        )
    print(f"-> {args.out} and {args.results} | cost ${store.cost_so_far():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
