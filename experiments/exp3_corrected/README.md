# Experiment 3 corrected

**This is the Experiment 3 the paper reports.** "Corrected" refers to its
history, below; the two earlier versions (`exp3`, `exp3bis`) are superseded.

Experiment 3 asked whether corrupting a phenotype's evidence changes the model's
call on that phenotype. It has been run twice and neither run answered the
question it posed.

**exp3** dosed `input.ocr_confusion` per character at rate 1.00, which
substitutes every confusable position in a token at once. `Hypertension` came
back as `Hvpcrfousj0h`. That is redaction with same-length noise, reported as
noise robustness.

**exp3bis** fixed the dose with `max_edits_per_token=1` and the effect largely
disappeared on the capable model, which is what dose-matching should produce.
It did not touch what the arms were aimed at.

**exp3_corrected** fixes the aim. Both experiments resolved `pheno=X` through
concept-set membership alone, so a span was evidence only where the matcher
grounded it to a CUI the closure had admitted. A closure built by walking a
disorder hierarchy cannot reach the causative organism, cannot reach the
qualifying adjective, and never sees an abbreviation that produced no candidate.
Measured against an independently authored clinical lexicon on the same 500
notes, barely half of every written diagnosis term was ever eligible, over a
per-phenotype range of 7% to 99%.

## What changed in the library

The full stage list is `validation/phenotype/PIPELINE.md`; the method is
`validation/record/methodology/16-phenotype-surface-anchoring.md` (both in the
RobustEHR repository). What matters for
reading this experiment's results:

- **Surface anchors.** Declared forms matched literally, admitted as evidence
  whatever the matcher grounded them to. Closes the organism gap, the qualifier
  gap and the abbreviation gap in one move.
- **Ungroundable terms are targeted.** The propose-then-ground stage grounded
  1,334 of 1,831 proposed clinical terms and discarded the rest as the method's
  error bar. They were not noise — `preserved left ventricular ejection
  fraction` was among them — and they now enter the target as surfaces at tier
  `associated`. A term with no CUI is still a term a reader uses.
- **A recall pass over the drops.** Vetting is precision-biased by construction;
  `phenotype_reconcile.py` sends its drops to a stronger model under the
  opposite bias, and a keep overrides a drop.
- **Stop surfaces.** The inverse of an anchor: matched surfaces refused because
  they are ordinary language in the wrong sense, `status` for "volume status"
  and `secondary` for "secondary to hypoperfusion".
- **Evidence carries its tier**, so reach into the diagnosis is reported
  separately from reach into associated concepts. That is what makes the reach
  gate below mean anything.

## What this experiment does NOT change

**The specificity screen is reported, not applied.** It removes concepts that
span too many unrelated phenotypes to discriminate, and under a per-token-capped
dose at rate 1.00 that buys nothing: every eligible span already receives
exactly one edit, so a broader set costs the diagnosis no coverage. The tier
field reports dilution directly, which is more informative than deleting the
spans before anyone can see them. The ladder ships in
`validation/measurements/phenotype_specificity.json`.

The sets are therefore **more sensitive than the ones exp3 and exp3bis ran
against, not less**. That is the intended direction: the failure those runs had
was evidence the target never reached, and a narrower set cannot fix it.

## Running it

Everything runs from the populated data checkout, because the facet, cache and
corpus paths are relative to it.

**To reproduce the experiment, start at step 3.** Steps 1 and 2 build and audit
the phenotype target itself, which is part of RobustEHR, so they run scripts
from a RobustEHR checkout (`../../RobustEHR/validation/...`). Their output, the
anchor resource, ships in RobustEHR 0.2.0, the version this repository
installs, so nobody reproducing the study needs to rebuild it or needs that
checkout. From step 3 on, every command uses only the installed `robustehr`
package and this repository. Regenerated with 0.2.0, the typographical-error
arms are byte-identical to the study's; the capped-OCR arms select the same
words and change one character in each, but draw different characters, because
the OCR operator's version is part of the seed and moved after the study ran.

```bash
cd _withdata/_RobustEHR_withdata
export OPENROUTER_API_KEY=...
R=../../mipa-corrupt/experiments
```

**1. The anchor resource, if it does not exist.** Two passes, two models. The
first ships in RobustEHR; the second does not, for the reason its docstring
gives.

```bash
ROBUSTEHR_LLM_MODEL=openai/gpt-5.6-luna \
  .venv/bin/python ../../RobustEHR/validation/phenotype/scripts/phenotype_anchors.py \
    --out ../../RobustEHR/src/robustehr/resources/phenotype_anchors.yaml

.venv/bin/python $R/exp3_corrected/vet_anchors.py \
  --anchors ../../RobustEHR/src/robustehr/resources/phenotype_anchors.yaml \
  --review $R/exp3_corrected/anchor_review.md --cache data/llm_cache
```

Then read `anchor_review.md`. Until someone has, the resource header says
`vetted_by: llm` and every result naming a `pheno=` target has to say so.
`--signed-by '<name>'` is what changes that, and it is a flag rather than a
default because passing it puts a name on a review.

The review is **recall-biased**, which is the opposite of the concept-vetting
criterion and deliberate. A first version used the vetting criterion and dropped
`lupus`, `mets` and `rheumatoid` as partial; the gap audit found `history of
lupus` and `active lupus flare` had become unreachable as a result. The eight
drops that survive the corrected criterion are all genuine ambiguities the cue
lexicon resolves from context: `cp`, `pe`, `ra`, `dm1`.

**2b. Recover the ungroundable terms and audit the result.**

```bash
.venv/bin/python ../../RobustEHR/validation/phenotype/scripts/phenotype_ungrounded.py \
  --anchors ../../RobustEHR/src/robustehr/resources/phenotype_anchors.yaml

.venv/bin/python $R/exp3_corrected/heldout_terms.py --out $R/exp3_corrected/heldout_terms.tsv
.venv/bin/python ../../RobustEHR/validation/phenotype/scripts/phenotype_gap_audit.py \
  --terms $R/exp3_corrected/heldout_terms.tsv
```

The held-out list is generated by a third model that built none of the target's
resources and asked a different question, so a gap cannot be explained away as
one model disagreeing with itself. It is committed, so a later run cannot
quietly regenerate a friendlier one.

Read the gap clusters, not only the rate. Values and units (`lvef 25%`, `bmi 35
kg/m2`) are unreachable by either warrant and no term list fixes them; that is a
limitation to state, not a number to improve.

**2. The corpora.** Thirty conditions, two operators over fifteen phenotypes.

```bash
.venv/bin/python $R/exp3_corrected/gen_exp3_corrected_dataset.py \
  --out data/experiments/exp3_corrected
```

Non-zero exit means an arm failed a gate. The realism gate is exp3bis's,
unchanged. The reach gate is new: an arm whose target declared no diagnosis
evidence, or whose operator treated less than half of what was declared, has not
tested its phenotype, and reporting it as robust is the error this experiment
exists to correct. `--allow-unaimed` writes the corpora anyway, for diagnosing a
bad anchor set and never for a corpus a claim will rest on.

**3. Inference.** Pass every path explicitly. The defaults point at experiment
3's, and that is how the exp3bis run overwrote `exp3_results.json` once already.

```bash
.venv/bin/python $R/exp3/run_exp3.py \
  --experiment exp3_corrected --all-questions \
  --experiments data/experiments \
  --store data/mipa_exp3_corrected/predictions.sqlite \
  --baseline-store data/mipa_exp1/results_run1/predictions.sqlite \
  --out data/mipa_exp3_corrected \
  --results ../../mipa-corrupt/results/measurements/exp3_corrected_results.json \
  --dry-run
```

Drop `--dry-run` to spend. Roughly 36,000 predictions over both Gemma models,
about three hours at the default concurrency, and fully resumable: a killed run
re-reads the store's completed keys and continues.

**4. Tables and reanalysis.**

```bash
.venv/bin/python $R/exp3/exp3_to_csv.py \
  --results ../../mipa-corrupt/results/measurements/exp3_corrected_results.json \
  --out results/exp3_corrected/run1
.venv/bin/python $R/exp3/render_exp3_tables.py \
  --deltas data/mipa_exp3_corrected/deltas.csv \
  --metrics data/mipa_exp3_corrected/phenotype_metrics.csv \
  --results ../../mipa-corrupt/results/measurements/exp3_corrected_results.json \
  --out data/mipa_exp3_corrected/tables
```

Then the analysis side. `common.arms()` and `33_validity.py` already know about
`exp3_corrected` and skip it when its data is absent, so they need no edit.
`34_why.py` is deliberately still pointed at exp3: its references measure what
the original closure declared, which is the subject of that page, and
repointing them would delete the before that the after is compared to.

## Reading the manifests

Each arm's `manifest.json` carries two things exp3 never had.

`reach_gate` reports `declared_by_tier` and `touched_by_tier`. An arm can now
say which evidence it reached rather than only how much: before the tier
existed, a run touching every symptom in the note while leaving the diagnosis
intact reported the same coverage as one that did the opposite.

`set_digests` carries five entries rather than three. `phenotype_anchors.yaml`
and `phenotype_nonspecific.yaml` join the closure and vetting digests, and
`absent` is a reportable value: a corpus built before a resource existed was
built under a different target, and saying so is what keeps two runs comparable
instead of conflated.

## Checking the gate against something it did not build

The reach gate is computed by the anchor layer that does the corrupting, so it
cannot fail in the one way that matters. A target blind to a phenotype is blind
when measuring itself, and reports a clean `1.00` over the few mentions it can
see. Reach is necessary and not sufficient.

`label_coverage.py` asks a question the target has no hand in: of the notes a
human annotator called positive, how many did the arm edit at all? MIPA's labels
share no code with the anchor resource and were fixed long before it existed.

```bash
python experiments/exp3_corrected/label_coverage.py \
  --experiments .../data/experiments/exp3_corrected \
  --notes .../data/golden_notes.csv --labels .../data/golden_labels.csv \
  --out results/measurements/exp3_corrected_label_coverage.json
```

Of 1,575 label-positive notes, 1,543 were edited. The 32 misses split three
ways, and the script reports the split rather than the total, because the total
alone cannot distinguish a broken target from a note with nothing to corrupt.

| | notes | what it is |
|---|---:|---|
| names the diagnosis, untouched | 0 | the only reading that is a defect |
| names an excluded surface | 18 | a disagreement about what the phenotype denotes |
| never writes the condition | 14 | labelled from the structured record |

Venous thromboembolism is one phenotype throughout. `vte_past` and
`vte_complication` are its two questions, prior episode and complicating this
admission, and deep vein thrombosis and pulmonary embolism are two arms aimed at
different parts of its vocabulary. The label columns are not coarse; the arms are
narrower than the phenotype by design.

**The eighteen are worth a decision, not a footnote.** Eight are alcohol use
disorder notes whose only evidence is alcoholic cirrhosis, gastritis or a
polysubstance list; `curated_associated.py` excludes alcohol-attributed organ
disease on the grounds that a coder records it as its own diagnosis, and the
annotators evidently read it as supporting the use disorder. Nine are venous
thromboembolism notes whose only clot is a catheter-related superior vena cava
thrombosis, which is neither of the two forms the arms target and which they are
right to leave alone. One is an obesity note whose sole evidence is `BMI: 35.8`,
a number with no surface to anchor.

**Why the audit carries two patterns.** An audit whose own pattern is narrow
enough always reports zero. `STRICT` asks whether the note writes the diagnosis;
`WIDE` asks whether it writes anything a reader might argue for. The first draft
of this script had only the strict pattern and reported zero misses everywhere,
which was true and misleading in the same breath. The gap between the columns is
the finding.

## A digest moved without the target moving

The manifests in this experiment record `phenotype_anchors.yaml` at file digest
`98f93f8d4ef20ae9`. The resource that ships today hashes to `ca95c0d2837e44ab`.
The corpora are not stale and nothing needs regenerating.

On 2026-09-23 the resource's provenance ledger was corrected: a duplicate entry
removed, the passes renumbered into build order, and `vetted_by` changed from
`llm` to `llm+hand` because a hand-curated pass had in fact run. None of that
touches targeting. The `phenotypes:` blocks, which are the only thing that
decides which spans an arm can edit, are byte-identical across the change and
hash to `9580e70108b3ce06`.

This is a defect in what the manifest chose to record rather than in the corpora.
A whole-file digest answers "are these the same bytes"; a manifest is asking
"was this built against the same target", and the two diverge exactly when a
provenance error is corrected. Later runs record both, as
`phenotype_anchors.yaml` and `phenotype_anchors.targeting`, so an equivalent
target is provable without re-running inference.

