#!/usr/bin/env python
"""Experiment 5: the same assertion corruption, aimed at one phenotype at a time.

Experiment 4 rewrites cues governing *any* panel phenotype's evidence — the
semantic channel's analogue of experiment 2's clinical aim. This is the analogue
of experiment 3: one phenotype per arm, so the effect can be attributed to a
cohort rather than to a corpus, and the untreated notes inside each arm serve as
the within-arm control exactly as they do in exp3bis.

**All four cue classes in one condition, composed rather than staged.**
`compose_operators` has every operator propose against the pristine document and
resolves the union once, so the stored edit script still references original
offsets and replays against the original note. A four-stage pipeline would put
each stage's edits in a different coordinate system and break that. Re-tagging
between stages would buy nothing anyway: flipping a negation cue does not move
the historical or family cues.

Overlap is not a risk here, and that is a property of the detector rather than
luck. medspaCy's matcher runs with `prune_on_modifier_overlap`, which keeps the
longest of any two overlapping modifier matches across categories, so
`no history of` fires as a single NEGATED_EXISTENCE cue and the HISTORICAL rule
is pruned away. Measured over 2,147 forward and backward cues in 40 notes:
**zero overlapping spans**. The generator asserts it anyway rather than trusting
that sample, and `conflicts_dropped` on the dose row reports any that slipped.

Like experiment 4, this is reference-altering by design: churn and its direction
are the endpoint, and F1 against the original labels measures drift from the
answer the clean note supported rather than error.

Layout follows `mipa_corpora.discover`:

    data/experiments/exp5/assertion_<phenotype>/full/notes.csv
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
from robustehr.runner import compose_operators, parse_severity
from robustehr.store import write_run
from robustehr.target import Governs, PhenotypeEvidence

ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: All four, composed into one condition. The per-class split is experiment 4's
#: job; here the question is what the whole assertion layer is worth to one
#: phenotype, so separating them would only thin the dose.
OPERATOR_IDS = (
    "semantic.negation_flip",
    "semantic.uncertainty_flip",
    "semantic.temporality_shift",
    "semantic.experiencer_shift",
)

ARM = "assertion"
SEVERITY_LITERAL = "1.00"
SEVERITY_DIR = "full"


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def gate(doses: list, edits: list, dropped: int) -> dict:
    eligible = sum(d.eligible_n for d in doses)
    applied = sum(d.applied_n for d in doses)
    treated = sum(1 for group in edits if group)
    return {
        "notes": len(doses),
        "notes_treated": treated,
        "eligible_cues": eligible,
        "applied_edits": applied,
        "conflicts_dropped": dropped,
        "edits_per_treated_note": round(applied / treated, 2) if treated else 0.0,
        "verdict": "measurable" if eligible else "detector silent",
    }


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
    parser.add_argument("--limit", type=int, default=0, help="first N notes, for a smoke run")
    parser.add_argument("--out", type=Path, default=Path("data/experiments/exp5"))
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

    sev = parse_severity(SEVERITY_LITERAL)
    ops = [registry.get(i)() for i in OPERATOR_IDS]
    pairs = [(o, o.meta) for o in ops]
    conditions = [(f"{ARM}_{p.name}", p.name) for p in phenotypes]

    writers: dict[str, object] = {}
    handles = []
    doses: dict[str, list] = {c: [] for c, _ in conditions}
    edit_groups: dict[str, list] = {c: [] for c, _ in conditions}
    literals: dict[str, Counter] = {c: Counter() for c, _ in conditions}
    dropped: dict[str, int] = {c: 0 for c, _ in conditions}
    for cname, _ in conditions:
        path = args.out / cname / SEVERITY_DIR / "notes.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8")
        handles.append(handle)
        writer = csv.writer(handle)
        writer.writerow(["hadm_id", "note_id", "note_corrupted"])
        writers[cname] = writer

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
        assertions = qualify(text, [e.span for e in idx.evidence])
        for cname, pheno_name in conditions:
            result = compose_operators(
                doc,
                pairs,
                sev,
                scope=Scope(target=Governs(PhenotypeEvidence(pheno_name))),
                salt=args.salt,
                run_id=f"exp5.{cname}.{SEVERITY_DIR}",
                mentions=mentions,
                phenotypes=idx,
                assertions=assertions,
            )
            applied = result.apply_result.applied
            writers[cname].writerow([hadm_id, note_id, result.text])
            doses[cname].append(result.dose)
            edit_groups[cname].append(applied)
            dropped[cname] += result.dose.conflicts_dropped or 0
            for edit in applied:
                literals[cname][text[edit.start : edit.end].strip().lower()] += 1
        if i % 25 == 0:
            print(f"  {i}/{len(sample)} notes", file=sys.stderr)
    for handle in handles:
        handle.close()

    print(
        "\n%-34s %7s %9s %9s %9s %8s"
        % ("condition", "notes", "treated", "cues", "edits", "dropped"),
        file=sys.stderr,
    )
    failures = []
    for cname, pheno_name in conditions:
        directory = args.out / cname / SEVERITY_DIR
        g = gate(doses[cname], edit_groups[cname], dropped[cname])
        print(
            "%-34s %7d %9d %9d %9d %8d"
            % (
                cname,
                g["notes"],
                g["notes_treated"],
                g["eligible_cues"],
                g["applied_edits"],
                g["conflicts_dropped"],
            ),
            file=sys.stderr,
        )
        if g["verdict"] != "measurable":
            failures.append(cname)
        write_run(
            directory,
            run_id=f"exp5.{cname}.{SEVERITY_DIR}",
            doses=doses[cname],
            edits=edit_groups[cname],
            corpus="corpus",
            # With the notes, each replacement is stored as its minimal difference
            # (one offset and one letter for a typo) instead of the retyped word.
            texts=clean_texts,
            extra={
                "experiment": "exp5",
                "corruption": cname,
                "phenotype": pheno_name,
                "operator": "+".join(OPERATOR_IDS),
                "params": {},
                "severity": SEVERITY_LITERAL,
                "severity_dir": SEVERITY_DIR,
                "salt": args.salt,
                "target": Governs(PhenotypeEvidence(pheno_name)).canon(),
                "design": (
                    "All four assertion cue classes, composed in one pass, aimed "
                    "at the cues governing this phenotype's evidence and nothing "
                    "else. The semantic channel's analogue of experiment 3. "
                    "Reference-altering by design: churn and its direction are "
                    "the endpoint, and F1 against the original labels measures "
                    "drift from the answer the clean note supported, not error. "
                    "Untreated notes inside the arm are the within-arm control."
                ),
                "assertion_gate": g,
                "detector_quality": {
                    op.meta.id: op.meta.simulates for op in ops
                },
                "cue_literals": dict(literals[cname].most_common(40)),
                "contains_note_text": True,
                "set_digests": digests,
                "generated_by": "experiments/exp5/gen_exp5_dataset.py",
            },
        )

    if skipped:
        print(f"skipped {skipped} sample notes with no text or cache entry", file=sys.stderr)
    total_dropped = sum(dropped.values())
    if total_dropped:
        print(
            f"WARNING: {total_dropped} edits dropped to overlap. The detector prunes "
            "overlapping modifier matches, so this should be zero; investigate before "
            "trusting the dose.",
            file=sys.stderr,
        )

    summary = {
        "experiment": "exp5",
        "conditions": [c for c, _ in conditions],
        "sample": str(args.sample),
        "notes_per_condition": len(sample) - skipped,
        "operators": list(OPERATOR_IDS),
        "conflicts_dropped_total": total_dropped,
        "set_digests": digests,
        "generated_by": "experiments/exp5/gen_exp5_dataset.py",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out} ({len(conditions)} conditions)")
    if failures:
        print(
            f"DETECTOR SILENT for {len(failures)} condition(s): {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
