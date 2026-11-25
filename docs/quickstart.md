# Running the pipeline on MIPA notes

Baseline a corpus, corrupt it under control, and measure what the corruption
cost — with every command verified end to end by
RobustEHR's `validation/pipeline/scripts/pipeline_audit.py`
(artifact: `validation/measurements/pipeline_audit.json`).

## Prerequisites

| what | needed for | if absent |
|---|---|---|
| the corpus (`note_id`, `text`) | everything | nothing runs |
| `data/quickumls_index` | concepts, phenotypes, `compare` | `baseline` still works |
| `data/umls_isa_mth.json`, `data/snomed_el` | phenotype targeting | `--phenotype` fails loudly |

**`baseline` deliberately needs no terminology.** That is what lets a reader
without a UMLS licence reproduce the structural half of the work, and it is
asserted in the audit rather than assumed.

## 1. Baseline — what is in the notes before anything is injected

```bash
robustehr describe --corpus notes.csv --markdown \
    --phenotype hypertension --phenotype heart_failure
```

That is **Table 1**, and it has one organisation: the taxonomy's. Every row is
a structural **level** an operator can target, so a reader can see which
operators reach which units — and the coverage is checked, not asserted
(`_unmeasured_levels_with_operators` must stay empty). On five MIMIC-IV
discharge summaries:

```
| level         | units, median [IQR] |  total | corruptible by                     |
| document      |             1 [1-1] |      5 | identity, truncate                 |
| section       |         33 [31-34]  |    165 | — (targetable via section=)        |
| header        |         46 [41-62]  |    278 | header_style, header_delete        |
| sentence      |        338 [257-340]|   1593 | sentence_delete                    |
| list_item     |         74 [69-94]  |    417 | bullet_to_prose                    |
| aligned_block |         12 [10-12]  |     64 | —                                  |
| space_run     |          7 [6-11]   |     58 | whitespace_collapse, lab_block_...  |
| placeholder   |         73 [61-87]  |    373 | deid_restyle                       |
| span          |        780 [746-820]|   3918 | — (targetable via cat=, pheno=)    |
| token         |      6134 [6022-6826]| 30650 | typo, char_shuffle, ocr_confusion  |
| character     |     15588 [15009-17127]| 77393 | —                                |
| assertion     |          376 cues   |    376 | 4 semantic operators               |
```

**A count is not a denominator**, and two levels report theirs explicitly. The
token level reports its composition — each field *is* an operator's eligible
set:

```
| word_min3     | 1780 [1610-1796] |  8513 | `input.typo`             |
| word_min4     | 1364 [1260-1374] |  6487 | `control.char_shuffle`   |
| ocr_confusable| 2301 [2091-2379] | 10990 | `input.ocr_confusion`    |
```

The assertion level reports **cues**, which is what a SEMANTIC operator is
eligible on — *not* the mentions carrying the attribute, which is a different
population one cue can produce several of:

```
| operator                     | eligible cues | mentions with the attribute |
| semantic.negation_flip       |           216 |                         355 |
| semantic.uncertainty_flip    |            65 |                         126 |
| semantic.temporality_shift   |            70 |                         131 |
| semantic.experiencer_shift   |            25 |                          33 |
```

**A concept mention is a span, so it has a level of its own.** Reporting it at
the token level made two true numbers look contradictory — 3,918 mentions over
12,399 content tokens reads as 32%, and the real answer is neither that nor
anything derivable from it, because mentions overlap and run one to six tokens
long. So both are reported:

| block | question it answers | on this corpus |
|---|---|---|
| `span.n` + `by_category` | how many mentions, of what kind | 3,918 spans; disorder 0.435 · finding 0.209 · procedure 0.197 · medication 0.192 |
| `span.token_lengths` | the bridge to the token level | 84% of mentions are one token |
| `token.concept_covered` | **what % of tokens are UMLS concepts** | **0.386 of content tokens** (disorder 0.169 · medication 0.086 · finding 0.083) |
| `assertion.by_attribute` | where a flip would land, by category | of 355 negated mentions, 224 are disorders and 114 findings |

Three further token blocks:

| block | what it answers | needs |
|---|---|---|
| lexical class | the 4-way partition of content tokens, plus overlapping annotations | nothing |
| abbreviation load | 1,337 abbreviation-shaped tokens (0.108 of content), 617 ambiguous, and the sense distribution `ambiguous` collapses — 221 tokens carry **10+ senses** | UMLS index |
| near-miss | 324 unrecognised candidates, 177 within one edit of a known term | clinical lexicon |

**Section presence names which of the 58 canonical sections**, and lists the
absent ones rather than omitting them — 28 present, 30 absent on this corpus,
and the absences are informative: `assessment_plan` and the ten `exam_*` ids are
missing because MIMIC-IV discharge summaries carry a *Brief Hospital Course* and
one *Physical Exam* block instead.

**Read the near-miss caveat before quoting it.** `near_miss_edit1` is a
candidate count, not a misspelling rate: adjudicated on 200 notes the filter is
right 0.425 of the time by distinct surface and **0.096 by occurrence**, because
the frequent near-misses are vocabulary the lexicons miss (`refills`,
`mellitus`) and clinical shorthand (`angap`, `eomi`). Use `distinct_hapax`,
where precision roughly doubles to 0.526. Numbers in
RobustEHR's `validation/measurements/spelling_precision.json`; re-run with its
`validation/pipeline/scripts/spelling_validate.py --review` to prepare a human sample.

### Per cohort, with each cohort's own annotator

```bash
robustehr describe --corpus notes.csv --markdown --per-note \
    --groups data/golden_labels.csv --group-map mipa
```

`--groups` reads a wide CSV of binary label columns keyed by `note_id`. Each
column becomes a cohort with its own Table 1, **annotated with that cohort's
phenotype** — the hypertension-positive notes are measured with the hypertension
concept set, the SLE-positive notes with the SLE set. `--group-map mipa` supplies
the correspondence from
the `robustehr` package's `resources/label_groups.yaml`,
because MIPA's column names are not this package's phenotype names (`sle` →
`systemic_lupus_erythematosus`, `vte_past` → deep vein thrombosis **and**
pulmonary embolism) and getting that wrong produces a table that looks right.

Three properties worth knowing:

* **Cohorts overlap.** A note positive for hypertension is usually positive for
  depression too, so the group sizes sum to more than the corpus — on MIPA,
  4,003 memberships over 1,387 notes. `_coverage` reports the arithmetic rather
  than leaving a reader to look for missing notes.
* **`none` is a cohort.** 35 notes are positive for nothing; no annotator
  applies, and that is the comparison every other cohort is read against.
* **One annotation pass, not one per cohort.** Every note is matched once and
  indexed against all declared phenotypes; a cohort's table is `assemble` over
  the subset of rows already measured. Running `describe` once per group would
  annotate 4,003 times over 1,387 notes and would let a cohort's numbers
  disagree with the corpus's.

Inside a cohort, `span.by_phenotype` still reports **every** declared phenotype,
not just its own — which is how cross-phenotype contamination becomes visible.

**One document per phenotype.** `--group-out DIR` writes a self-contained
Table 1 per cohort, markdown beside JSON, each naming its own note count and its
own annotator. The whole artifact is one command:

```bash
robustehr describe --corpus data/golden_notes.csv \
    --groups data/golden_labels.csv --group-map mipa \
    --per-note \
    --group-out data/mipa_table1/by_phenotype \
    --out data/mipa_table1/table1.json
```

**Re-render without re-measuring.** The documents are a pure function of the
table, and `--from-table` proves it — no corpus is read, and the output is
byte-identical to the measuring run's:

```bash
robustehr describe --from-table data/mipa_table1/table1.json \
    --group-out data/mipa_table1/by_phenotype
```

0.1 seconds instead of the ~76 minutes the annotation pass over 1,388 notes
costs, so a formatting change never means re-running the measurement.

`--per-note` adds a row per note carrying the same measurements before
aggregation, so a reader can find which note holds the p75 header count. Those
rows carry `note_uid` and are note-derived: `data/` only on a restricted corpus.
`--cui-map` adds every mention as `(note_uid, cui, span, tuis, categories)` —
identifiers and offsets only, never the matched surface, and note-derived for
the same reason.

The other commands remain for detail:

```bash
robustehr applicability   --corpus notes.csv   # does each operator apply here at all?
robustehr baseline        --corpus notes.csv   # degradation detail. No index needed.
robustehr concept-profile --corpus notes.csv --per-note --phenotype hypertension
robustehr ambiguity       --corpus notes.csv   # abbreviation load, with spans
```

`concept-profile` reports, per note: concepts, distinct CUIs, by category,
concepts per 1,000 content tokens, per-phenotype evidence, and the assertion
breakdown (`negated`, `uncertain`, `historical`, `family`, `unmodified`).

Two conventions worth knowing before reading the output:

* `affirmed` is **null**, not zero, when the assertion stage did not run —
  "not asked" and "asked and found none" are different facts.
* `phenotype_measured_set_recall` travels beside the counts. A phenotype's count
  is only as good as its concept set, and evidence never matched is evidence
  never counted. See RobustEHR's `validation/phenotype/phenotype-concept-table.md`.

`--per-note` rows carry `note_uid` and are therefore note-derived: they belong
under `data/` on a restricted corpus.

## 2. Corrupt — two axes

**Scale** is chosen by the operator; **target** by the selector.

```bash
robustehr taxonomy                      # every operator, its level and channel
robustehr target 'cat=medication'         # explain what a target selects
```

| you want | write |
|---|---|
| everything | `--target all` |
| general English, not clinical terms | `--target lex=general_english` |
| one semantic category | `--target cat=medication` |
| one phenotype's concepts | `--target pheno=heart_failure` |
| a category **within** a phenotype | `--target 'all(cat=medication;pheno=hfpef)'` |
| either of two phenotypes | `--target 'any(pheno=deep_vein_thrombosis;pheno=pulmonary_embolism)'` |
| a section | `--target section=history_of_present_illness` |
| everything except | `--target 'not(cat=disease)'` |

```bash
robustehr run --corpus notes.csv --out run/ \
    --operators input.typo --severities 0.10 0.30 0.50 \
    --target 'all(cat=medication;pheno=hypertension)'
```

**Severity is a fraction of eligible units, not of the document.** `dose.jsonl`
records the whole chain — `total_n → scope_n → protected_n → eligible_n →
requested_k → applied_n` — so a dose that could not be delivered is visible
rather than silently rounded.

### Several corruptions at once

```bash
robustehr run --corpus notes.csv --out run/ --compose \
    --operators input.typo render.whitespace_collapse discourse.sentence_delete \
    --severities 0.30 --emit-text data/corrupted/
```

Every operator proposes against the **pristine** note, and the proposals are
merged in one pass. Two consequences:

* **Order does not matter.** Conflicts resolve by a content-derived total order,
  so `a,b` and `b,a` produce identical bytes.
* **Collisions are counted.** A sentence delete swallows spans a token operator
  wanted; those land in `dose.conflicts_dropped` rather than vanishing. On three
  MIMIC notes at severity 1.0 the audit records 2,976 of them.

`--emit-text` writes the corrupted notes. It refuses any path outside `data/`
unless `--i-understand-the-licence` is passed — corrupted text is derived from
the corpus and carries its restrictions.

## 3. Verify and compare

```bash
robustehr replay  --run run/ --corpus notes.csv          # every cell reconstructs to its hash
robustehr compare --run run/ --corpus notes.csv --markdown --phenotype hypertension
```

`compare` runs **the same function** — `metrics.concepts.profile_concepts` —
over the pristine and the corrupted text. That is what makes the delta
meaningful: a change in the table is a change the baseline instrument can see,
so it is a change a downstream model sees too.

```
operator        sev  applied  concepts   delta  pheno d  by category
input.typo rate:0.1      171       746     -52       +0  anatomy -3, disease +5
input.typo rate:0.3      512       746    -147       +0  anatomy -18, disease +2
```

The same operator at the same severity, aimed differently:

| target | applied | concepts lost |
|---|---:|---:|
| `all` | 512 | −147 |
| `cat=medication` | 42 | −32 |

A **positive** delta is real and is reported rather than hidden: a typo can
accidentally spell a concept the matcher then finds.

## Known limitations before you interpret a result

- **`hfpef` and `hfref` recover none of their own disorder evidence** (measured
  0.000). Their declarations say DO NOT USE for disorder-facet work; the
  medication and proposal facets are populated and usable.
- **`depression`** is weak in both directions on the disorder facet (recall
  0.111, precision 0.188) with span recall 1.000 — the text is found and
  assigned elsewhere. Treat depression results as unsupported.
- **No concept set is clinician-signed.** Vetting is `vetted_by: llm`, and the
  model demonstrably errs. RobustEHR's
  `validation/phenotype/scripts/phenotype_export_review.py` produces the review
  file; the review has not happened.
- **Union precision is unmeasured** — see
  RobustEHR's `validation/record/methodology/14-phenotype-concept-association.md` §5.
