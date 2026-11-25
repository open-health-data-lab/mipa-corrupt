#!/usr/bin/env python
"""Per-phenotype concept lists for the paper appendix, in two licence tiers.

**Why two.** The UMLS Metathesaurus licence does not permit redistributing
vocabulary content, which is why every artifact in this repository carries
identifiers and `surface_sha256` rather than strings. A paper appendix wants
readable terms. Both are produced, and which one you publish is a licence
decision only the licence holder can make:

* ``docs/appendix/concepts/<phenotype>.csv`` — **identifiers only**, safe to
  ship in the repository and to publish anywhere: CUI, how it entered the set,
  its category, its vetting verdict, and whether the corpus writes it. A
  reader with any UMLS release can resolve the CUIs themselves.
* ``data/appendix/concepts_with_terms/<phenotype>.csv`` — the same rows plus
  the English preferred term. Gitignored, refuses to write outside ``data/``
  (the same guard RobustEHR's `validation/phenotype/scripts/phenotype_export_review.py`
  uses). Publish only if
  your licence and journal permit; the identifier column is what makes the
  table reproducible either way.

**Columns, and why each is there.** A reviewer's question about a concept set
is never "what is in it" alone — it is "how did this get in, who judged it,
and does it matter in the corpus". So every row carries its own provenance:

    facet        disorder | medication | finding | proposed | closure
    provenance   seed | closure | lift | identity | declared | grounded
    vetted       keep | drop-not-shipped | auto (curated source, unreviewed)
    category     the shipped exclusive partition (disease, medication, ...)
    in_corpus    1 if any of the 1,388 notes writes it; mentions counts them
    in_sample    1 if any of the 500 evaluated notes writes it

Rows are the SHIPPED set — what a `pheno=` target actually selects — so the
appendix and the experiments describe the same object.
"""

from __future__ import annotations

import argparse
import csv
import json
import warnings
from collections import Counter
from importlib.resources import files
from pathlib import Path
from typing import Any

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, in_cohort, load_definitions, load_maps
from robustehr.rng import sha256_text

#: RobustEHR's packaged resources, located through the installed `robustehr`
#: package rather than through `src/robustehr/resources/...`. This repository is
#: independent of RobustEHR's checkout layout, and the relative path only ever
#: resolved when the process happened to be running from inside that source tree.
ROBUSTEHR_RESOURCES = Path(str(files("robustehr.resources")))

COLUMNS = [
    "phenotype", "cui", "facet", "provenance", "vetted", "category",
    "in_corpus", "corpus_mentions", "in_sample", "sample_mentions",
]
EXCLUSIVE = [
    "disease", "finding", "symptom", "medication",
    "anatomy", "procedure", "lab_result", "device",
]


def load_semantic_types(mrsty: Path, wanted: frozenset[str]) -> dict[str, frozenset[str]]:
    types: dict[str, set[str]] = {}
    with mrsty.open(encoding="utf-8") as handle:
        for line in handle:
            cui, tui = line.split("|", 2)[:2]
            if cui in wanted:
                types.setdefault(cui, set()).add(tui)
    return {c: frozenset(t) for c, t in types.items()}


def preferred_terms(mrconso: Path, wanted: frozenset[str]) -> dict[str, str]:
    """One English preferred term per CUI. Licensed content — data/ only."""
    best: dict[str, tuple[int, str, str]] = {}
    with mrconso.open(encoding="utf-8") as handle:
        for line in handle:
            row = line.split("|")
            cui = row[0]
            if cui not in wanted or row[1] != "ENG":
                continue
            text = row[14].strip()
            if not text:
                continue
            # Preferred current atom first, any current atom next, and a
            # suppressed (obsolete) atom last: about 4,000 RxNorm product
            # identifiers in the medication facets have only obsolete English
            # names, and a blank term would hide a real member of the set.
            if row[16] != "N":
                rank = 2
            elif row[2] == "P" and row[4] == "PF" and row[6] == "Y":
                rank = 0
            else:
                rank = 1
            key = (rank, row[5], text)
            if cui not in best or key < best[cui]:
                best[cui] = key
    return {c: v[2] for c, v in best.items()}


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--mrsty", type=Path, default=Path("data/umls/2026AA/META/MRSTY.RRF"))
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--cache-digest", default="6e56a7c3a64d53ff")
    parser.add_argument("--out", type=Path, default=Path("docs/appendix/concepts"))
    parser.add_argument(
        "--terms-out", type=Path, default=Path("data/appendix/concepts_with_terms")
    )
    parser.add_argument(
        "--carry-from",
        type=Path,
        default=None,
        help="a previous with-terms export: when the UMLS release is not on this machine, "
        "preferred terms and categories are carried over from it by CUI (both are stable "
        "across a release), and a concept that export did not contain is marked unresolved",
    )
    parser.add_argument(
        "--all-phenotypes",
        action="store_true",
        help="all 22 declared, not just the 15 MIPA-cohort ones the paper uses",
    )
    args = parser.parse_args(argv)

    # Same guard as the review export: licensed strings never leave data/.
    resolved = args.terms_out.resolve()
    if Path("data").resolve() not in resolved.parents:
        print(f"refusing to write UMLS terms to {args.terms_out}: must stay under data/")
        return 2

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    definitions = load_definitions()
    names = sorted(definitions) if args.all_phenotypes else sorted(in_cohort("mipa"))
    built = {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}
    import yaml

    vetting_raw = (
        yaml.safe_load((ROBUSTEHR_RESOURCES / "phenotype_vetting.yaml").read_text("utf-8"))
        or {}
    ).get("phenotypes", {})
    vetting = facets.load_vetting()
    proposals = facets.load_proposals()
    closure_kept = facets.load_closure()
    edges = facets.load()

    # Corpus and sample mention counts, from the cache. No re-tagging.
    csv.field_size_limit(1_000_000_000)
    with args.notes.open(newline="", encoding="utf-8") as handle:
        texts = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    with args.sample.open(newline="", encoding="utf-8") as handle:
        sample_ids = {r["note_id"] for r in csv.DictReader(handle)}
    cache = args.cache / args.cache_digest
    corpus_counts: Counter[str] = Counter()
    sample_counts: Counter[str] = Counter()
    for uid, text in texts.items():
        sha = sha256_text(text)
        path = cache / sha[:2] / f"{sha}.json"
        if not path.exists():
            continue
        counts = Counter(m[2] for m in json.loads(path.read_text("utf-8"))["mentions"])
        corpus_counts.update(counts)
        if uid in sample_ids:
            sample_counts.update(counts)

    union = frozenset(c for p in built.values() for c in p.concept_cuis)
    carried_terms: dict[str, str] = {}
    carried_categories: dict[str, str] = {}
    if args.carry_from is not None:
        for path in sorted(args.carry_from.glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as handle:
                for r in csv.DictReader(handle):
                    if r.get("term"):
                        carried_terms.setdefault(r["cui"], r["term"])
                    if r.get("category"):
                        carried_categories.setdefault(r["cui"], r["category"])
    if args.mrsty.exists():
        types = load_semantic_types(args.mrsty, union)
        from robustehr.categories import categories_of

        def category(cui: str) -> str:
            found = categories_of(types.get(cui, frozenset()))
            matched = [c for c in EXCLUSIVE if c in found]
            return matched[0] if matched else "other"
    elif carried_categories:

        def category(cui: str) -> str:
            return carried_categories.get(cui, "unresolved")
    else:
        raise SystemExit(f"no MRSTY at {args.mrsty} and no --carry-from export to take categories from")

    args.out.mkdir(parents=True, exist_ok=True)
    args.terms_out.mkdir(parents=True, exist_ok=True)
    terms = preferred_terms(args.mrconso, union) if args.mrconso.exists() else carried_terms

    index: list[dict[str, Any]] = []
    for name in names:
        definition = definitions[name]
        members = built[name].concept_cuis
        vet = vetting_raw.get(name, {})
        disorder = build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis
        medication = facets.medications(
            frozenset(c for code in definition.seeds for c in code_to_cuis.get(code, ())),
            disorder,
            edges,
            declared=definition.medication_seeds,
            vetted=vetting.get(name, {}).get("medication"),
        )
        finding = facets.findings(definition.finding_seeds, isa, code_to_cuis)
        proposed = frozenset(c for cuis in proposals.get(name, {}).values() for c in cuis)
        kept_proposed = vetting.get(name, {}).get("proposed")
        if kept_proposed is not None:
            proposed &= kept_proposed
        closure = closure_kept.get(name, frozenset()) & vetting.get(name, {}).get(
            "closure", frozenset()
        )

        def facet_and_provenance(cui: str) -> tuple[str, str]:
            if cui in medication.cuis:
                return "medication", medication.provenance.get(cui, "closure")
            if cui in closure:
                return "closure", "one-hop neighbourhood"
            if cui in proposed:
                return "proposed", "grounded"
            if cui in finding.cuis:
                return "finding", "declared seed"
            return "disorder", "descendant closure"

        def verdict(cui: str, facet: str) -> str:
            for facet_key in (facet, "medication", "proposed", "closure"):
                reviewed = (vet.get(facet_key) or {}).get("reviewed") or {}
                if cui in reviewed:
                    return reviewed[cui]["verdict"]
                base = edges.ingredient(cui)
                if base != cui and base in reviewed:
                    return reviewed[base]["verdict"]
            return "auto"

        rows = []
        for cui in sorted(members):
            facet, provenance = facet_and_provenance(cui)
            rows.append(
                {
                    "phenotype": name,
                    "cui": cui,
                    "facet": facet,
                    "provenance": provenance,
                    "vetted": verdict(cui, facet),
                    "category": category(cui),
                    "in_corpus": int(corpus_counts.get(cui, 0) > 0),
                    "corpus_mentions": corpus_counts.get(cui, 0),
                    "in_sample": int(sample_counts.get(cui, 0) > 0),
                    "sample_mentions": sample_counts.get(cui, 0),
                }
            )
        # Observed concepts first, then by category — a reader scanning the
        # appendix wants the concepts the corpus actually writes at the top.
        rows.sort(key=lambda r: (-r["corpus_mentions"], r["category"], r["cui"]))

        with (args.out / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        with (args.terms_out / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["term", *COLUMNS])
            writer.writeheader()
            writer.writerows({"term": terms.get(r["cui"], ""), **r} for r in rows)

        observed = sum(r["in_corpus"] for r in rows)
        index.append(
            {
                "phenotype": name,
                "concepts": len(rows),
                "observed_in_corpus": observed,
                "observed_in_sample": sum(r["in_sample"] for r in rows),
                "with_english_term": sum(1 for r in rows if terms.get(r["cui"])),
            }
        )
        print(f"{name:<30} {len(rows):>6} concepts, {observed:>5} observed")

    with (args.out / "index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(index[0].keys()))
        writer.writeheader()
        writer.writerows(index)
    (args.out / "README.md").write_text(
        "# Appendix — concept sets per phenotype\n\n"
        "One CSV per phenotype: every concept a `pheno=` target selects, with "
        "how it entered the set, who judged it, and whether the corpus writes "
        "it. Generated by `analysis/export_concept_appendix.py`.\n\n"
        "**Identifiers only.** UMLS preferred terms are licensed content and "
        "are not redistributed here; a companion export carrying them is "
        "written to `data/appendix/concepts_with_terms/` (gitignored) for a "
        "reader who holds a licence. Resolve any CUI against your own release.\n\n"
        "| column | meaning |\n|---|---|\n"
        "| `facet` | disorder closure, MED-RT medication, declared finding, "
        "LLM-proposed, or evidence closure |\n"
        "| `provenance` | how it was reached — seed, closure, lift, identity "
        "(RxNorm brand/product of a kept ingredient), declared, grounded |\n"
        "| `vetted` | `keep` = explicitly judged clinically appropriate; "
        "`auto` = asserted by a curated source and not model-reviewed |\n"
        "| `category` | the shipped exclusive partition (one category per "
        "concept) |\n"
        "| `in_corpus` / `corpus_mentions` | does any of the 1,388 notes write "
        "it, and how often |\n"
        "| `in_sample` / `sample_mentions` | the same over the 500 evaluated "
        "notes |\n\n"
        "Rows are sorted by corpus frequency, so the concepts that carry the "
        "evidence appear first. `index.csv` summarises the panel.\n",
        encoding="utf-8",
    )
    print(f"\n-> {args.out} (identifiers, shippable)\n-> {args.terms_out} (terms, data/ only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
