# Releasing the corpora: replay, not redistribution

The corrupted corpora of Experiments 1, 2 and 3 are MIMIC-IV text and are not
distributed. What a credentialed reader needs to rebuild them is, per
condition, an edit script (`edits.jsonl`), a dose table (`dose.jsonl`) and a
manifest, plus their own copy of the notes and RobustEHR 0.2.0:

```bash
robustehr replay --run <condition directory> --corpus <their notes.csv>
```

Replay applies the stored edits and checks every corrupted note against the
SHA-256 the original run recorded.

## Export the edit scripts before sharing them

The study's corpora were written by pre-release builds of RobustEHR, which
stored a typographical error as the whole word with one letter changed. Those
files hold the notes' own words and should not be shared as they are.
`export_ledgers.py` rewrites each one with every replacement stored as its
minimal difference (one offset and one letter for a typographical error),
replays the result against the clean notes, and writes a condition only if
every note reproduces its recorded hash:

```bash
cd <data checkout>          # where data/experiments and data/golden_notes.csv live
python <this repo>/release/export_ledgers.py --out data/release_ledgers
```

It covers `exp1`, `exp2` and `exp3_corrected`: 63 conditions. Allow a few
hours; the OCR conditions of Experiment 1 hold several hundred thousand edits
each. `index.json` in the output lists what was verified.

The exported scripts copy no span of a note. They are still data derived from
MIMIC-IV, because an offset says where a word was, so share them with
credentialed users under the PhysioNet agreement. RobustEHR's
`docs/run-artifact.md` lists what each operator's edits imply.

## What has been checked, and what has not

Checked with RobustEHR 0.2.0 installed from its public tag:

- Replay to the recorded hashes of five stored conditions as generated:
  Experiment 1 typographical errors (low), Experiment 2 OCR (high), and
  Experiment 3 typographical errors (hypertension, HFrEF) and capped OCR
  (HFrEF).
- Export, with its replay check, of eight Experiment 1 conditions.
- Regeneration from the seed of the two Experiment 3 hypertension arms. The
  typographical-error arm is byte-identical to the study's on all 500 notes.
  The capped-OCR arm selects the same words and makes the same number of edits
  but draws different characters.

Not run to completion: the export of all 63 conditions, and regeneration of
the other 14 phenotypes. The statements in the paper's Appendix A4 that every
corpus replays, and that the Experiment 3 typographical-error arms regenerate
byte for byte, rest on the checks above and on the design (replay does not
depend on the operator that proposed an edit). Run the export in full before
any edit script leaves the building; it is the check.

## Why regeneration does not give the identical corpora

Every random draw is seeded with, among other things, the package's seed
specification and the operator's version.

- Experiments 1 and 2 were generated in August 2026, when the package was
  named `ehrrobust`; the seed specification carried that name.
- The OCR operator moved from version 2.0.0 to 2.1.0 after Experiment 3 was
  generated. Its confusion table did not change between the two.
- The OCR table itself was extended between Experiments 1 and 2 and
  Experiment 3, from 30 character rows to 52, adding most uppercase letters.

So RobustEHR 0.2.0 regenerates corpora of the same design and dose with
different draws, except where neither input moved: the typographical-error
arms of Experiment 3.
