#!/usr/bin/env python
"""Does corrupting the closure-recovered evidence change the model's call?

**The question.** The closure layer added concepts to each `pheno=X` target on
the argument that they carry the phenotype's decision basis — "diastolic heart
failure" for hfpef, "metastasis" for metastatic cancer, "Lasix" for the heart
failures. Coverage says the corpus writes them; this probe asks whether the
MODEL actually rides on them: corrupt only those spans, and see whether
predictions flip.

**Design.** For a sample of label-positive notes per phenotype, three arms:

* ``baseline`` — the clean note;
* ``old``      — corrupt only spans whose mention CUI is in the PRE-closure
                 set (what exp2-style targeting would have hit);
* ``delta``    — corrupt only spans whose CUI is in (closed − old): the
                 closure keeps plus the RxNorm identity variants.

Same operator, severity, salt and — deliberately — the same target canon in
both corrupted arms: the selection RNG ranks units by a hash that folds in
``target.canon()``, so giving both arms the probe Phenotype the same name
makes their scope canons byte-identical and the arms differ only through the
eligible set. That is the causal contrast; anything else would compare two
different lotteries.

If the closure captured real decision basis, flips concentrate in ``delta``
on the notes where ``old`` had little to hit — exactly the audit's cases
(the hfref note whose entire cardiac evidence was one EF line).

**What this is not.** Not a robustness result (tiny n, positives only, one
model) — it is a validity check that the treatment now reaches the decision
basis, reported beside the coverage numbers. Flip counts are per-note paired
comparisons against the same model's baseline call.

Departures and reuse: notes and labels from the golden corpus; mentions from
the clean-note cache (no QuickUMLS at probe time); the vendored MIPA protocol
via `mipa_client.classify` (one call per note-arm, ~$0.0002 each); predictions
cached in a JSONL keyed by sha256(document|model|condition|phenotype) so
reruns are free.
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

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.cache import MentionCache
from robustehr.concepts.phenotype import (
    Phenotype,
    build,
    index_document,
    load_definitions,
    load_maps,
)
from robustehr.document import Document
from robustehr.metrics.describe import load_group_map, read_groups
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, parse_severity
from robustehr.target import PhenotypeEvidence

#: RobustEHR's packaged resources, located through the installed `robustehr`
#: package rather than through `src/robustehr/resources/...`. This repository is
#: independent of RobustEHR's checkout layout, and the relative path only ever
#: resolved when the process happened to be running from inside that source tree.
ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: Our phenotype name -> the MIPA protocol's phenotype key (the label column
#: whose description the prompt interpolates). One key per phenotype: where
#: MIPA splits complication/past, the probe asks the broader "past" framing.
PROTOCOL_KEY = {
    "hfpef": "hfpef",
    "hfref": "hfref",
    "metastatic_cancer": "metastatic_cancer",
    "type_2_diabetes": "diabetes_type_2",
    "type_1_diabetes": "diabetes_type_1",
    "hypertension": "hypertension",
    "obesity": "obesity",
    "dementia": "dementia",
    "depression": "depression",
    "rheumatoid_arthritis": "rheumatoid_arthritis",
    "systemic_lupus_erythematosus": "sle",
    "alcohol_use_disorder": "alcohol_abuse",
    "clostridioides_difficile": "c_diff_past",
    "deep_vein_thrombosis": "vte_past",
    "pulmonary_embolism": "vte_past",
}

ARMS = ("baseline", "old", "delta")


def prediction_key(document_id: str, model: str, condition: str, phenotype: str) -> str:
    return hashlib.sha256("\x1f".join([document_id, model, condition, phenotype]).encode()).hexdigest()


class JsonlCache:
    """Tiny append-only prediction cache; reruns cost nothing."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    self.rows[row["key"]] = row

    def put(self, row: dict[str, Any]) -> None:
        self.rows[row["key"]] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def sample_notes(positive: list[str], n: int) -> list[str]:
    """Deterministic spread: hash-ordered, so the sample is stable and unbiased
    by whatever ordered the label file."""
    return sorted(positive, key=lambda uid: hashlib.sha256(uid.encode()).hexdigest())[:n]


#: Operator params, exactly as `experiments/exp1_exp2/run_experiments.py` declares them.
OP_PARAMS = {"input.typo": {}, "input.ocr_confusion": {"mode": "glyph"}}


def corrupt(doc: Document, mentions: Any, cuis: frozenset[str], op: Any, sev: Any, salt: str):
    """One arm's corrupted text and dose. Constant probe name -> constant canon."""
    probe = Phenotype(name="probe", seed_codes=(), concept_cuis=cuis, concept_codes=frozenset())
    idx = index_document(mentions, [probe])
    result = apply_operator(
        doc,
        op,
        op.meta,
        sev,
        scope=Scope(target=PhenotypeEvidence("probe")),
        params=OP_PARAMS.get(op.meta.id, {}),
        salt=salt,
        mentions=mentions,
        phenotypes=idx,
    )
    return result.text, result.dose


def redact(doc: Document, mentions: Any, cuis: frozenset[str]):
    """The ablation ceiling: replace each evidence span with the corpus's own
    de-identification placeholder.

    This is NOT noise corruption and is never presented as such — it answers
    the prior question "does the concept-mention channel carry the decision at
    all?". `___` is what every MIMIC note already shows where information was
    removed, so the treatment is maximally in-distribution: the model sees a
    note whose evidence was redacted, a thing it sees on every real note.
    Deterministic (no RNG, no severity): every evidence span, right to left so
    offsets stay valid.
    """
    probe = Phenotype(name="probe", seed_codes=(), concept_cuis=cuis, concept_codes=frozenset())
    idx = index_document(mentions, [probe])
    spans = sorted(
        {(e.span.start, e.span.end) for e in idx.evidence}, key=lambda s: -s[0]
    )
    text = doc.text
    for start, end in spans:
        text = text[:start] + "___" + text[end:]
    return text, len(spans)


async def run_all(pending: list[dict[str, Any]], model: str, cache: JsonlCache) -> None:
    from mipa.client import ClientConfig, OpenRouterClient, load_api_key

    key = load_api_key(None, Path("openrouterapi.txt") if Path("openrouterapi.txt").exists() else None)
    # One model, short run: open the per-model throttle to the adaptive
    # limiter's own ceiling and let it back off if the API pushes back.
    config = ClientConfig(global_concurrency=16, per_model_concurrency=12)
    async with OpenRouterClient(key, config, models=(model,)) as client:
        async def one(task: dict[str, Any]) -> None:
            attempt = await client.classify(model, task["protocol_key"], task["text"])
            cache.put(
                {
                    "key": task["key"],
                    "document_id": task["uid"],
                    "phenotype": task["phenotype"],
                    "condition": task["condition"],
                    "model": model,
                    "y_pred": attempt.y_pred,
                    "parse_status": str(attempt.parse_status),
                    "cost": attempt.cost,
                }
            )

        await asyncio.gather(*(one(t) for t in pending))


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--phenotype",
        action="extend",
        nargs="*",
        default=None,
        help="default: the audit-exposed four",
    )
    parser.add_argument("--n", type=int, default=75)
    parser.add_argument("--model", default="google/gemma-3-12b-it")
    parser.add_argument("--operator", default="input.typo")
    parser.add_argument("--severity-index", type=int, default=1, help="0=low 1=medium 2=high")
    parser.add_argument(
        "--saturate",
        action="store_true",
        help="corrupt EVERY eligible span (rate 1.00) instead of an exp2 "
        "ladder rung. The ladder probes exp2-comparable doses; saturation "
        "probes the decision basis — with 1-2 edits the model reads the "
        "surviving mentions, which the medium-severity null demonstrated",
    )
    parser.add_argument(
        "--treatment",
        choices=("operator", "redact", "retest"),
        default="operator",
        help="`operator` corrupts spans with the named noise operator; "
        "`redact` replaces every evidence span with the corpus's ___ "
        "placeholder — the ablation ceiling, a different question, reported "
        "as such",
    )
    parser.add_argument(
        "--arms",
        action="extend",
        nargs="*",
        choices=("old", "delta", "closed"),
        default=None,
        help="which evidence sets to treat (default: old delta). `closed` is "
        "old ∪ delta — the complete concept channel",
    )
    parser.add_argument("--salt", default="rep0")
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/golden_labels.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--cache-digest", default="6e56a7c3a64d53ff")
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument(
        "--predictions", type=Path, default=Path("data/causal_probe/predictions.jsonl")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("results/measurements/causal_probe.json")
    )
    parser.add_argument("--dry-run", action="store_true", help="corrupt and count doses, no LLM")
    args = parser.parse_args(argv)
    names = args.phenotype or ["hfpef", "hfref", "metastatic_cancer", "type_2_diabetes"]
    arms = ["retest"] if args.treatment == "retest" else (args.arms or ["old", "delta"])
    if args.out == Path("results/measurements/causal_probe.json"):
        if args.treatment == "retest":
            args.out = Path("results/measurements/causal_probe_retest.json")
        elif args.treatment == "redact":
            args.out = Path("results/measurements/causal_probe_redacted.json")
        elif args.saturate:
            suffix = "" if args.operator == "input.typo" else f"_{args.operator.split('.')[-1]}"
            args.out = Path(f"results/measurements/causal_probe_saturated{suffix}.json")

    registry.register_builtins()
    op = registry.get(args.operator)()
    sev_literal = "1.00" if args.saturate else op.meta.severity_levels[args.severity_index]
    sev = parse_severity(sev_literal)

    def condition(arm: str) -> str:
        # Baseline text is treatment-independent; the treated arms are not, so
        # the cache key must carry the treatment, operator and severity or a
        # rerun under another regime would silently reuse the wrong
        # predictions.
        if arm == "baseline":
            return "probe/baseline"
        if args.treatment == "retest":
            return "probe/baseline_retest"
        if args.treatment == "redact":
            return f"probe/{arm}/redact/all"
        return f"probe/{arm}/{args.operator}/{sev_literal}"

    csv.field_size_limit(1_000_000_000)
    with args.notes.open(newline="", encoding="utf-8") as handle:
        notes = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    group_map = load_group_map("mipa")
    groups = read_groups(args.labels, group_map)
    positive: dict[str, set[str]] = {}
    for column, uids in groups.items():
        for pheno in group_map.get(column, ()):
            positive.setdefault(pheno, set()).update(u for u in uids if u in notes)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    definitions = load_definitions()
    built = {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}
    vetting = facets.load_vetting()
    closure_candidates = facets.load_closure()
    edges = facets.load()
    mention_cache = MentionCache(root=args.cache, config_digest=args.cache_digest)

    cache = JsonlCache(args.predictions)
    pending: list[dict[str, Any]] = []
    doses: dict[str, dict[str, Any]] = {}
    rows: dict[str, Any] = {}

    for name in names:
        closed = built[name].concept_cuis
        closure_kept = closure_candidates.get(name, frozenset()) & vetting.get(name, {}).get(
            "closure", frozenset()
        )
        medication = facets.medications(
            frozenset(c for code in definitions[name].seeds for c in code_to_cuis.get(code, ())),
            build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis,
            edges,
            declared=definitions[name].medication_seeds,
            vetted=vetting.get(name, {}).get("medication"),
        )
        identity = frozenset(c for c, t in medication.provenance.items() if t == "identity")
        delta = (closure_kept | identity) & closed
        old = closed - delta
        arm_sets = {"old": old, "delta": delta, "closed": closed, "retest": frozenset()}
        sample = sample_notes(sorted(positive.get(name, ())), args.n)
        arm_doses: dict[str, list[int]] = {arm: [] for arm in arms}
        edited = dict.fromkeys(arms, 0)
        for uid in sample:
            doc = Document.from_text(notes[uid], uid=uid)
            mentions = mention_cache.get(doc)
            if mentions is None:
                continue
            texts = {"baseline": notes[uid]}
            for arm in arms:
                if args.treatment == "retest":
                    # The identical clean text, asked again: the temperature-0.5
                    # test-retest noise floor every flip count is read against.
                    text, applied = notes[uid], 0
                elif args.treatment == "redact":
                    text, applied = redact(doc, mentions, arm_sets[arm])
                else:
                    text, dose = corrupt(doc, mentions, arm_sets[arm], op, sev, args.salt)
                    applied = dose.applied_n
                texts[arm] = text
                arm_doses[arm].append(applied)
                edited[arm] += applied > 0
            for arm in ("baseline", *arms):
                key = prediction_key(uid, args.model, condition(arm), name)
                if key in cache.rows or args.dry_run:
                    continue
                pending.append(
                    {
                        "key": key,
                        "uid": uid,
                        "phenotype": name,
                        "protocol_key": PROTOCOL_KEY[name],
                        "condition": condition(arm),
                        "text": texts[arm],
                    }
                )
        rows[name] = {
            "sampled_notes": len(sample),
            "treatment": args.treatment,
            **{f"{arm}_set": len(arm_sets[arm]) for arm in arms},
            **{f"notes_with_{arm}_edits": edited[arm] for arm in arms},
            **{
                f"mean_edits_{arm}": (
                    round(sum(arm_doses[arm]) / len(arm_doses[arm]), 2)
                    if arm_doses[arm]
                    else 0
                )
                for arm in arms
            },
        }
        doses[name] = arm_doses
        print(
            f"{name}: {len(sample)} notes | "
            + " | ".join(f"{arm}={len(arm_sets[arm])} cuis, edited {edited[arm]}" for arm in arms),
            file=sys.stderr,
        )

    if args.dry_run:
        print(json.dumps(rows, indent=1))
        return 0

    print(f"{len(pending)} predictions to fetch (cache: {len(cache.rows)})", file=sys.stderr)
    if pending:
        asyncio.run(run_all(pending, args.model, cache))

    # Flip analysis: paired against the same note's baseline call, with the
    # direction kept apart — losing a positive (1->0) is the causal signal;
    # gaining one (0->1) is instability.
    for name in names:
        sample = sample_notes(sorted(positive.get(name, ())), args.n)
        flips = dict.fromkeys(arms, 0)
        lost = dict.fromkeys(arms, 0)
        gained = dict.fromkeys(arms, 0)
        denom = dict.fromkeys(arms, 0)
        baseline_pos = 0
        for uid in sample:
            preds = {
                arm: cache.rows.get(prediction_key(uid, args.model, condition(arm), name), {}).get(
                    "y_pred"
                )
                for arm in ("baseline", *arms)
            }
            if preds["baseline"] is None:
                continue
            baseline_pos += preds["baseline"] == 1
            for arm in arms:
                if preds[arm] is None:
                    continue
                denom[arm] += 1
                if preds[arm] != preds["baseline"]:
                    flips[arm] += 1
                    if preds["baseline"] == 1:
                        lost[arm] += 1
                    else:
                        gained[arm] += 1
        rows[name]["baseline_positive"] = baseline_pos
        for arm in arms:
            rows[name].update(
                {
                    f"flips_{arm}": flips[arm],
                    f"lost_positive_{arm}": lost[arm],
                    f"gained_positive_{arm}": gained[arm],
                    f"compared_{arm}": denom[arm],
                    f"flip_rate_{arm}": (
                        round(flips[arm] / denom[arm], 4) if denom[arm] else None
                    ),
                }
            )

    payload = {
        "question": (
            "does treating the closure-recovered evidence (delta) change the "
            "phenotyping model's prediction more than treating the "
            "pre-closure set (old)?"
        ),
        "design": (
            "paired per-note comparison, label-positive samples, arms against "
            "a shared baseline with identical seeds and target canon so the "
            "selection lottery is shared and arms differ only in the eligible "
            "set. `redact` replaces evidence spans with the corpus's ___ "
            "placeholder — an ABLATION ceiling answering whether the concept "
            "channel carries the decision at all, not a noise-robustness "
            "result. A validity check on the treatment either way."
        ),
        "treatment": args.treatment,
        "arms": list(arms),
        "operator": args.operator if args.treatment == "operator" else None,
        "severity": sev_literal if args.treatment == "operator" else None,
        "model": args.model,
        "salt": args.salt,
        "vetting_sha256": hashlib.sha256(
            (ROBUSTEHR_RESOURCES / "phenotype_vetting.yaml").read_bytes()
        ).hexdigest()[:16],
        "phenotypes": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(rows, indent=1))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
