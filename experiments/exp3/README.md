# exp3: the Experiment 3 runner, and a superseded generator

Two different things live here.

**Used by the paper.** `run_exp3.py` asks the model the phenotype questions of
an Experiment 3 corpus, and `exp3_to_csv.py` and `render_exp3_tables.py`
tabulate the answers. For the paper's Experiment 3 they are run with
`--experiment exp3_corrected`; the commands are in
[`../exp3_corrected/README.md`](../exp3_corrected/README.md).

**Not used by the paper.** `gen_exp3_dataset.py` is the first corpus generator
for Experiment 3. It is superseded by
[`../exp3_corrected/gen_exp3_corrected_dataset.py`](../exp3_corrected/gen_exp3_corrected_dataset.py):
its OCR arm was uncapped and its target missed most written diagnoses. See
[`../README.md`](../README.md).
