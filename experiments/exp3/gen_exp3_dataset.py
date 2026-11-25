#!/usr/bin/env python
"""The experiment-3 corpora: one phenotype's evidence, fully corrupted.

**Design (docs/exp_3_hypothesis.md).** Experiment 3 asks whether corrupting a
phenotype's concepts changes the phenotyping call. Its treatment differs from
exp2 in three deliberate ways:

* **Per-phenotype targets.** Each condition corrupts only spans whose mention
  CUI falls in ONE phenotype's closed, vetting-gated set — the real
  `pheno=<name>` target, canon and all — for each of the 15 MIPA-cohort
  phenotypes.
* **Binary dose, not a ladder.** A note carries a handful of eligible spans
  per phenotype (typically 1–50), so a severity ladder has nothing to
  resolve: the causal probe measured exp2's medium rung flipping nothing
  anywhere. Every condition runs at rate 1.00 — every eligible span treated —
  and the severity directory is named `full`.
* **No baseline arm.** The baseline corpus and its predictions already exist;
  deltas are computed against them.

Two operators, exactly exp2's: `typographical_errors` (`input.typo`) and
`homoglyph_substitutions` (`input.ocr_confusion`, glyph mode). 15 phenotypes
× 2 operators = 30 conditions over the 500-note evaluated sample (only
sampled notes are generated: the runner never reads the rest, and 30 full
corpora would be pure disk).

Layout follows `mipa_corpora.discover`:

    data/experiments/exp3/<operator>_<phenotype>/full/notes.csv  (+ manifest.json)

Mentions come from the clean-note cache (no QuickUMLS at generation time);
seeds derive from salt, note uid, operator and the true target canon, so a
regeneration is byte-identical. Manifests carry the vetting and closure file
digests per validation-protocol §10 — a `pheno=` treatment is only as good as
the set behind it, and these are the sets' fingerprints.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import warnings
from importlib.resources import files
from pathlib import Path

from robustehr.concepts import hierarchy
from robustehr.concepts.cache import MentionCache
from robustehr.concepts.phenotype import build, in_cohort, index_document, load_maps
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, parse_severity
from robustehr.target import PhenotypeEvidence

#: RobustEHR's packaged resources, located through the installed `robustehr`
#: package rather than through `src/robustehr/resources/...`. This repository is
#: independent of RobustEHR's checkout layout, and the relative path only ever
#: resolved when the process happened to be running from inside that source tree.
ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

#: exp2's operators, verbatim from experiments/exp1_exp2/run_experiments.py.
OPERATORS = (
    ("typographical_errors", "input.typo", {}),
    ("homoglyph_substitutions", "input.ocr_confusion", {"mode": "glyph"}),
)

SEVERITY_LITERAL = "1.00"
SEVERITY_DIR = "full"


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


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
    parser.add_argument("--out", type=Path, default=Path("data/experiments/exp3"))
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

    ops = {op_id: registry.get(op_id)() for _, op_id, _ in OPERATORS}
    sev = parse_severity(SEVERITY_LITERAL)

    conditions = [
        (f"{op_name}_{pheno.name}", op_name, op_id, params, pheno.name)
        for op_name, op_id, params in OPERATORS
        for pheno in phenotypes
    ]
    writers: dict[str, csv.writer] = {}
    handles = []
    stats = {c[0]: {"notes": 0, "edited": 0, "edits": 0, "max": 0} for c in conditions}
    for cname, *_ in conditions:
        path = args.out / cname / SEVERITY_DIR / "notes.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8")
        handles.append(handle)
        writer = csv.writer(handle)
        writer.writerow(["hadm_id", "note_id", "note_corrupted"])
        writers[cname] = writer

    skipped = 0
    for i, (hadm_id, note_id) in enumerate(sample, 1):
        text = text_by_note.get(note_id)
        if text is None:
            skipped += 1
            continue
        doc = Document.from_text(text, uid=note_id)
        mentions = mention_cache.get(doc)
        if mentions is None:
            skipped += 1
            continue
        idx = index_document(mentions, phenotypes)
        for cname, _op_name, op_id, params, pheno_name in conditions:
            op = ops[op_id]
            result = apply_operator(
                doc,
                op,
                op.meta,
                sev,
                scope=Scope(target=PhenotypeEvidence(pheno_name)),
                params=params,
                salt=args.salt,
                mentions=mentions,
                phenotypes=idx,
            )
            writers[cname].writerow([hadm_id, note_id, result.text])
            s = stats[cname]
            s["notes"] += 1
            s["edited"] += result.dose.applied_n > 0
            s["edits"] += result.dose.applied_n
            s["max"] = max(s["max"], result.dose.applied_n)
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} notes", file=sys.stderr)
    for handle in handles:
        handle.close()

    for cname, op_name, op_id, params, pheno_name in conditions:
        s = stats[cname]
        manifest = {
            "experiment": "exp3",
            "corruption": cname,
            "phenotype": pheno_name,
            "operator": op_id,
            "params": params,
            "severity": SEVERITY_LITERAL,
            "severity_dir": SEVERITY_DIR,
            "salt": args.salt,
            "target": f"pheno={pheno_name}",
            "design": (
                "binary full-dose: every span whose mention CUI is in this "
                "phenotype's closed, vetting-gated set is treated. No severity "
                "ladder (eligible spans are few) and no baseline arm (the "
                "baseline corpus and predictions already exist)."
            ),
            "notes": s["notes"],
            "notes_with_edits": s["edited"],
            "edits": s["edits"],
            "max_edits_per_note": s["max"],
            "contains_note_text": True,
            "set_digests": digests,
            "generated_by": "experiments/exp3/gen_exp3_dataset.py",
        }
        (args.out / cname / SEVERITY_DIR / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    width = max(len(c[0]) for c in conditions)
    print(f"{'condition':<{width}} {'notes':>6} {'edited':>7} {'edits':>7} {'max':>5}")
    for cname, *_ in conditions:
        s = stats[cname]
        print(f"{cname:<{width}} {s['notes']:>6} {s['edited']:>7} {s['edits']:>7} {s['max']:>5}")
    if skipped:
        print(f"skipped {skipped} sample notes with no text or cache entry", file=sys.stderr)
    summary = {
        "experiment": "exp3",
        "conditions": [c[0] for c in conditions],
        "sample": str(args.sample),
        "notes_per_condition": len(sample) - skipped,
        "set_digests": digests,
        "generated_by": "experiments/exp3/gen_exp3_dataset.py",
    }
    (args.out / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out} ({len(conditions)} conditions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
