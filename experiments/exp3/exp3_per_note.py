"""Per-note predictions and operational rows for exp3.

`analyze` would emit these, but it computes robustness deltas first and exp3's
store holds no baseline arm — exp3 was paired against run1's baseline, which
lives in the exp1/exp2 store. So the delta step raises and the per-note export
never runs.

The per-note data is independent of that: it is the store's own rows. This
calls the same `mipa_metrics` writers `analyze` uses, so the files are
byte-format-identical to exp1's and exp2's, and skips only the step that has no
reference arm to work from.
"""
import argparse
from pathlib import Path

from mipa import metrics as mipa_metrics
from mipa import sample as mipa_sample
from mipa.store import PredictionStore

# Parameterised: the hardcoded paths meant a second experiment could only be
# exported by editing the file, and editing it is how the wrong store gets read
# into the right directory name.
parser = argparse.ArgumentParser(description=__doc__ or "per-note export")
parser.add_argument("--store", type=Path, default=Path("data/mipa_exp3/predictions.sqlite"))
parser.add_argument("--labels", type=Path, default=Path("data/golden_labels.csv"))
parser.add_argument("--out", type=Path, default=Path("results/exp3/run1"))
args = parser.parse_args()

store = PredictionStore(args.store)
labels = mipa_sample.read_labels(args.labels)
out = args.out
out.mkdir(parents=True, exist_ok=True)

written = [
    mipa_metrics.write_csv_gz(
        out / "predictions.csv.gz",
        mipa_metrics.prediction_rows(store.iter_rows(), labels),
    ),
    mipa_metrics.write_csv_gz(out / "operational.csv.gz", store.operational_rows()),
    mipa_metrics.write_csv(out / "parse_failures.csv", list(store.iter_failures())),
]
for path in written:
    p = Path(path) if not isinstance(path, Path) else path
    print(f"  wrote {p}  ({p.stat().st_size:,} bytes)")
print(f"\nstore: {store.count():,} predictions, cost ${store.cost_so_far():.4f}")
store.close()
