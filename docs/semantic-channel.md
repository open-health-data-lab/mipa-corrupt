# Experiments 4 and 5 — the semantic channel

## Why there is a semantic channel

Experiments 1, 2 and 3 all corrupt **legibility**. `input.typo` and
`input.ocr_confusion` damage the surface of a word and leave its sense intact:
`Hypertenslon` still reads as hypertension to a human and to a capable model.
That is why corrupting a phenotype's *entire* evidence set at saturating dose
costs the 12b model a median 0.013 macro-F1 — a result that reads as robustness
and is better described as a gate that was never opened.

No arm in experiments 1–3 changes what a note **says**. Assertion cues are the
smallest perturbation that does: `no evidence of DVT` and `evidence of DVT`
differ by two words and assert opposite things. Measured over the 500 evaluated
notes, **40% of phenotype-evidence mentions carry an assertion cue** (negation
9.8%, temporality 23.4%, experiencer 5.1%, uncertainty 5.3%).

The two experiments complete a 2×3 design:

| | no aim | pooled aim | phenotype aim |
|---|---|---|---|
| **surface** | exp1 | exp2 | exp3 / exp3bis |
| **semantic** | *not run* | **exp4** | **exp5** |

The semantic/no-aim cell is deliberately empty: flipping every cue in a note
regardless of what it governs is a 67-edit-per-note perturbation with no clinical
reading, and the comparison that matters is aimed-semantic against
aimed-surface.

## What each experiment does

### Experiment 4 — pooled, one arm per cue class

`experiments/exp4/gen_exp4_dataset.py`. Four arms — `negation`, `uncertainty`,
`temporality`, `experiencer` — each rewriting the cues that govern **any** panel
phenotype's evidence. The semantic analogue of experiment 2's clinical aim.

All 16 protocol questions are scored per arm, so exp4 produces a macro-F1
directly comparable to experiments 1 and 2, which experiment 3 never did. That is
what `run_exp3.py --all-questions` exists for: exp4's condition names carry no
phenotype, so `phenotype_of()` cannot recover one and all 16 apply.

4 arms × 16 questions × 500 notes × 2 models = **64,000 predictions**.

### Experiment 5 — per phenotype, all four classes composed

`experiments/exp5/gen_exp5_dataset.py`. Fifteen arms, `assertion_<phenotype>`,
each applying all four cue operators to the cues governing that one phenotype's
evidence, scoring only that phenotype's question(s). Structurally identical to
exp3bis, including untreated notes as the within-arm control.

18 (condition, question) pairs × 500 × 2 = **18,000 predictions**.

**Composition, not staging.** `runner.compose_operators` has all four operators
propose against the pristine document and resolves the union once, so the stored
edit script still references original offsets and replays against the original
note. A four-stage pipeline would put each stage's edits in a different
coordinate system and break that; `stage_index` is a seed field, not a pipeline.
Zero edits were dropped to overlap in any of the 15 conditions — a property of
the detector rather than luck, since medspaCy prunes overlapping modifier matches
across categories, so `no history of` fires as one NEGATED_EXISTENCE cue.

## How the aim works

`Scope(target=PhenotypeEvidence(name))` — what experiment 3 uses — selects
**zero** cues. `_by_target` tests the unit's own span, and for a cue-flip
operator the unit *is* the cue; the `denies` in `denies hypertension` is not
itself evidence for hypertension. The run completes, the corpus comes out
byte-identical to the baseline, and only `eligible_n = 0` in the dose ledger
says so.

RobustEHR gained a target for this:

```python
Scope(target=Governs(PhenotypeEvidence("hypertension")))   # exp5
Scope(target=Governs(PhenotypeEvidence()))                 # exp4, any panel phenotype
```

`governs(a)` admits a span inside a cue whose ConText scope covers a span that
`a` admits. It is a lookup rather than a proximity window — ConText already
records which cues produced each span's attributes — so nothing picks a
character distance. The generator passes the index explicitly:

```python
assertions = qualify(text, [e.span for e in idx.evidence])
apply_operator(..., phenotypes=idx, assertions=assertions)
```

Omit it and the runner **raises** rather than reporting zero, because a
configuration error must not present as a finding.

The scoping is surgical: filtering forward and backward cues to those governing a
phenotype mention keeps **179 of 2,147 cues, 8%** — roughly one to two words per
note, while still reaching most notes.

## Why churn is the endpoint and F1 is not

Both experiments are **reference-altering by design**, which the library declares
in its own vocabulary: all four operators carry
`Contract.REFERENCE_ALTERING_BY_DESIGN`.

Once `no evidence of` is gone, the note no longer supports the answer the golden
label records. An F1 against that label therefore measures *drift from the answer
the clean note supported*, not error. So:

* **primary** — assignment churn, with its gained/lost decomposition
* **secondary** — ΔmacroF1, reported and explicitly labelled as drift

This is not a hedge. It is the study's thesis at its sharpest: the pooled
negation arm costs **0.017 macro-F1**, less than experiment 1's worst arm, while
moving 1.45% of assignments at 3.3× the noise floor with **100 gained against 16
lost**. The score says nothing happened; 84 patients entered cohorts they do not
belong to.

## The gate, and why exp3bis's does not transfer

exp3bis gates on characters changed per token: an arm may carry a
noise-robustness claim only if the median is 1 and no token loses more than half.
A whole-word substitution changes most of the token **by design** —
`denies → reports` is the intended perturbation — so every semantic arm would
score `ablation` and the gate would mean nothing.

The gate here is **detector-and-dose** instead. Each manifest records
`eligible_n`, `applied_n`, treated notes, the cue literals actually edited, and
the operator's own published validation string verbatim. Generation exits
non-zero if any arm has zero eligible cues, because a null on zero cues is not
robustness.

Detector quality is wildly uneven and has to be carried beside every number:

| cue class | validation |
|---|---|
| negation | **F1 0.9289** negated-class on the NegEx gold, κ 0.74 |
| uncertainty | F1 0.2511, BioScope abstracts only — out of domain |
| temporality | no published gold; F1 0.29 held-out MIMIC, κ 0.41 |
| experiencer | **no gold, κ 0.22** — cut from v1, reinstated by explicit decision |

A null in the uncertainty or experiencer arm cannot be distinguished from the
detector never firing.

## What the prompt can and cannot answer

`src/mipa/protocol.py` decides which perturbations are even answerable. Two
clauses matter:

> "determine if the history, symptoms and treatments described indicate that
> **the patient has** {phenotype}" … "Only output 1 if the evidence is
> **conclusive**"

So negation, uncertainty and experiencer are answerable for all 16 questions.
**Temporality is not.** `{phenotype}` is interpolated with
`PHENOTYPE_DESCRIPTIONS`, and only four questions carry a temporal qualifier —
`vte_past`, `vte_complication`, `c_diff_past`, `c_diff_complication`.
`Hypertension` and `Obesity` are bare concepts, so a temporality flip on the
other twelve is **null by construction** and is reported as a pre-registered
negative control rather than a finding.

## Running them

Working directory must be the populated data checkout — `data/umls_facets.json`
is a hardcoded relative path.

```bash
cd _withdata/_RobustEHR_withdata
uv pip install -e ../../mipa-corrupt          # mipa is not installed by default

python ../../mipa-corrupt/experiments/exp4/gen_exp4_dataset.py --out data/experiments/exp4
python ../../mipa-corrupt/experiments/exp5/gen_exp5_dataset.py --out data/experiments/exp5

R=../../mipa-corrupt/experiments/exp3/run_exp3.py
python $R --experiment exp4 --all-questions \
  --experiments data/experiments --store data/mipa_exp4/predictions.sqlite \
  --baseline-store data/mipa_exp1/results_run1/predictions.sqlite \
  --out data/mipa_exp4 --results results/measurements/exp4_results.json --dry-run
python $R --experiment exp5 \
  --experiments data/experiments --store data/mipa_exp5/predictions.sqlite \
  --baseline-store data/mipa_exp1/results_run1/predictions.sqlite \
  --out data/mipa_exp5 --results results/measurements/exp5_results.json --dry-run
```

**Pass `--out`, `--store` and `--results` explicitly.** The defaults point at
experiment 3's paths, and the exp3bis run overwrote
`results/measurements/exp3_results.json` that way. `--baseline-store` must be named
too: the default `run1/predictions.sqlite` does not exist.

Drop `--dry-run` to spend. Both runs returned `cost $0.00` on free-tier Gemma
routing; 82,000 predictions, 100% parsed.

## Appropriateness — read this before quoting a result

An OCR misread is self-evidently something scanners do. `denies → reports` is
not. Whether these arms *model* an incident or merely *bound* one was adjudicated
before any prediction was spent — 50 edits per arm on mechanism, ecology and
fidelity — in `mipa-corrupt-analysis/reanalysis/scripts/24_appropriateness.py`,
with the results in `tables/07_exp4_deltas/appropriateness.md`.

**The defensible arm and the validated arm are the same arm.** Negation is 74%
deletions — a dropped `no` is what truncation and a lost line break produce — and
its detector is the only one validated in domain. The other three are pure
substitution, which nothing accidental performs, and their detectors are
unvalidated or out of domain.

So the claim rests on negation; the other three bound it.

The audit also found two library defects, both fixed rather than reported:
`uncertainty_flip` enumerated HYPOTHETICAL cues and rewrote care plans into facts
(`as needed → scheduled` changes a medication order), and all four operators
edited ConText scope terminators. One limitation stands: the header segmenter
misses uppercase headers written without a colon, so 5 of 950 sampled edits
landed on `PAST MEDICAL HISTORY`. Fixing that would invalidate experiments 1
through 3bis, so it is reported as measured 0.5% contamination of the temporality
arm.
