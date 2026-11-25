#!/usr/bin/env python
"""Experiment 4: corrupt what the evidence *means*, not whether it can be read.

**The hole this fills.** Experiments 1-3 all corrupt legibility. A typo and an
OCR misread damage the surface of a word and leave its meaning intact, which is
precisely why `Hypertenslon` still reads as hypertension and why a capable model
absorbs even saturating, perfectly aimed corruption at a median cost of 0.013
macro-F1. No arm in the study has ever changed what a note *says*.

Assertion cues are the smallest perturbation that does. `no evidence of DVT` and
`evidence of DVT` differ by two words and assert opposite things, and 40% of
phenotype-evidence mentions in this corpus carry such a cue.

**Four arms, one per cue class**, each scoped to cues governing *any* panel
phenotype's evidence — the semantic channel's analogue of experiment 2's
clinical aim. All 16 questions are scored per arm, so unlike experiment 3 this
yields a macro-F1 directly comparable to experiments 1 and 2.

**This is not an accuracy experiment.** Stripping `no evidence of` changes what
the note asserts, so the golden label is no longer the right reference for the
corrupted note and an F1 against it measures drift, not error. The primary
endpoint is churn and its gained/lost split. The library says the same thing in
its own vocabulary: all four operators declare
`Contract.REFERENCE_ALTERING_BY_DESIGN`.

**Detector quality is not uniform and the gate records it per arm.** Negation is
validated at 0.9289 F1 against the NegEx gold; experiencer has no gold at all and
scores kappa 0.22. A null in the experiencer arm cannot be distinguished from the
detector never firing, so every arm reports `eligible_n` beside its effect and
carries its operator's own `simulates` string into the manifest.

Layout follows `mipa_corpora.discover`, as exp3 and exp3bis do:

    data/experiments/exp4/<cue_class>/full/notes.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import warnings
from collections import Counter
from importlib.resources import files
from pathlib import Path

from robustehr.concepts import hierarchy
from robustehr.concepts.cache import MentionCache
from robustehr.concepts.context import qualify
from robustehr.concepts.phenotype import build, in_cohort, index_document, load_maps
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, parse_severity
from robustehr.store import write_run
from robustehr.target import Governs, PhenotypeEvidence

ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: One arm per cue class. The names are the reported dimension rather than the
#: ConText category, because `uncertainty` spans two of the latter.
ARMS = (
    ("negation", "semantic.negation_flip"),
    ("uncertainty", "semantic.uncertainty_flip"),
    ("temporality", "semantic.temporality_shift"),
    ("experiencer", "semantic.experiencer_shift"),
)

SEVERITY_LITERAL = "1.00"
SEVERITY_DIR = "full"

#: Cues governing a panel phenotype, whichever phenotype that is. `pheno=*` is
#: "any declared one", which is a different request from naming all fifteen.
TARGET = Governs(PhenotypeEvidence())


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def gate(doses: list, edits: list, simulates: str) -> dict:
    """What replaces exp3bis's realism gate, which does not transfer.

    `token_damage` measures characters changed per token. A whole-word
    substitution changes most of the token *by design* — `denies` -> `reports`
    is the intended perturbation, not a failure of restraint — so every arm
    would score `verdict: ablation` and the gate would mean nothing.

    What matters for a semantic operator instead is whether the detector fired
    at all, and how well that detector is validated. An arm reporting a null
    effect on zero eligible cues is reporting nothing, and must not be readable
    as robustness.
    """
    eligible = sum(d.eligible_n for d in doses)
    applied = sum(d.applied_n for d in doses)
    treated = sum(1 for group in edits if group)
    return {
        "notes": len(doses),
        "notes_treated": treated,
        "eligible_cues": eligible,
        "applied_edits": applied,
        "edits_per_treated_note": round(applied / treated, 2) if treated else 0.0,
        "detector_quality": simulates,
        "verdict": "measurable" if eligible else "detector silent",
    }


def report(rows: list[dict]) -> list[str]:
    print(
        "\n%-14s %7s %9s %9s %9s  %s"
        % ("arm", "notes", "treated", "cues", "edits", "verdict"),
        file=sys.stderr,
    )
    failures = []
    for row in rows:
        g = row["gate"]
        print(
            "%-14s %7d %9d %9d %9d  %s"
            % (
                row["arm"],
                g["notes"],
                g["notes_treated"],
                g["eligible_cues"],
                g["applied_edits"],
                g["verdict"],
            ),
            file=sys.stderr,
        )
        if g["verdict"] != "measurable":
            failures.append(row["arm"])
    return failures


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--cache-digest", default="6e56a7c3a64d53ff")
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--salt", default="rep0")
    parser.add_argument("--phenotype", action="extend", nargs="*", default=None)
    parser.add_argument("--arm", action="extend", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=0, help="first N notes, for a smoke run")
    parser.add_argument("--out", type=Path, default=Path("data/experiments/exp4"))
    args = parser.parse_args(argv)

    registry.register_builtins()
    csv.field_size_limit(1_000_000_000)
    with args.notes.open(newline="", encoding="utf-8") as handle:
        text_by_note = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    with args.sample.open(newline="", encoding="utf-8") as handle:
        sample = [(r["hadm_id"], r["note_id"]) for r in csv.DictReader(handle)]
    if args.limit:
        sample = sample[: args.limit]

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = list(args.phenotype or in_cohort("mipa"))
    phenotypes = build(sorted(names), isa, code_to_cuis, cui_to_codes)
    mention_cache = MentionCache(root=args.cache, config_digest=args.cache_digest)

    digests = {
        "phenotype_vetting.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_vetting.yaml"),
        "phenotype_closure.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_closure.yaml"),
        "assertion_flips.yaml": sha16(ROBUSTEHR_RESOURCES / "assertion_flips.yaml"),
        "umls_facets.json": sha16(Path("data/umls_facets.json")),
    }

    wanted = set(args.arm) if args.arm else {a for a, _ in ARMS}
    arms = [(a, op) for a, op in ARMS if a in wanted]
    sev = parse_severity(SEVERITY_LITERAL)
    operators = {arm: registry.get(op_id)() for arm, op_id in arms}

    writers: dict[str, object] = {}
    handles = []
    doses: dict[str, list] = {a: [] for a, _ in arms}
    edit_groups: dict[str, list] = {a: [] for a, _ in arms}
    literals: dict[str, Counter] = {a: Counter() for a, _ in arms}
    for arm, _ in arms:
        path = args.out / arm / SEVERITY_DIR / "notes.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8")
        handles.append(handle)
        writer = csv.writer(handle)
        writer.writerow(["hadm_id", "note_id", "note_corrupted"])
        writers[arm] = writer

    skipped = 0
    clean_texts: dict[str, str] = {}
    for i, (hadm_id, note_id) in enumerate(sample, 1):
        text = text_by_note.get(note_id)
        if text is None:
            skipped += 1
            continue
        doc = Document.from_text(text, uid=note_id)
        clean_texts[note_id] = text
        mentions = mention_cache.get(doc)
        if mentions is None:
            skipped += 1
            continue
        idx = index_document(mentions, phenotypes)
        # The join `governs(...)` resolves against: which cues decided the
        # reading of which evidence span. ConText computes it; nothing here
        # picks a proximity window.
        assertions = qualify(text, [e.span for e in idx.evidence])
        for arm, op_id in arms:
            op = operators[arm]
            result = apply_operator(
                doc,
                op,
                op.meta,
                sev,
                scope=Scope(target=TARGET),
                salt=args.salt,
                run_id=f"exp4.{arm}.{SEVERITY_DIR}",
                mentions=mentions,
                phenotypes=idx,
                assertions=assertions,
            )
            applied = result.apply_result.applied
            writers[arm].writerow([hadm_id, note_id, result.text])
            doses[arm].append(result.dose)
            edit_groups[arm].append(applied)
            for edit in applied:
                literals[arm][text[edit.start : edit.end].strip().lower()] += 1
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} notes", file=sys.stderr)
    for handle in handles:
        handle.close()

    rows = []
    for arm, op_id in arms:
        directory = args.out / arm / SEVERITY_DIR
        simulates = operators[arm].meta.simulates
        g = gate(doses[arm], edit_groups[arm], simulates)
        rows.append({"arm": arm, "gate": g})
        write_run(
            directory,
            run_id=f"exp4.{arm}.{SEVERITY_DIR}",
            doses=doses[arm],
            edits=edit_groups[arm],
            corpus="corpus",
            # With the notes, each replacement is stored as its minimal difference
            # (one offset and one letter for a typo) instead of the retyped word.
            texts=clean_texts,
            extra={
                "experiment": "exp4",
                "corruption": arm,
                "operator": op_id,
                "params": {},
                "severity": SEVERITY_LITERAL,
                "severity_dir": SEVERITY_DIR,
                "salt": args.salt,
                "target": TARGET.canon(),
                "design": (
                    "Every assertion cue governing the evidence of any panel "
                    "phenotype is rewritten, one cue class per arm. The semantic "
                    "channel's analogue of experiment 2's clinical aim: pooled "
                    "across phenotypes, so all 16 questions are scored per arm "
                    "and the macro-F1 is comparable to experiments 1 and 2. "
                    "Reference-altering by design, so churn and its direction "
                    "are the endpoint and F1-vs-original-labels measures drift "
                    "from the answer the clean note supported, not error."
                ),
                "assertion_gate": g,
                "cue_literals": dict(literals[arm].most_common(40)),
                "contains_note_text": True,
                "set_digests": digests,
                "generated_by": "experiments/exp4/gen_exp4_dataset.py",
            },
        )

    failures = report(rows)
    if skipped:
        print(f"skipped {skipped} sample notes with no text or cache entry", file=sys.stderr)

    summary = {
        "experiment": "exp4",
        "conditions": [a for a, _ in arms],
        "sample": str(args.sample),
        "notes_per_condition": len(sample) - skipped,
        "target": TARGET.canon(),
        "set_digests": digests,
        "generated_by": "experiments/exp4/gen_exp4_dataset.py",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out} ({len(arms)} conditions)")
    if failures:
        print(
            f"DETECTOR SILENT for {len(failures)} arm(s): {', '.join(failures)}. "
            "An arm with no eligible cues reports nothing and must not be read "
            "as robustness.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
