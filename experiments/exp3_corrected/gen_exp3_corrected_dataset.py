#!/usr/bin/env python
"""Experiment 3 corrected: the same aim, at a target that reaches the diagnosis.

**What exp3 and exp3bis got wrong, and it is not the dose.** exp3bis fixed the
dose: capping the OCR operator at one misread per token turned an ablation back
into noise, and the two operators became comparable. What neither fixed is what
the arms were aimed AT. `pheno=X` resolved through concept-set membership alone,
so a span was evidence only if the matcher grounded it to a CUI the closure had
admitted — and a closure built by walking a disorder hierarchy cannot reach the
causative organism, cannot reach the qualifying adjective, and never sees an
abbreviation the matcher produced no candidate for.

Measured against an independently authored clinical lexicon on the same 500
notes, barely half of every written diagnosis term was ever eligible for
corruption, and the per-phenotype share the target could reach ran from 7% to
99%. An arm reporting "this phenotype resisted corruption" over that range was
not describing the phenotype. It was describing the ontology.

**What changed underneath.** RobustEHR now admits evidence on two warrants:
concept-set membership as before, and a declared surface form matched literally
against the text. It also refuses matched surfaces that are ordinary English in
the wrong sense, and drops concepts that span too many unrelated phenotypes to
discriminate. So `pheno=X` now means roughly what the experiment always claimed
it meant, and the resource digests in every manifest say which version of that
claim a corpus was built under.

**What this generates.** Both operators, the way exp3bis established they should
be dosed: `typographical_errors` and `ocr_capped`, 15 phenotypes, 30 conditions.
exp3's uncapped OCR arm is not regenerated — exp3bis retired it as an ablation,
and re-running it here would reintroduce the confound this experiment exists to
remove.

**Two gates, and both exit non-zero.** The realism gate of exp3bis is kept
unchanged. The reach gate is new, and it is the one this experiment needs:

    the target declared the diagnosis as evidence at all           diagnosis_n > 0
    the corruption reached most of what was written                diagnosis_reach >= 0.50

An arm failing the second has not tested its phenotype, and reporting it as
robust is the error the whole correction is for. It fails loudly at generation
rather than quietly in someone's re-analysis.

Layout follows `mipa_corpora.discover`, as exp3 and exp3bis do::

    data/experiments/exp3_corrected/<operator>_<phenotype>/full/notes.csv

Run it from the populated data checkout, because the facet and cache paths are
relative::

    cd _withdata/_RobustEHR_withdata
    python ../../mipa-corrupt/experiments/exp3_corrected/gen_exp3_corrected_dataset.py \\
        --out data/experiments/exp3_corrected
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import statistics
import sys
import warnings
from collections import defaultdict
from importlib.resources import files
from pathlib import Path

from robustehr.concepts import hierarchy
from robustehr.concepts.cache import MentionCache
from robustehr.concepts.phenotype import build, in_cohort, index_document, load_maps
from robustehr.document import Document
from robustehr.metrics.impact import aggregate, concept_impact
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, parse_severity
from robustehr.store import write_run
from robustehr.target import PhenotypeEvidence
from robustehr.types import Span

ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: Both operators, each dosed to one edit per eligible unit.
#:
#: `input.typo` at rate 1.00 already does that by construction. `ocr_confusion`
#: needs the cap exp3bis added, without which the same rate substitutes every
#: confusable position in the token at once. With both capped the operators
#: differ only in WHICH character moves and how — keyboard adjacency against
#: glyph shape — which is the comparison the paper wants and exp3 could not make.
#: `include_mixed` is what makes the comparison honest.
#:
#: `input.typo` admits only alphabetic tokens by default, and `DM2`, `T2DM` and
#: `A1c` tokenize as MIXED. Aimed at type 2 diabetes it therefore reached 132 of
#: 252 declared diagnosis spans where the glyph operator reached 247 — missing
#: `DM2` 25 times and `T2DM` 8 while editing every spelled-out form. Two
#: operators that cannot treat the same tokens are not dose-matched, whatever
#: their edit counts say, and this experiment exists to compare them.
#:
#: Off by default in the operator, so exp1, exp2, exp3 and exp3bis are
#: untouched and need no re-run.
ARMS = (
    ("typographical_errors", "input.typo", {"include_mixed": True}),
    ("ocr_capped", "input.ocr_confusion", {"mode": "glyph", "max_edits_per_token": 1}),
)

SEVERITY_LITERAL = "1.00"
SEVERITY_DIR = "full"

#: An arm may carry a noise-robustness claim only if it clears all three.
GATE_MEDIAN_CHARS = 1
GATE_MIN_SINGLE_CHAR = 0.95
GATE_MAX_OVER_HALF = 0.0

#: Share of the declared diagnosis an arm must actually treat.
#:
#: **Half, not ninety percent, and the first draft of this gate had it wrong.**
#: Reach is two questions and only one of them is about the aim:
#:
#: 1. did the TARGET declare the phenotype's diagnosis as evidence? That is what
#:    this correction changed, and it is gated absolutely — `diagnosis_declared`
#:    must be non-zero or the arm has not tested its phenotype at all.
#: 2. could the OPERATOR then edit what was declared? That is a property of the
#:    operator and the words, not of the aim. `ocr_confusion` needs a confusable
#:    glyph, and short clinical abbreviations frequently have none: measured on
#:    hypertension it treated 30 of 53 declared diagnosis spans where `typo`
#:    treated all 53. Failing the arm for that would report an operator
#:    limitation as a targeting failure, which is the same category error in the
#:    opposite direction.
#:
#: So the threshold is set where an arm stops being a test rather than where it
#: stops being tidy. Below half the diagnosis touched, a null result says
#: nothing about the phenotype; above it, the shortfall is reported beside the
#: estimate and belongs in the operator's own limitations.
GATE_MIN_DIAGNOSIS_REACH = 0.50

#: Tiers that carry the diagnosis itself, as against concepts associated with it.
#:
#: Both, because the two warrants are alternatives rather than a hierarchy. Where
#: the closure already covers a phenotype's diagnosis the matcher grounds it and
#: the span arrives as `disorder`; the anchor layer then suppresses its own
#: overlapping span so one piece of evidence is counted once. Hypertension over
#: twenty notes declares 53 disorder spans and 1 anchor span for exactly that
#: reason — its closure was never the broken one. Counting anchors alone would
#: make a well-covered phenotype look unreached.
DIAGNOSIS_TIERS = ("anchor", "disorder")


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def sha16_optional(path: Path) -> str:
    """Digest, or `absent` — which is itself a fact worth recording.

    A corpus built before the anchor resource existed is a different treatment
    from one built after it, and `absent` is what says so.
    """
    return sha16(path) if path.exists() else "absent"


def sha16_targeting(path: Path) -> str:
    """Digest of what a resource TARGETS, ignoring how it was built.

    A whole-file digest answers "is this the same bytes", which is not the
    question a manifest is asking. It is asking "was this corpus built against
    the same target", and a resource carries provenance metadata that has no
    effect on targeting: a ledger of which pass added what, who vetted it, a
    licence note. Correcting a mistake in that metadata changes the file hash
    and silently invalidates every corpus that used it, although not one edit
    would land differently.

    That happened. On 2026-09-23 the anchor resource's `passes` ledger was
    deduplicated and renumbered and `vetted_by` was corrected; the file digest
    moved from 98f93f8d4ef20ae9 to ca95c0d2837e44ab while the phenotype blocks
    stayed byte-identical at 9580e70108b3ce06. The manifests recorded the file
    digest, so they appeared to describe a target that no longer shipped.

    Both are recorded now. The file digest still answers reproducibility of the
    artifact; this one answers equivalence of the treatment.
    """
    if not path.exists():
        return "absent"
    import yaml

    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    blocks = doc.get("phenotypes", doc)
    canonical = json.dumps(blocks, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def token_damage(doc: Document, edits: list) -> list[tuple[int, int]]:
    """Per corrupted token: (characters changed, token length).

    Grouped by the token an edit falls inside rather than by the edit, because
    the question the gate asks is what a *word* looks like afterwards.
    """
    starts = [t.span.start for t in doc.tokens]
    hits: dict[int, int] = defaultdict(int)
    for edit in edits:
        i = bisect.bisect_right(starts, edit.start) - 1
        if i < 0:
            continue
        token = doc.tokens[i]
        if edit.start < token.span.end:
            hits[i] += 1
    return [(n, len(doc.tokens[i].span)) for i, n in hits.items()]


def gate(damage: list[tuple[int, int]]) -> dict[str, object]:
    """The realism measurement, and whether this arm passes it."""
    if not damage:
        return {"corrupted_tokens": 0, "verdict": "no edits"}
    changed = [n for n, _ in damage]
    median = statistics.median(changed)
    single = sum(1 for n in changed if n == 1) / len(changed)
    over_half = sum(1 for n, length in damage if n * 2 > length) / len(damage)
    passed = (
        median == GATE_MEDIAN_CHARS
        and single >= GATE_MIN_SINGLE_CHAR
        and over_half <= GATE_MAX_OVER_HALF
    )
    return {
        "corrupted_tokens": len(damage),
        "median_chars_changed": median,
        "mean_share_of_token": round(sum(n / length for n, length in damage) / len(damage), 4),
        "share_single_char": round(single, 4),
        "share_over_half_the_token": round(over_half, 4),
        "verdict": "noise" if passed else "ablation",
    }


def reach_gate(declared: dict[str, int], touched: dict[str, int]) -> dict[str, object]:
    """Did this arm reach the phenotype's written diagnosis?

    Reported per tier, because "we corrupted this phenotype's evidence" is only
    a meaningful sentence once it says WHICH evidence. The verdict turns on the
    anchor tier alone: the other tiers are supporting concepts, and an arm that
    flattened every symptom in the note while leaving the diagnosis intact has
    not tested whether the model reads the diagnosis.
    """
    diagnosis_n = sum(declared.get(t, 0) for t in DIAGNOSIS_TIERS)
    diagnosis_touch = sum(touched.get(t, 0) for t in DIAGNOSIS_TIERS)
    common = {
        "anchor_n": declared.get("anchor", 0),
        "anchor_touch": touched.get("anchor", 0),
        "diagnosis_n": diagnosis_n,
        "diagnosis_touch": diagnosis_touch,
        "declared_by_tier": declared,
        "touched_by_tier": touched,
    }
    if diagnosis_n == 0:
        return {
            **common,
            "diagnosis_reach": None,
            "verdict": "not aimed",
            "why": "the target declared no diagnosis evidence anywhere in the corpus",
        }
    reach = diagnosis_touch / diagnosis_n
    aimed = reach >= GATE_MIN_DIAGNOSIS_REACH
    return {
        **common,
        "diagnosis_reach": round(reach, 4),
        "verdict": "aimed" if aimed else "not aimed",
        "why": (
            ""
            if aimed
            else f"the operator treated {diagnosis_touch} of {diagnosis_n} declared "
            "diagnosis spans; below half, a null result says nothing about the phenotype"
        ),
    }


def report(conditions: list[tuple[str, str, str, dict]], doses: dict, damage: dict, reach: dict):
    """Print the per-condition summary; return the conditions that failed a gate."""
    width = max(len(c) for c, *_ in conditions)
    header = f"{'condition':<{width}} {'notes':>6} {'edited':>7} {'edits':>7}"
    print(f"{header} {'realism':>9} {'reach':>7} {'aimed':>10}")
    failures = []
    for cname, *_ in conditions:
        rows = doses[cname]
        edited = sum(1 for d in rows if d.applied_n > 0)
        total = sum(d.applied_n for d in rows)
        realism = gate(damage[cname])["verdict"]
        aim = reach[cname]
        pct = "-" if aim["diagnosis_reach"] is None else f"{aim['diagnosis_reach']:.2f}"
        if realism != "noise" or aim["verdict"] != "aimed":
            failures.append(cname)
        line = f"{cname:<{width}} {len(rows):>6} {edited:>7} {total:>7}"
        print(f"{line} {realism:>9} {pct:>7} {aim['verdict']:>10}")
    return failures


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912, PLR0915 - one block per stage
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
    parser.add_argument("--out", type=Path, default=Path("data/experiments/exp3_corrected"))
    parser.add_argument(
        "--allow-unaimed",
        action="store_true",
        help="write the corpora even when an arm fails the reach gate. For "
        "diagnosing a bad anchor set, never for generating a corpus a claim "
        "will rest on",
    )
    args = parser.parse_args(argv)

    registry.register_builtins()
    csv.field_size_limit(1_000_000_000)
    with args.notes.open(newline="", encoding="utf-8") as handle:
        text_by_note = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    with args.sample.open(newline="", encoding="utf-8") as handle:
        sample = [(r["hadm_id"], r["note_id"]) for r in csv.DictReader(handle)]

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = list(args.phenotype or in_cohort("mipa"))
    phenotypes = build(sorted(names), isa, code_to_cuis, cui_to_codes)
    mention_cache = MentionCache(root=args.cache, config_digest=args.cache_digest)

    unanchored = [p.name for p in phenotypes if p.anchors is None or not p.anchors.declared]
    if unanchored:
        print(
            f"WARNING: no surface anchors declared for {', '.join(unanchored)}.\n"
            "Those arms fall back to concept-set membership alone — which is exactly "
            "the aim this experiment exists to correct — and will fail the reach gate.\n"
            "Build the resource first: validation/phenotype/scripts/phenotype_anchors.py",
            file=sys.stderr,
        )

    # The anchor digest joins the two that exp3 already recorded. Between them
    # they fingerprint the treatment: a corpus built under different digests is
    # a different experiment, and saying so is what keeps exp3, exp3bis and this
    # comparable rather than conflated.
    digests = {
        "phenotype_vetting.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_vetting.yaml"),
        "phenotype_closure.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_closure.yaml"),
        "phenotype_anchors.yaml": sha16_optional(ROBUSTEHR_RESOURCES / "phenotype_anchors.yaml"),
        # what the anchors TARGET, independent of the provenance ledger beside
        # them -- see sha16_targeting for why the file digest is not enough
        "phenotype_anchors.targeting": sha16_targeting(
            ROBUSTEHR_RESOURCES / "phenotype_anchors.yaml"
        ),
        "phenotype_nonspecific.yaml": sha16_optional(
            ROBUSTEHR_RESOURCES / "phenotype_nonspecific.yaml"
        ),
        "umls_facets.json": sha16(Path("data/umls_facets.json")),
    }

    sev = parse_severity(SEVERITY_LITERAL)
    operators = {arm: registry.get(op_id)() for arm, op_id, _ in ARMS}
    conditions = [
        (f"{arm}_{p.name}", p.name, arm, op_id, params)
        for arm, op_id, params in ARMS
        for p in phenotypes
    ]

    writers: dict[str, object] = {}
    handles = []
    doses: dict[str, list] = {c: [] for c, *_ in conditions}
    edit_groups: dict[str, list] = {c: [] for c, *_ in conditions}
    impacts: dict[str, list] = {c: [] for c, *_ in conditions}
    damage: dict[str, list] = {c: [] for c, *_ in conditions}
    declared: dict[str, dict] = {c: defaultdict(int) for c, *_ in conditions}
    touched: dict[str, dict] = {c: defaultdict(int) for c, *_ in conditions}
    for cname, *_ in conditions:
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
        # `text=` is the whole correction: it turns on the surface warrant, so a
        # written diagnosis becomes evidence whether or not the closure ever
        # reached a CUI for it.
        idx = index_document(mentions, phenotypes, text=text)
        for cname, pheno_name, arm, _op_id, params in conditions:
            op = operators[arm]
            result = apply_operator(
                doc,
                op,
                op.meta,
                sev,
                scope=Scope(target=PhenotypeEvidence(pheno_name)),
                params=params,
                salt=args.salt,
                run_id=f"exp3_corrected.{cname}.{SEVERITY_DIR}",
                mentions=mentions,
                phenotypes=idx,
            )
            applied = result.apply_result.applied
            writers[cname].writerow([hadm_id, note_id, result.text])
            doses[cname].append(result.dose)
            edit_groups[cname].append(applied)
            damage[cname].extend(token_damage(doc, list(applied)))
            impacts[cname].append(concept_impact(note_id, mentions, applied))
            edited = [Span(start=e.start, end=e.end) for e in applied if e.end > e.start]
            for tier, n in idx.declared_by_tier(pheno_name).items():
                declared[cname][tier] += n
            for tier, n in idx.touched_by_tier(edited, pheno_name).items():
                touched[cname][tier] += n
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} notes", file=sys.stderr)
    for handle in handles:
        handle.close()

    reach = {
        cname: reach_gate(dict(declared[cname]), dict(touched[cname])) for cname, *_ in conditions
    }

    for cname, pheno_name, _arm, op_id, params in conditions:
        directory = args.out / cname / SEVERITY_DIR
        write_run(
            directory,
            run_id=f"exp3_corrected.{cname}.{SEVERITY_DIR}",
            doses=doses[cname],
            edits=edit_groups[cname],
            corpus="corpus",
            # With the notes, each replacement is stored as its minimal difference
            # (one offset and one letter for a typo) instead of the retyped word.
            texts=clean_texts,
            extra={
                "experiment": "exp3_corrected",
                "corruption": cname,
                "phenotype": pheno_name,
                "operator": op_id,
                "params": params,
                "severity": SEVERITY_LITERAL,
                "severity_dir": SEVERITY_DIR,
                "salt": args.salt,
                "target": f"pheno={pheno_name}",
                "design": (
                    "exp3bis's dose with exp3's two operators, against a target "
                    "that admits evidence on two warrants: concept-set membership "
                    "as before, and a declared surface form matched literally "
                    "against the text. Both operators make one edit per eligible "
                    "unit, so they are dose-matched and differ only in which "
                    "character moves. No baseline arm and no severity ladder; the "
                    "baseline corpus and predictions already exist."
                ),
                "realism_gate": gate(damage[cname]),
                "reach_gate": reach[cname],
                "contains_note_text": True,
                "set_digests": digests,
                "generated_by": "experiments/exp3_corrected/gen_exp3_corrected_dataset.py",
            },
        )
        if impacts[cname]:
            (directory / "concept_impact.json").write_text(
                json.dumps(
                    {
                        "what": (
                            "which UMLS concepts this condition's edits landed on, "
                            "derived from the CLEAN tagging and the edit script"
                        ),
                        "caveat": (
                            "touched is not lost: a mistyped concept may still match, "
                            "and a corruption can create a match."
                        ),
                        **aggregate(impacts[cname]),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    failures = report(conditions, doses, damage, reach)
    if skipped:
        print(f"skipped {skipped} sample notes with no text or cache entry", file=sys.stderr)

    summary = {
        "experiment": "exp3_corrected",
        "conditions": [c for c, *_ in conditions],
        "sample": str(args.sample),
        "notes_per_condition": len(sample) - skipped,
        "set_digests": digests,
        "gates": {
            "realism": {
                "median_chars_changed": GATE_MEDIAN_CHARS,
                "min_share_single_char": GATE_MIN_SINGLE_CHAR,
                "max_share_over_half": GATE_MAX_OVER_HALF,
            },
            "reach": {
                "min_diagnosis_reach": GATE_MIN_DIAGNOSIS_REACH,
                "diagnosis_tiers": list(DIAGNOSIS_TIERS),
            },
        },
        "diagnosis_reach": {c: reach[c]["diagnosis_reach"] for c, *_ in conditions},
        "anchor_n": {c: reach[c]["anchor_n"] for c, *_ in conditions},
        "failed_gates": failures,
        "generated_by": "experiments/exp3_corrected/gen_exp3_corrected_dataset.py",
    }
    (args.out / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out} ({len(conditions)} conditions)")
    if failures:
        print(
            f"\nGATE FAILED for {len(failures)} condition(s): {', '.join(failures)}\n"
            "An arm that failed the reach gate has not tested its phenotype, and "
            "reporting it as robust is the error this experiment exists to correct.",
            file=sys.stderr,
        )
        return 0 if args.allow_unaimed else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
