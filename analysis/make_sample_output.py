"""Generate a synthetic copy of the Experiment 1 outputs, for pipeline development.

The point is to let downstream analysis be written and debugged before the real
run finishes, so what matters here is that the **schema** is exactly right —
column names, order, dtypes, value ranges, the null convention for a failed
parse. The numbers are invented; the shape is not.

That is why this does not hand-author CSVs. It builds a real `PredictionStore`,
fills it with synthetic predictions, and then calls the same
`mipa_metrics` functions `analyze` calls. The sample cannot drift from the
production schema, because it is produced by the production code.

**Everything numeric in the output is fabricated.** Document ids are synthetic
and deliberately outside MIMIC-IV's `hadm_id` range, so nothing here is
restricted under the PhysioNet DUA and none of it should ever be cited.

Effect sizes are chosen to be *plausible and clearly patterned* rather than
realistic — bigger models degrade less, higher severity hurts more, character
corruptions hurt more than structural ones. A student's pipeline should surface
that structure; if it does not, the pipeline is wrong, and a flat or random mock
would not have caught it.

    python analysis/make_sample_output.py --out sample_output
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from mipa import metrics as mipa_metrics
from mipa.protocol import PHENOTYPES, departures
from mipa.store import Prediction, PredictionStore

MODELS = ("google/gemma-3-4b-it", "google/gemma-3-12b-it", "google/gemma-3-27b-it")
SEVERITIES = ("low", "medium", "high")

#: The nine Experiment 1 corruptions, in their two baskets. The basket a
#: corruption belongs to is the main fixed effect the analysis is looking for, so
#: the mock gives the two baskets clearly different effect sizes.
STRUCTURAL = (
    "section_header_deletion",
    "bullet_to_prose",
    "loss_of_text_structure",
    "spacing_loss",
    "section_duplication",
    "section_header_renaming",
)
CHARACTER = (
    "typographical_errors",
    "homoglyph_substitutions",
    "alphanumeral_variations",
)

#: Corpus prevalence of each phenotype, from the real 1,388-note MIPA corpus.
#: Real numbers, because a pipeline that silently breaks on a phenotype with 30
#: positives should break on the mock too.
PREVALENCE = {
    "hypertension": 0.677,
    "depression": 0.489,
    "diabetes_type_2": 0.283,
    "vte_past": 0.225,
    "obesity": 0.206,
    "hfpef": 0.156,
    "metastatic_cancer": 0.121,
    "rheumatoid_arthritis": 0.118,
    "alcohol_abuse": 0.112,
    "diabetes_type_1": 0.097,
    "hfref": 0.088,
    "sle": 0.081,
    "dementia": 0.073,
    "c_diff_past": 0.073,
    "c_diff_complication": 0.060,
    "vte_complication": 0.060,
}

#: Baseline per-phenotype F1 the mock aims for, by model. Loosely MIPA-shaped:
#: better on common, well-described phenotypes than on rare ones, and better with
#: scale.
BASE_SKILL = {
    "google/gemma-3-4b-it": 0.52,
    "google/gemma-3-12b-it": 0.63,
    "google/gemma-3-27b-it": 0.71,
}

#: Relative macro-F1 loss at `high` severity. Character corruptions bite harder
#: than structural ones, and smaller models bite worst — the interaction the
#: experiment exists to test.
CORRUPTION_EFFECT = {
    "section_header_deletion": 0.14,
    "bullet_to_prose": 0.06,
    "loss_of_text_structure": 0.11,
    "spacing_loss": 0.05,
    "section_duplication": 0.04,
    "section_header_renaming": 0.09,
    "typographical_errors": 0.22,
    "homoglyph_substitutions": 0.31,
    "alphanumeral_variations": 0.13,
}
SEVERITY_SCALE = {"low": 0.30, "medium": 0.62, "high": 1.0}
MODEL_FRAGILITY = {
    "google/gemma-3-4b-it": 1.35,
    "google/gemma-3-12b-it": 1.0,
    "google/gemma-3-27b-it": 0.72,
}


def unit(*parts: object) -> float:
    """A deterministic pseudo-random float in [0, 1).

    BLAKE2b of the inputs rather than `random`, so regenerating the sample on any
    machine produces byte-identical files — a student comparing their pipeline's
    output against a colleague's should be comparing pipelines, not seeds.
    """
    material = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big") / 2**64


def document_ids(n: int) -> list[str]:
    """Synthetic ids, deliberately outside MIMIC-IV's 8-digit `hadm_id` range.

    Real outputs carry real `hadm_id`s and are restricted under the PhysioNet
    DUA. Nothing here is, and the shape difference makes that obvious at a glance
    rather than requiring a caveat nobody reads.
    """
    return [f"MOCK{i:06d}" for i in range(1, n + 1)]


def gold_labels(documents: list[str]) -> dict[str, frozenset[str]]:
    """Assign labels at the real corpus prevalence, independently per phenotype."""
    return {
        doc: frozenset(p for p in PHENOTYPES if unit("label", doc, p) < PREVALENCE[p])
        for doc in documents
    }


def conditions() -> list[tuple[str, str, str]]:
    """`(condition, corruption, severity)`, baseline first — the run's own order."""
    out = [("baseline", "none", "none")]
    out += [(f"{c}/{s}", c, s) for c in sorted(STRUCTURAL + CHARACTER) for s in SEVERITIES]
    return out


def rates(skill: float) -> tuple[float, float]:
    """An arm's skill, expressed as (recall, false-positive rate).

    Corruption is modelled as losing recall faster than precision, because that
    is the direction it actually pushes a model: one that can no longer find the
    evidence stops asserting the phenotype rather than starting to invent it.
    The false-positive rate drifts up only slightly as skill falls.
    """
    return skill, 0.05 + 0.06 * (1.0 - skill)


def predict(doc: str, model: str, phenotype: str, y_true: int, *, recall: float, fpr: float) -> int:
    """One synthetic prediction.

    The draw is keyed on (document, model, phenotype) and **not** on condition,
    which is the whole trick: every arm compares the same underlying draw against
    its own threshold, so a harder arm catches a strict subset of what an easier
    one caught. Effects then come out monotone in severity instead of being
    swamped by independent per-arm noise — with 60 notes, independent draws put
    the sampling error an order of magnitude above the effect being modelled, and
    the mock showed `medium` beating `low`.

    Real results will not be this clean. The mock is deliberately legible so a
    pipeline bug shows up as a *broken* pattern rather than as plausible noise.
    """
    if y_true:
        return int(unit("pos", doc, model, phenotype) < recall)
    return int(unit("neg", doc, model, phenotype) < fpr)


def build_store(path: Path, documents: list[str], labels: dict[str, frozenset[str]]) -> None:
    store = PredictionStore(path)
    for condition, corruption, severity in conditions():
        for model in MODELS:
            loss = (
                0.0
                if corruption == "none"
                else CORRUPTION_EFFECT[corruption]
                * SEVERITY_SCALE[severity]
                * MODEL_FRAGILITY[model]
            )
            recall, fpr = rates(max(0.05, BASE_SKILL[model] * (1.0 - loss)))

            # Parse failures rise with severity: a heavily corrupted note makes a
            # small model likelier to emit prose instead of the JSON it was asked
            # for. The analysis has to cope with a moving denominator, so the mock
            # gives it one.
            failure_rate = 0.0 if corruption == "none" else 0.004 * SEVERITY_SCALE[severity]
            if model == MODELS[0]:
                failure_rate *= 2.5

            batch = []
            for doc in documents:
                for phenotype in PHENOTYPES:
                    y_true = int(phenotype in labels[doc])
                    failed = unit("fail", doc, model, condition, phenotype) < failure_rate
                    y_pred = (
                        None
                        if failed
                        else predict(doc, model, phenotype, y_true, recall=recall, fpr=fpr)
                    )
                    batch.append(
                        Prediction(
                            document_id=doc,
                            model=model,
                            condition=condition,
                            corruption=corruption,
                            severity=severity,
                            phenotype=phenotype,
                            y_pred=y_pred,
                            parse_status="no_json" if failed else "ok",
                            raw_output="I'm sorry, I can't determine that." if failed else None,
                            attempts=2 if failed else 1,
                            latency_ms=900 + int(4200 * unit("lat", doc, model, phenotype)),
                            prompt_tokens=3200 + int(6400 * unit("ptok", doc)),
                            completion_tokens=18 + int(12 * unit("ctok", doc, phenotype)),
                            cost=round(0.00016 + 0.0005 * unit("cost", doc, model), 8),
                        )
                    )
            store.put_many(batch)
    store.set_meta("departures", json.dumps(departures()))
    store.close()


def write_sample_csv(path: Path, documents: list[str], labels: dict[str, frozenset[str]]) -> None:
    """`sample.csv`, same columns the real sampler writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["hadm_id", "note_id", "concepts", "density_band", *PHENOTYPES]
        )
        writer.writeheader()
        for i, doc in enumerate(documents):
            concepts = 180 + int(1500 * unit("concepts", doc))
            writer.writerow(
                {
                    "hadm_id": doc,
                    "note_id": f"{doc}-DS-{i % 90 + 10}",
                    "concepts": concepts,
                    "density_band": min(2, int(3 * unit("band", doc))),
                    **{p: int(p in labels[doc]) for p in PHENOTYPES},
                }
            )


def write_labels_csv(path: Path, labels: dict[str, frozenset[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hadm_id", *PHENOTYPES])
        writer.writeheader()
        for doc, positive in labels.items():
            writer.writerow({"hadm_id": doc, **{p: int(p in positive) for p in PHENOTYPES}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("sample_output"))
    parser.add_argument(
        "-n",
        type=int,
        default=500,
        help=(
            "synthetic notes. The default matches the real run exactly, so the "
            "mock has true dimensions (672,000 predictions) and true sampling "
            "noise — at 120 notes the rare phenotypes are so lumpy that macro "
            "recall stops ordering by model size."
        ),
    )
    args = parser.parse_args()

    documents = document_ids(args.n)
    labels = gold_labels(documents)

    args.out.mkdir(parents=True, exist_ok=True)
    write_sample_csv(args.out / "sample.csv", documents, labels)
    write_labels_csv(args.out / "golden_labels.csv", labels)

    store_path = args.out / "predictions.sqlite"
    store_path.unlink(missing_ok=True)
    build_store(store_path, documents, labels)

    store = PredictionStore(store_path)
    arms = mipa_metrics.build_arms(store.iter_rows(), labels)
    deltas = mipa_metrics.delta_rows(arms)

    mipa_metrics.write_csv_gz(
        args.out / "predictions.csv.gz", mipa_metrics.prediction_rows(store.iter_rows(), labels)
    )
    mipa_metrics.write_csv(args.out / "overall_metrics.csv", mipa_metrics.overall_rows(arms))
    mipa_metrics.write_csv(args.out / "phenotype_metrics.csv", mipa_metrics.phenotype_rows(arms))
    mipa_metrics.write_csv(args.out / "robustness_deltas.csv", deltas)
    mipa_metrics.write_csv(args.out / "parse_failures.csv", list(store.iter_failures()))
    mipa_metrics.write_csv_gz(args.out / "operational.csv.gz", store.operational_rows())

    (args.out / "run_summary.json").write_text(
        json.dumps(
            {
                "MOCK": "Synthetic data. Every number is fabricated. Do not cite.",
                "generated_by": "analysis/make_sample_output.py",
                "models": sorted({a.model for a in arms.values()}),
                "conditions": sorted({a.condition for a in arms.values()}),
                "notes": len(documents),
                "predictions": store.count(),
                "cost_usd": round(store.cost_so_far(), 4),
                "parse_status": store.parse_status_counts(),
                "protocol_departures": departures(),
                "sample": "sample.csv",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    store.close()
    store_path.unlink()  # the SQLite file is an implementation detail, not a deliverable

    print(mipa_metrics.summarise(deltas))
    print(f"\n{len(documents)} notes x {len(MODELS)} models x {len(conditions())} conditions")
    for item in sorted(args.out.iterdir()):
        print(f"  {item.name:<26} {item.stat().st_size / 1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
