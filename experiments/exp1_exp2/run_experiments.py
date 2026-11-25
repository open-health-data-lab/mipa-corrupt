"""Generate the Experiment 1 and Experiment 2 corruption datasets.

    python experiments/exp1_exp2/run_experiments.py \
        --corpus data/golden_notes.csv --out data/experiments

**Experiment 1 — global corruption robustness.** Nine corruptions, each applied
*independently* to the full corpus at three severities. No corruption is ever
combined with another, so every condition isolates one operator.

    Basket 1 (structural)   header deletion, bullet-to-prose, loss of text
                            structure, spacing loss, section duplication,
                            header renaming
    Basket 2 (character)    typographical errors, homoglyph substitution,
                            alphanumeral variation

**Experiment 2 — clinically-targeted character corruption.** Two Basket 2
operators — typographical errors and homoglyph substitution — restricted to
**clinical content** and **stratified by each document's own semantic-category
distribution**, so no category is corrupted at a higher rate than another and a
degradation can be attributed to the category rather than to how the sampler
fell.

"Restricted to UMLS concept spans" is what this said, and what an earlier build
did. Measured against the SNOMED CT Entity Linking gold, that rule admits 45.7%
of a discharge summary's tokens at 0.500 precision — it corrupts `she`, `you`,
`please` and section headings, and only ~30% of its edit budget reaches clinical
content. Section headings in particular confound this experiment with Experiment
1's structural arms. The target is now `ClinicalSalience`: 0.820 precision at
28.0% coverage against a gold rate of 29.1%. See `docs/validation-protocol.md`
§9 for the measurement and the two failure modes only whole-note review caught.

`alphanumeral_variations` is deliberately absent: under a clinical target its
eligible units are lab values and doses, which asks a different question from
"does corrupting the clinical *terms* hurt". It still runs in Experiment 1 over
the whole document.

Output layout — one directory per condition, so a downstream evaluation can walk
the tree without parsing filenames::

    <out>/
      index.json                     every condition, machine-readable
      README.md                      the same, for a human
      baseline/
        table1.json  table1.md       the clean corpus, same instrument
        notes.csv                    hadm_id, note_id, note_text
      exp1/
        <corruption>/
          <severity>/
            notes.csv                hadm_id, note_id, note_corrupted
            table1.json  table1.md   the corrupted corpus
            dose.jsonl               per-note dose accounting
            edits.jsonl              the replayable edit script
            manifest.json
      exp2/  ... same shape

Every `notes.csv` carries `hadm_id` and `note_id` so a condition joins straight
back to the cohort labels, and `note_corrupted` so no downstream step has to
replay anything to read the text.

**These CSVs contain note text.** They are written under `data/` by default,
which is gitignored, and they inherit the corpus licence — a corrupted MIMIC
note is still MIMIC. The edit scripts beside them carry offsets only and are the
redistributable artifact.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Basket 1 — structural. Each row is the taxonomy name a reader will look for,
#: the operator that implements it, and any mode it needs.
STRUCTURAL: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("section_header_deletion", "render.header_delete", {}),
    ("bullet_to_prose", "render.list_to_prose", {}),
    ("loss_of_text_structure", "render.break_removal", {}),
    ("spacing_loss", "render.space_delete", {}),
    ("section_duplication", "discourse.section_duplicate", {}),
    ("section_header_renaming", "render.header_rename", {}),
)

#: Basket 2 — character level. Used by both experiments; Experiment 2 adds the
#: concept target and the stratifier without changing the operators.
CHARACTER: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("typographical_errors", "input.typo", {}),
    ("homoglyph_substitutions", "input.ocr_confusion", {"mode": "glyph"}),
    ("alphanumeral_variations", "lexical.numeral_to_word", {"mode": "bare"}),
)

#: Experiment 2 runs the two corruptions that act on the *characters of a term*.
#: All three CHARACTER operators run in Experiment 1 over the whole document.
EXP2_CORRUPTIONS = frozenset({"typographical_errors", "homoglyph_substitutions"})

#: One line per corruption for the methods table: what a clinician would
#: recognise it as, and what a reader should expect it to change. The mechanical
#: facts (unit, contract, severity ladder) are read from the operator so they
#: cannot drift; only the description lives here.
DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "section_header_deletion": (
        "An export or template that dropped its section headings.",
        "Section headers fall; the content beneath them survives but is no "
        "longer attributable to a section.",
    ),
    "section_header_renaming": (
        "A different institution or template naming the same section "
        "differently (`Assessment and Plan:` -> `Clinical Impression:`).",
        "Counts do not move — the header is still a header of the same "
        "canonical section. Only the section VOCABULARY changes.",
    ),
    "bullet_to_prose": (
        "A structured problem list pasted into a free-text field.",
        "Lists collapse into running prose joined by `; `; list and list-item "
        "counts fall, prose sentences rise.",
    ),
    "loss_of_text_structure": (
        "An export that did not carry line structure.",
        "Structural breaks between blocks are replaced by a single space; "
        "sections and headers merge into surrounding narrative.",
    ),
    "spacing_loss": (
        "Word boundaries lost to copy-paste or PDF text extraction.",
        "Single spaces between words are deleted, merging word pairs; token "
        "counts fall and out-of-vocabulary rises.",
    ),
    "section_duplication": (
        "Copy-paste note bloat repeating a section verbatim.",
        "Sections rise. The benign control for copy-forward: content is "
        "identical, so nothing is contradicted, only repeated.",
    ),
    "typographical_errors": (
        "Keyboard typing errors: substitution over QWERTY adjacency, "
        "transposition, deletion, doubling.",
        "Word counts do NOT move — a mistyped word is still a word. Damage "
        "shows as out-of-vocabulary tokens and disturbed concepts.",
    ),
    "homoglyph_substitutions": (
        "Optical character recognition on a scanned or faxed chart, including "
        "the digit-letter confusions (`5`->`S`, `0`->`O`) that turn a lab value "
        "into a word.",
        "Character counts do not move. Damage shows as out-of-vocabulary "
        "tokens and disturbed concepts, at a far higher rate than typos.",
    ),
    "alphanumeral_variations": (
        "A dictated or template-written note that spells numbers out "
        "(`EF 30 %` -> `EF thirty %`).",
        "Numeric tokens fall and words rise. Unit-bearing values (`650 mg`) "
        "are excluded by default so drug doses keep their parseable shape.",
    ),
}

#: The three levels every condition runs at, resolved per operator from its own
#: `severity_levels` ladder — 5/10/15% for a typo, 30/50/100% for a header
#: deletion, 1/2/5 sections for a duplication. One shared ladder would compare a
#: mild dose against a severe one and call them the same condition.
LEVELS = ("low", "medium", "high")


@dataclass
class Condition:
    """One (experiment, corruption, severity) cell."""

    experiment: str
    corruption: str
    op_id: str
    level: str
    severity: str
    params: dict[str, str]
    targeted: bool
    stratified: bool
    directory: Path
    notes: int = 0
    edits: int = 0
    notes_changed: int = 0
    eligible_total: int = 0
    applied_total: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    concept_impact: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "corruption": self.corruption,
            "operator": self.op_id,
            "severity_level": self.level,
            "severity": self.severity,
            "params": self.params,
            "target": "clinical_salience" if self.targeted else "whole_document",
            "target_canon": _target_canon() if self.targeted else None,
            "salience_lexicon": _salience_manifest() if self.targeted else None,
            "stratified_by": "semantic_category" if self.stratified else None,
            "path": str(self.directory.relative_to(self.directory.parents[2])),
            "notes": self.notes,
            "notes_changed": self.notes_changed,
            "eligible_units": self.eligible_total,
            "applied_edits": self.applied_total,
            "status_counts": self.status_counts,
            "concept_impact": self.concept_impact,
        }


def read_corpus(path: Path, limit: int | None) -> list[dict[str, str]]:
    """Notes plus the identifiers a downstream evaluation joins on."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if limit:
        rows = rows[:limit]
    missing = {"note_id", "text"} - set(rows[0])
    if missing:
        raise SystemExit(f"corpus is missing column(s) {sorted(missing)}")
    return rows


def write_notes_csv(path: Path, rows: list[dict[str, str]], column: str) -> None:
    """`hadm_id, note_id, <column>` — the join keys first, then the text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hadm_id", "note_id", column])
        writer.writeheader()
        writer.writerows(rows)


def annotate_all(
    docs: list[Any], index: Path, cache_root: Path, workers: int, label: str
) -> dict[str, Any]:
    """Corpus-level concept tagging, which now lives in the package.

    Cached by note hash, parallel across processes, and keyed on the matcher
    config — none of which is specific to this experiment, so it moved to
    `robustehr.concepts.annotate`. Kept as a thin wrapper under the old name
    because the import stays deferred here: this script must run without the
    terminology extra installed, and a module-scope import would load the
    concept layer just to print `--help`.
    """
    from robustehr.concepts.annotate import annotate_corpus

    return annotate_corpus(docs, index, cache_root, workers=workers, label=label)

def write_delta_table(
    rows: list[Any], condition: Condition, lexicon: Any, baseline: dict[str, Any] | None
) -> None:
    """The post-corruption table, as a change against the clean corpus.

    A standalone corrupted table is hard to read — nobody remembers the clean
    corpus had 27 headers per note, so "14" means nothing on its own. What a
    condition answers is the *drop*: `render.header_delete` at 0.50 takes half
    the section headers, and that is the row a reader wants, in absolute terms
    and as a percentage.
    """
    from robustehr import report
    from robustehr.metrics.describe import assemble

    payload: dict[str, Any] = {
        "what": f"Table 1 delta — {condition.corruption} / {condition.level}",
        "corpus": f"{condition.experiment}/{condition.corruption}/{condition.level}",
        "lexicon_source": lexicon.source,
        "phenotypes": [],
        **assemble(rows, {}).to_row(),
    }
    condition.directory.mkdir(parents=True, exist_ok=True)
    (condition.directory / "table1.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if baseline is None:  # pragma: no cover - baseline always precedes conditions
        return
    with (condition.directory / "table1_delta.md").open("w", encoding="utf-8") as handle:
        report.delta_table(
            baseline,
            payload,
            lambda line="": print(line, file=handle),
            title=(
                f"Table 1 Δ — {condition.corruption} ({condition.level}, "
                f"`{condition.severity}`)"
            ),
            subtitle=(
                f"`{condition.op_id}` applied independently to the full corpus, "
                f"{condition.experiment}"
                + (
                    ", restricted to clinical content by the measured "
                    "`ClinicalSalience` rule (validation-protocol §9), with the "
                    "dose allocated proportionally across semantic categories."
                    if condition.stratified
                    else "."
                )
            ),
        )


def _measure_all(
    docs: list[Any],
    lexicon: Any,
    concepts: dict[str, Any] | None,
    widths: dict[str, int] | None = None,
) -> list[Any]:
    """Per-note rows, with the concept blocks when a tagged corpus is available.

    ``concepts`` maps note uid -> its :class:`MentionIndex`. Supplying it turns
    on the span level, the semantic-category distribution, the medication naming
    breakdown and the abbreviation-ambiguity bands — the blocks that make a
    post-corruption table comparable to the baseline on the axes a robustness
    result is actually about, rather than on structure alone.
    """
    from robustehr.concepts.phenotype import PhenotypeIndex
    from robustehr.metrics.ambiguity import profile_ambiguity
    from robustehr.metrics.concepts import profile_concepts
    from robustehr.metrics.describe import measure_note

    widths = widths or {}
    if not concepts:
        return [
            measure_note(doc, lexicon, wrap_width=widths.get(doc.uid)) for doc in docs
        ]

    matcher = _shared_matcher()
    rows = []
    for doc in docs:
        mentions = concepts.get(doc.uid)
        if mentions is None:  # pragma: no cover - every doc is tagged upstream
            rows.append(measure_note(doc, lexicon, wrap_width=widths.get(doc.uid)))
            continue
        rows.append(
            measure_note(
                doc,
                lexicon,
                profile_concepts(doc, mentions, PhenotypeIndex(), None),
                profile_ambiguity(doc, matcher, keep_occurrences=False)
                if matcher is not None
                else None,
                None,
                # A sequence of Mention, matching what `cli._describe_concepts`
                # hands `measure_note` — the index itself is not iterable.
                mentions.mentions,
                widths.get(doc.uid),
            )
        )
    return rows


_MATCHER: list[Any] = []


def _shared_matcher() -> Any:
    """One matcher for the whole process — loading the index is seconds each."""
    if not _MATCHER:
        from robustehr.concepts.matcher import ConceptMatcher

        _MATCHER.append(ConceptMatcher(Path(_INDEX[0])) if _INDEX else None)
    return _MATCHER[0]


_INDEX: list[str] = []


def load_lexicon(path: Path) -> Any:
    """The clinical vocabulary, or the morphology-only fallback with a warning.

    Not optional decoration. Without it `dose.category_hits` is empty for every
    row in every condition, so the artifact cannot answer "did this operator hit
    medications or function words" — which is the column that makes an Exp1
    result interpretable and the one that shows Exp2's targeting worked.
    """
    from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon

    if not path.exists():
        print(
            f"WARNING: no clinical lexicon at {path}. Landing counts "
            "(dose.category_hits) will be empty for every condition.",
            flush=True,
        )
        return DEFAULT_LEXICON
    lexicon = load_clinical_lexicon(path)
    print(f"lexicon: {lexicon.source}", flush=True)
    return lexicon


def write_table1(rows: list[Any], out_dir: Path, label: str, lexicon: Any) -> dict[str, Any]:
    """Corpus-level Table 1 — the whole set of notes, not one of them.

    Takes the already-measured per-note rows rather than re-reading the CSV: the
    corrupted text has to be segmented once to be measured at all, and doing it
    twice would double the dominant cost of the sweep.

    The baseline table and every post-corruption table come off the identical
    `assemble`, so a difference between them is a difference the instrument can
    see rather than an artifact of measuring them differently. Structural and
    character levels only — they need no terminology, which is what lets all 27
    conditions be characterised at the same cost.
    """
    from robustehr import report
    from robustehr.metrics.describe import assemble

    payload: dict[str, Any] = {
        "what": f"Table 1 — {label}",
        "corpus": label,
        "lexicon_source": lexicon.source,
        "phenotypes": [],
        **assemble(rows, {}).to_row(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "table1.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out_dir / "table1.md").open("w", encoding="utf-8") as handle:
        report.render(payload, {}, handle, None)
    return payload


def _target_canon() -> str:
    """The rule's canonical string, which is also what feeds the seed."""
    from robustehr.target import ClinicalSalience

    return ClinicalSalience().canon()


def _salience_manifest() -> dict[str, object]:
    """Corpus and digest of the lexicon the targeting rule consulted.

    `docs/validation-protocol.md` §9 requires a targeting claim to quote its
    rule, its lexicon digest and its benchmark. Without them "concept-targeted"
    is exactly the assertion the first build of this experiment made, and it was
    wrong by a factor of three.
    """
    from robustehr.salience import manifest

    m = manifest()
    return {k: m[k] for k in ("sha256", "corpus", "notes", "types") if k in m}


def build_conditions(out: Path, exp2: bool) -> list[Condition]:
    from robustehr.ops import registry

    registry.register_builtins()
    conditions: list[Condition] = []
    for name, op_id, params in STRUCTURAL + CHARACTER:
        ladder = registry.get(op_id).meta.severity_levels
        for level, literal in zip(LEVELS, ladder, strict=True):
            conditions.append(
                Condition(
                    experiment="exp1",
                    corruption=name,
                    op_id=op_id,
                    level=level,
                    severity=literal,
                    params=params,
                    targeted=False,
                    stratified=False,
                    directory=out / "exp1" / name / level,
                )
            )
    if exp2:
        # Two of the three character corruptions, by decision: `alphanumeral_
        # variations` rewrites numerals to words, and under a clinical target its
        # eligible units are lab values and doses — a different question from
        # "does corrupting the clinical *terms* hurt", which is what this
        # experiment asks.
        for name, op_id, params in CHARACTER:
            if name not in EXP2_CORRUPTIONS:
                continue
            ladder = registry.get(op_id).meta.severity_levels
            for level, literal in zip(LEVELS, ladder, strict=True):
                conditions.append(
                    Condition(
                        experiment="exp2",
                        corruption=name,
                        op_id=op_id,
                        level=level,
                        severity=literal,
                        params=params,
                        targeted=True,
                        stratified=True,
                        directory=out / "exp2" / name / level,
                    )
                )
    return conditions


def run_condition(  # noqa: PLR0917 - one argument per shared, precomputed input
    condition: Condition,
    records: list[dict[str, str]],
    documents: dict[str, Any],
    mentions_by_uid: dict[str, Any],
    salt: str,
    lexicon: Any,
    concepts: dict[str, Any] | None = None,
    measure: bool = True,
    index: Path | None = None,
    cache_root: Path = Path("data/concept_cache"),
    workers: int = 1,
    retag: bool = False,
    baseline_table: dict[str, Any] | None = None,
    widths: dict[str, int] | None = None,
) -> None:
    """Apply one operator at one severity to every note, and persist the cell."""
    from robustehr.document import Document
    from robustehr.ops import registry
    from robustehr.ops.base import Scope
    from robustehr.runner import apply_operator, parse_severity
    from robustehr.store import write_run
    from robustehr.target import ClinicalSalience

    op = registry.get(condition.op_id)()
    severity = parse_severity(condition.severity)
    # `ClinicalSalience`, not `Concept`. Measured against the SNOMED CT Entity
    # Linking gold, "any UMLS mention" admits 45.7% of a discharge summary's
    # tokens at 0.500 precision — it corrupts `she`, `you`, `please` and section
    # headings, and only ~30% of the edit budget reaches clinical content. It
    # also tags `History of Present Illness`, which confounds this experiment
    # with Experiment 1's structural arms. See docs/validation-protocol.md §9.
    scope = Scope(target=ClinicalSalience()) if condition.targeted else Scope()
    condition.directory.mkdir(parents=True, exist_ok=True)

    from robustehr.metrics.impact import aggregate, concept_impact

    doses, edit_groups, out_rows, corrupted_docs = [], [], [], []
    impacts = []
    statuses: dict[str, int] = {}
    for record in records:
        uid = record["note_id"]
        doc = documents[uid]
        result = apply_operator(
            doc,
            op,
            op.meta,
            severity,
            scope=scope,
            params=condition.params,
            salt=salt,
            lexicon=lexicon,
            mentions=mentions_by_uid.get(uid) if condition.targeted else None,
            stratify_by="semantic_category" if condition.stratified else None,
        )
        doses.append(result.dose)
        edit_groups.append(result.apply_result.applied)
        statuses[result.dose.status.value] = statuses.get(result.dose.status.value, 0) + 1
        condition.eligible_total += result.dose.eligible_n
        condition.applied_total += result.dose.applied_n
        if result.text != doc.text:
            condition.notes_changed += 1
        if measure:
            # Segment the corrupted text once, here, and reuse it for the
            # table. Re-reading the CSV afterwards would segment it a second
            # time, and segmentation-plus-measurement is the dominant cost of
            # the whole sweep.
            corrupted_docs.append(Document.from_text(result.text, uid=uid))
        # Where the corruption landed, in UMLS terms, from the CLEAN tags and
        # this cell's edits. No re-annotation: an edit carries original offsets
        # and a mention carries an original span, so the intersection is a
        # lookup. See `metrics/impact.py` for what this does and does not say.
        if concepts and uid in concepts:
            impacts.append(concept_impact(uid, concepts[uid], result.apply_result.applied))
        out_rows.append(
            {
                "hadm_id": record.get("hadm_id", ""),
                "note_id": uid,
                "note_corrupted": result.text,
            }
        )

    write_notes_csv(condition.directory / "notes.csv", out_rows, "note_corrupted")
    if impacts:
        (condition.directory / "concept_impact.json").write_text(
            json.dumps(
                {
                    "what": (
                        "which UMLS concepts this condition's edits landed on, derived "
                        "from the CLEAN tagging and the edit script"
                    ),
                    "caveat": (
                        "touched is not lost: a mistyped concept may still match, and a "
                        "corruption can create a match. Recognition survival needs the "
                        "corrupted text re-tagged (--retag-corrupted)."
                    ),
                    **aggregate(impacts),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        condition.concept_impact = aggregate(impacts)

    # Only when explicitly asked: this is the expensive half, and it is the one
    # measurement the clean tags cannot supply.
    retagged: dict[str, Any] | None = None
    if measure and retag and index is not None:
        retagged = annotate_all(
            corrupted_docs,
            index,
            cache_root,
            workers,
            f"{condition.corruption}/{condition.level}",
        )
    manifest = write_run(
        condition.directory,
        run_id=f"{condition.experiment}.{condition.corruption}.{condition.level}",
        doses=doses,
        edits=edit_groups,
        corpus="corpus",
        # With the notes, each replacement is stored as its minimal difference
        # (one offset and one letter for a typo) instead of the retyped word.
        texts={uid: doc.text for uid, doc in documents.items()},
        extra={
            "experiment": condition.experiment,
            "corruption": condition.corruption,
            "operator": condition.op_id,
            "severity_level": condition.level,
            "severity": condition.severity,
            "params": condition.params,
            "target": scope.resolved_target().canon(),
            # `docs/validation-protocol.md` §9 requires a targeting claim to
            # quote its rule, its lexicon digest and its benchmark. The canon
            # above is the rule; without the other two, "clinical-targeted" is
            # the same unbacked assertion the first build of this experiment
            # made, and that one was wrong by a factor of three.
            "salience_lexicon": _salience_manifest() if condition.targeted else None,
            "stratified_by": "semantic_category" if condition.stratified else None,
            "salt": salt,
        },
    )
    condition.notes = len(records)
    condition.edits = manifest["edits"]
    condition.status_counts = dict(sorted(statuses.items()))
    if measure:
        write_delta_table(
            _measure_all(corrupted_docs, lexicon, retagged, widths),
            condition,
            lexicon,
            baseline_table,
        )


def main() -> int:  # noqa: PLR0915 - a linear pipeline, one statement per stage
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/golden_notes.csv")
    parser.add_argument("--out", default="data/experiments")
    parser.add_argument("--index", default="data/quickumls_index")
    parser.add_argument("--lexicon", default="data/lexicon/clinical_tokens.txt")
    parser.add_argument(
        "--cache",
        default="data/concept_cache",
        help="persistent concept-annotation cache. Keyed by note hash and matcher "
        "config, so re-running any experiment over MIPA never re-tags a note",
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip conditions already complete on disk. A full sweep is hours "
        "long, so an interrupted run should cost the remainder rather than the "
        "whole thing — completeness is judged by the files a condition writes",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="re-run only conditions whose corruption name contains this, e.g. "
        "`loss_of_text_structure`. Everything else on disk is left alone",
    )
    parser.add_argument(
        "--retag-corrupted",
        action="store_true",
        help="also concept-tag every corrupted corpus, so each condition's Table 1 "
        "carries the surviving concept layer rather than only the derived impact. "
        "Costs ~5h over 36 conditions; cached, so it can be added later per condition",
    )
    parser.add_argument(
        "--skip-concepts",
        action="store_true",
        help="structural and character levels only; much faster, no UMLS blocks",
    )
    parser.add_argument("--salt", default="rep0")
    parser.add_argument("--limit", type=int, default=None, help="smoke-test subset")
    parser.add_argument("--skip-exp2", action="store_true")
    parser.add_argument(
        "--experiment",
        choices=("exp1", "exp2"),
        default=None,
        help="regenerate only this experiment's conditions. Exists so exp2 can be "
        "rebuilt without touching exp1 — those corpora are what a completed "
        "downstream evaluation was run against, and silently rewriting them "
        "would invalidate results already in hand.",
    )
    parser.add_argument(
        "--skip-tables", action="store_true", help="datasets only, no Table 1 per condition"
    )
    args = parser.parse_args()

    from robustehr.document import Document

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = read_corpus(Path(args.corpus), args.limit)
    print(f"corpus: {len(records)} notes", flush=True)
    lexicon = load_lexicon(Path(args.lexicon))
    _INDEX.append(args.index)
    workers = max(1, args.workers)

    # Segment once and reuse across every condition. Rebuilding per cell would
    # make segmentation the dominant cost of the sweep and would also invite the
    # layers to drift between conditions.
    documents = {r["note_id"]: Document.from_text(r["text"], uid=r["note_id"]) for r in records}
    # Each note's CLEAN wrap column, pinned so the corrupted twin is measured at
    # the same threshold. Without it, a corruption that joins lines widens the
    # margin, reclassifies hard-wrap continuations as breaks, and reports MORE
    # breaks after removing them — the instrument moving with the corruption.
    from robustehr.segment.wrap import wrap_width as _wrap_width

    widths = {uid: _wrap_width(doc.lines) for uid, doc in documents.items()}

    # -- baseline ---------------------------------------------------------
    baseline = out / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    write_notes_csv(
        baseline / "notes.csv",
        [
            {"hadm_id": r.get("hadm_id", ""), "note_id": r["note_id"], "note_text": r["text"]}
            for r in records
        ],
        "note_text",
    )
    use_concepts = not args.skip_concepts and Path(args.index).exists()
    baseline_concepts: dict[str, Any] = {}
    baseline_table: dict[str, Any] | None = None
    if not args.skip_tables:
        docs = [documents[r["note_id"]] for r in records]
        if use_concepts:
            baseline_concepts = annotate_all(
                docs, Path(args.index), Path(args.cache), workers, "baseline"
            )
        start = time.time()
        baseline_table = write_table1(
            _measure_all(docs, lexicon, baseline_concepts),
            baseline,
            "baseline (clean corpus)",
            lexicon,
        )
        print(f"baseline table1: {time.time() - start:.1f}s", flush=True)

    conditions = build_conditions(out, exp2=not args.skip_exp2)
    if args.experiment:
        conditions = [c for c in conditions if c.experiment == args.experiment]
        print(f"--experiment {args.experiment}: {len(conditions)} condition(s)", flush=True)
    if args.only:
        conditions = [c for c in conditions if args.only in c.corruption]
        print(f"--only {args.only!r}: {len(conditions)} condition(s)", flush=True)
    if args.resume:
        # A condition is complete when it has both the dataset and the table.
        # Checking the directory rather than the log means a run resumes from
        # what is actually on disk, not from what a log claims was written.
        wanted = ("notes.csv", "dose.jsonl", "edits.jsonl") + (
            () if args.skip_tables else ("table1_delta.md",)
        )
        pending = [
            c for c in conditions if not all((c.directory / f).exists() for f in wanted)
        ]
        print(
            f"--resume: {len(conditions) - len(pending)} complete, "
            f"{len(pending)} to run",
            flush=True,
        )
        conditions = pending

    # -- concept matching, once per note ----------------------------------
    # Exp2 targets concepts in the CLEAN text, which the baseline pass already
    # tagged — so this is free when tables are on and a cache hit otherwise.
    mentions_by_uid: dict[str, Any] = baseline_concepts
    if any(c.targeted for c in conditions) and not mentions_by_uid:
        mentions_by_uid = annotate_all(
            [documents[r["note_id"]] for r in records],
            Path(args.index),
            Path(args.cache),
            workers,
            "exp2 targets",
        )

    # -- conditions -------------------------------------------------------
    for i, condition in enumerate(conditions, start=1):
        start = time.time()
        run_condition(
            condition,
            records,
            documents,
            mentions_by_uid,
            args.salt,
            lexicon,
            baseline_concepts,
            not args.skip_tables,
            Path(args.index) if use_concepts else None,
            Path(args.cache),
            workers,
            args.retag_corrupted,
            baseline_table,
            widths,
        )
        print(
            f"[{i:2d}/{len(conditions)}] {condition.experiment} {condition.corruption:<24} "
            f"{condition.level:<6} sev={condition.severity:<8} "
            f"edits={condition.applied_total:7,d} "
            f"notes_changed={condition.notes_changed:4d}/{condition.notes} "
            f"{time.time() - start:.0f}s",
            flush=True,
        )

    _write_index(out, records, conditions, args)
    print(f"\nwrote {len(conditions)} conditions to {out}")
    return 0


def _write_index(
    out: Path, records: list[dict[str, str]], conditions: list[Condition], args: Any
) -> None:
    """One machine-readable index, and the same thing for a human."""
    from robustehr.version import __version__

    index = {
        "package_version": __version__,
        "corpus": Path(args.corpus).name,
        "notes": len(records),
        "salt": args.salt,
        "columns": ["hadm_id", "note_id", "note_corrupted"],
        "baseline": {"path": "baseline", "columns": ["hadm_id", "note_id", "note_text"]},
        "severity_levels": list(LEVELS),
        "conditions": [c.as_row() for c in conditions],
    }
    (out / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    from robustehr.ops import registry

    registry.register_builtins()
    n = len(records)
    lines = [
        "# Corruption datasets — EHR-Robust over MIPA",
        "",
        f"**{n:,} MIMIC-IV discharge summaries**, package `{__version__}`, seed "
        f"`{args.salt}`. Every condition is deterministic and replayable: the "
        "same corpus and seed regenerate byte-identical text on any machine.",
        "",
        "## Table — corruptions and their perturbation levels",
        "",
        "Severity is a fraction of the operator's **own eligible units**, never "
        "of document length, so the denominator differs per corruption and is "
        "named in the table. A single shared ladder would compare a mild dose "
        "against a severe one and call them the same condition.",
        "",
        "| # | Corruption | Operator | Unit dosed | Low | Medium | High | Contract |",
        "|---|---|---|---|---|---|---|---|",
    ]
    catalogue = [("Basket 1 — structural", STRUCTURAL), ("Basket 2 — character", CHARACTER)]
    row_no = 0
    for _, group in catalogue:
        for name, op_id, _params in group:
            meta = registry.get(op_id).meta
            row_no += 1
            low, med, high = meta.severity_levels
            lines.append(
                f"| {row_no} | {name.replace('_', ' ')} | `{op_id}` "
                f"| {meta.dose.unit_kind.value} | {low} | {med} | {high} "
                f"| {meta.contract.value.replace('_', ' ')} |"
            )
    lines += [
        "",
        "### What each corruption simulates, and what to expect it to move",
        "",
        "| Corruption | Simulates | Expected effect |",
        "|---|---|---|",
    ]
    for _, group in catalogue:
        for name, _op_id, _params in group:
            sim, eff = DESCRIPTIONS.get(name, ("", ""))
            lines.append(f"| **{name.replace('_', ' ')}** | {sim} | {eff} |")

    lines += [
        "",
        "> **Three corruptions substitute in place rather than removing units** "
        "— typographical errors, homoglyphs and header renaming. Their own "
        "denominator therefore cannot fall: a mistyped word is still a word, a "
        "renamed header is still a header of the same canonical section. Read "
        "those arms on out-of-vocabulary tokens and `concept_impact.json`, not "
        "on the structural delta.",
        "",
        "---",
        "",
        "## Experiment 1 — global corruption robustness",
        "",
        f"Each corruption applied **independently** to all {n:,} notes at three "
        "severities. No corruption is ever combined with another, so every "
        "condition isolates one operator. 27 conditions.",
        "",
        "| Corruption | Severity | Edits | Notes changed | Concepts touched |",
        "|---|---|---:|---:|---:|",
    ]
    for c in [x for x in conditions if x.experiment == "exp1"]:
        touched = (c.concept_impact or {}).get("share_touched")
        lines.append(
            f"| {c.corruption.replace('_', ' ')} | {c.level} (`{c.severity}`) "
            f"| {c.applied_total:,} | {c.notes_changed:,} / {c.notes:,} "
            f"| {touched:.1%} |" if touched is not None else
            f"| {c.corruption.replace('_', ' ')} | {c.level} (`{c.severity}`) "
            f"| {c.applied_total:,} | {c.notes_changed:,} / {c.notes:,} | — |"
        )

    exp2 = [x for x in conditions if x.experiment == "exp2"]
    if exp2:
        lines += [
            "",
            "## Experiment 2 — concept-targeted character corruption",
            "",
            "The three character-level corruptions again, restricted to **UMLS "
            "concept spans** and with the dose allocated proportionally across "
            "each document's own semantic-category distribution, so no category "
            "is corrupted at a higher rate than another. 9 conditions.",
            "",
            "| Corruption | Severity | Edits | Notes changed | Concepts touched |",
            "|---|---|---:|---:|---:|",
        ]
        for c in exp2:
            touched = (c.concept_impact or {}).get("share_touched")
            share = f"{touched:.1%}" if touched is not None else "—"
            lines.append(
                f"| {c.corruption.replace('_', ' ')} | {c.level} (`{c.severity}`) "
                f"| {c.applied_total:,} | {c.notes_changed:,} / {c.notes:,} | {share} |"
            )

    lines += [
        "",
        "---",
        "",
        "## What each condition directory holds",
        "",
        "| File | Contents |",
        "|---|---|",
        "| `notes.csv` | `hadm_id`, `note_id`, `note_corrupted` — the dataset |",
        "| `table1_delta.md` | Table 1 **as a change against the clean corpus**, per level |",
        "| `table1.json` | the corrupted characterisation, machine-readable |",
        "| `concept_impact.json` | which UMLS concepts these edits landed on, by category |",
        "| `dose.jsonl` | per-note dose accounting: eligible, requested, applied, status |",
        "| `edits.jsonl` | the replayable edit script — offsets only, no note text |",
        "| `manifest.json` | operator version, resource digests, seed, target |",
        "",
        "`baseline/` holds the clean corpus as `notes.csv` (`note_text`) and the "
        "full Table 1 including the UMLS concept, medication and abbreviation "
        "blocks that the per-condition delta tables omit.",
        "",
        "### Reproducing and verifying",
        "",
        "```bash",
        "robustehr replay --run exp1/<corruption>/<level> --corpus <notes.csv>",
        "```",
        "",
        "reconstructs every note from its edit script and checks it against the "
        "recorded hash. All 36 conditions verify.",
        "",
        "### Licence",
        "",
        "`notes.csv` contains note text derived from MIMIC-IV and inherits the "
        "PhysioNet DUA — a corrupted MIMIC note is still MIMIC. `edits.jsonl` "
        "carries offsets and hashes only and is the redistributable artifact.",
        "",
        "### Measurement caveats",
        "",
        "* **Break counts are measured at each note's clean wrap width.** The "
        "width is the p90 of that note's own line lengths, so a corruption that "
        "joins lines widens it and reclassifies hard-wrap continuations as "
        "breaks — reporting *more* breaks after removing them. Pinning the clean "
        "width makes the two measurements comparable.",
        "* **`concept_impact.json` reports concepts TOUCHED, not lost.** A "
        "mistyped concept may still match the terminology, and a corruption can "
        "create a spurious match. Recognition survival requires re-tagging the "
        "corrupted text (`--retag-corrupted`), which is deliberately not run by "
        "default.",
        "* **Semantic categories overlap.** `disorder` is the union of disease, "
        "finding and symptom; `procedure` of its two subtypes. Table 1 reports "
        "the leaves as the distribution and the unions separately as rollups.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
