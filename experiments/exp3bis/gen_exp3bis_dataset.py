#!/usr/bin/env python
"""Experiment 3 bis: the same phenotype-evidence target, dosed like a scanner.

**Why there is a bis.** Experiment 3 ran two operators at rate 1.00 against one
phenotype's evidence set. `input.typo` is dosed per WORD, so a saturating rate
means one interior character per eligible word — a misprint, at any severity.
`input.ocr_confusion` is dosed per CHARACTER, so the same rate means *every*
confusable position in a token at once. Measured over 120 notes, exp3's OCR arm
changed a median of six characters per word, 65% of the word, and pushed 82% of
corrupted words past half their characters: `Hypertension` came back as
`Hvpcrfousj0h` and `Obesity` as `06osjlv`. That is the term deleted and replaced
with same-length noise — a redaction wearing the operator's name — and it was
reported as noise robustness.

**What this generates.** One arm, `ocr_capped_<phenotype>`, identical to exp3's
OCR arm except for `max_edits_per_token: 1`. At rate 1.00 that is exactly one
misread per eligible token, which is what `input.typo` at rate 1.00 already
does — so for the first time the two operators are dose-matched and the
comparison between them means something. The realistic typo arms are NOT
regenerated: they already pass the realism gate and their predictions exist.

**What this fixes on the way.** Experiment 3 kept only the corrupted text and
threw away every `DoseRecord` and `Edit`, so its corpora could not be replayed,
verified against a hash, or asked where the edits landed. This writes the edit
script, the dose ledger and the concept impact, as exp1 and exp2 always did.

Every manifest carries the **realism gate** — the measurement that caught the
original problem — so an arm that stops being a misreading says so in its own
provenance rather than in someone's re-analysis:

    median characters changed per corrupted token   must be 1
    share of corrupted tokens changed in one place  must be >= 0.95
    share of corrupted tokens losing over half      must be 0

Layout follows `mipa_corpora.discover`, as exp3 does:

    data/experiments/exp3bis/ocr_capped_<phenotype>/full/notes.csv
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

ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: exp3's OCR arm, with the per-token cap that makes it a misreading again.
#: The name says what it is rather than which glyph table it uses: the whole
#: point of the arm is the bound, not the confusion set.
ARM = ("ocr_capped", "input.ocr_confusion", {"mode": "glyph", "max_edits_per_token": 1})

SEVERITY_LITERAL = "1.00"
SEVERITY_DIR = "full"

#: An arm may carry a noise-robustness claim only if it clears all three.
GATE_MEDIAN_CHARS = 1
GATE_MIN_SINGLE_CHAR = 0.95
GATE_MAX_OVER_HALF = 0.0


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def token_damage(doc: Document, edits: list) -> list[tuple[int, int]]:
    """Per corrupted token: (characters changed, token length).

    Grouped by the token an edit falls inside rather than by the edit, because
    the question the gate asks is what a *word* looks like afterwards. An edit
    landing outside every token is ignored; OCR eligibility confines them to
    token interiors, so that set is empty and stays a guard rather than a filter.
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


def report(conditions: list[tuple[str, str]], doses: dict, damage: dict) -> list[str]:
    """Print the per-condition summary; return the conditions that failed the gate."""
    width = max(len(c) for c, _ in conditions)
    print(f"{'condition':<{width}} {'notes':>6} {'edited':>7} {'edits':>7} {'gate':>9}")
    failures = []
    for cname, _ in conditions:
        rows = doses[cname]
        edited = sum(1 for d in rows if d.applied_n > 0)
        total = sum(d.applied_n for d in rows)
        verdict = gate(damage[cname])["verdict"]
        if verdict != "noise":
            failures.append(cname)
        print(f"{cname:<{width}} {len(rows):>6} {edited:>7} {total:>7} {verdict:>9}")
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
    parser.add_argument("--out", type=Path, default=Path("data/experiments/exp3bis"))
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

    digests = {
        "phenotype_vetting.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_vetting.yaml"),
        "phenotype_closure.yaml": sha16(ROBUSTEHR_RESOURCES / "phenotype_closure.yaml"),
        "umls_facets.json": sha16(Path("data/umls_facets.json")),
    }

    arm_name, op_id, params = ARM
    op = registry.get(op_id)()
    sev = parse_severity(SEVERITY_LITERAL)
    conditions = [(f"{arm_name}_{p.name}", p.name) for p in phenotypes]

    writers: dict[str, object] = {}
    handles = []
    doses: dict[str, list] = {c: [] for c, _ in conditions}
    edit_groups: dict[str, list] = {c: [] for c, _ in conditions}
    impacts: dict[str, list] = {c: [] for c, _ in conditions}
    damage: dict[str, list] = {c: [] for c, _ in conditions}
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
        for cname, pheno_name in conditions:
            result = apply_operator(
                doc,
                op,
                op.meta,
                sev,
                scope=Scope(target=PhenotypeEvidence(pheno_name)),
                params=params,
                salt=args.salt,
                run_id=f"exp3bis.{cname}.{SEVERITY_DIR}",
                mentions=mentions,
                phenotypes=idx,
            )
            applied = result.apply_result.applied
            writers[cname].writerow([hadm_id, note_id, result.text])
            doses[cname].append(result.dose)
            edit_groups[cname].append(applied)
            damage[cname].extend(token_damage(doc, list(applied)))
            impacts[cname].append(concept_impact(note_id, mentions, applied))
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} notes", file=sys.stderr)
    for handle in handles:
        handle.close()

    for cname, pheno_name in conditions:
        directory = args.out / cname / SEVERITY_DIR
        realism = gate(damage[cname])
        write_run(
            directory,
            run_id=f"exp3bis.{cname}.{SEVERITY_DIR}",
            doses=doses[cname],
            edits=edit_groups[cname],
            corpus="corpus",
            # With the notes, each replacement is stored as its minimal difference
            # (one offset and one letter for a typo) instead of the retyped word.
            texts=clean_texts,
            extra={
                "experiment": "exp3bis",
                "corruption": cname,
                "phenotype": pheno_name,
                "operator": op_id,
                "params": params,
                "severity": SEVERITY_LITERAL,
                "severity_dir": SEVERITY_DIR,
                "salt": args.salt,
                "target": f"pheno={pheno_name}",
                "design": (
                    "exp3's OCR arm with max_edits_per_token=1: every span whose "
                    "mention CUI is in this phenotype's closed, vetting-gated set "
                    "is treated, but a token loses at most one character. Dose-"
                    "matched to exp3's typo arm, which at rate 1.00 also makes one "
                    "edit per eligible unit. No baseline arm (the baseline corpus "
                    "and predictions already exist) and no severity ladder."
                ),
                "realism_gate": realism,
                "contains_note_text": True,
                "set_digests": digests,
                "generated_by": "experiments/exp3bis/gen_exp3bis_dataset.py",
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

    failures = report(conditions, doses, damage)
    if skipped:
        print(f"skipped {skipped} sample notes with no text or cache entry", file=sys.stderr)

    summary = {
        "experiment": "exp3bis",
        "conditions": [c for c, _ in conditions],
        "sample": str(args.sample),
        "notes_per_condition": len(sample) - skipped,
        "set_digests": digests,
        "generated_by": "experiments/exp3bis/gen_exp3bis_dataset.py",
    }
    (args.out / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out} ({len(conditions)} conditions)")
    if failures:
        print(
            f"REALISM GATE FAILED for {len(failures)} condition(s): {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
