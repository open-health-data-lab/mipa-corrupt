# Experiments

## Which Experiment 3 is in the paper

**`exp3_corrected/`.** The name is historical: Experiment 3 was run three
times, and only the third is reported. In the paper it is simply
"Experiment 3".

| Directory | Version | Phenotype target | Operators | In the paper |
|---|---|---|---|---|
| `exp3/gen_exp3_dataset.py` | first | concept set only | typographical errors; OCR **uncapped** | No. Superseded |
| `exp3bis/` | second | concept set only | OCR capped at one character per word (no typographical arm) | No. Superseded |
| **`exp3_corrected/`** | **third** | **concept set and the diagnosis as written** | **typographical errors; OCR capped at one character per word** | **Yes: this is Experiment 3** |

Why the first two were replaced:

- **`exp3`** dosed OCR per character at full rate, which rewrote every
  confusable character of a word at once. The word was replaced by noise, not
  misread.
- **`exp3bis`** capped OCR at one character per word, which fixed the dose. It
  kept the first target, which selected a word only if the concept matcher
  linked it to a concept in the phenotype's set. That target missed most
  written diagnoses: abbreviations such as HTN or DVT, causative organisms, and
  qualifiers such as "preserved ejection fraction". It also has no
  typographical-error arm, so it cannot be compared with Experiments 1 and 2 on
  the operator the paper leads with.
- **`exp3_corrected`** keeps the cap and adds the diagnosis as written to the
  target, so the words that name the phenotype are among the words corrupted.

A quick way to tell them apart in the data: the paper's Experiment 3 has 30
corpora (15 phenotypes × 2 operators) averaging 7.6 corrupted words per note
under typographical errors and 9.0 under capped OCR. `exp3bis` has 15 corpora,
all capped OCR.

`exp3/` is still needed: its `run_exp3.py`, `exp3_to_csv.py` and
`render_exp3_tables.py` are the prediction runner and table renderers that
`exp3_corrected` uses, selected with `--experiment exp3_corrected`.

## Everything here

| Directory | What it is | In the paper |
|---|---|---|
| `exp1_exp2/` | Corpus generation for Experiments 1 (whole note) and 2 (clinical words) | Yes |
| `exp3_corrected/` | Experiment 3: corpus generation, checks on the phenotype targets, reading sample | Yes |
| `exp3/` | Prediction runner and table renderers for Experiment 3; the first, superseded generator | Runner and renderers only |
| `exp3bis/` | Second, superseded version of Experiment 3 | No |
| `exp4/`, `exp5/` | Corruption of negation and other assertion cues | No |
| `causal_probe/` | Whether redacting a phenotype's evidence moves the model's answer | No |
