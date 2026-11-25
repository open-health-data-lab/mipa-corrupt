"""Gather every generated table into one organised tree.

The tables are written beside the corpora and measurements they describe, which
is right for provenance and wrong for reading: the baseline sits in one
directory, 33 deltas in 33 others, the targeting evidence under `docs/`. Nobody
can hold that in their head, and a collaborator handed the repository cannot
find the six files that matter.

This copies them into `data/tables/` under subdirectories that follow the
questions rather than the pipeline:

    01_baseline/      what the clean corpus looks like (all 1,388 notes)
    02_sample/        the same, over the 500 notes actually evaluated
    03_targeting/     did Experiment 2 hit clinical content, and how is
                      "clinical" defined
    04_exp1_deltas/   what each untargeted corruption did to the text
    05_exp2_deltas/   the same for the clinically-targeted arm
    06_exp3_deltas/   experiment 3: per-phenotype full-dose targeted
                      corruption vs baseline (F1 deltas, flips, scorecard)

Copies, deliberately. The originals stay canonical — regenerate with
`regen_tables.py`, `sample_table1.py` and `targeting_showcase.py`, then re-run
this. A missing source is reported rather than skipped silently, because a
quietly incomplete set is worse than an obviously incomplete one.

    python analysis/collect_tables.py
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

EXPERIMENTS = Path("data/experiments")

#: (destination subdirectory, source path, destination filename). Sources that
#: do not exist are reported at the end rather than skipped quietly.
SINGLES: tuple[tuple[str, Path, str], ...] = (
    ("01_baseline", EXPERIMENTS / "baseline" / "table1_short.md", "table1_short.md"),
    ("01_baseline", EXPERIMENTS / "baseline" / "table1.md", "table1.md"),
    ("01_baseline", EXPERIMENTS / "baseline" / "table1.json", "table1.json"),
    (
        "01_baseline",
        EXPERIMENTS / "baseline" / "phenotype_density.md",
        "phenotype_density.md",
    ),
    (
        "02_sample",
        Path("data/mipa_exp1/table1_sample/table1_short.md"),
        "table1_short.md",
    ),
    ("02_sample", Path("data/mipa_exp1/table1_sample/table1.md"), "table1.md"),
    ("02_sample", Path("data/mipa_exp1/table1_sample/table1.json"), "table1.json"),
    (
        "02_sample",
        Path("data/mipa_exp1/table1_sample/sample_appropriateness.md"),
        "sample_appropriateness.md",
    ),
    (
        "02_sample",
        Path("data/mipa_exp1/table1_sample/phenotype_density.md"),
        "phenotype_density.md",
    ),
    (
        "03_targeting",
        Path("results/measurements/targeting_showcase.md"),
        "targeting_showcase.md",
    ),
    ("03_targeting", EXPERIMENTS / "edit_placement.md", "edit_placement.md"),
    (
        "03_targeting",
        Path("results/measurements/edit_placement.json"),
        "edit_placement.json",
    ),
    # Experiment 3: per-phenotype full-dose targeted corruption vs baseline.
    # Rendered by experiments/exp3/render_exp3_tables.py from data/mipa_exp3/deltas.csv.
    ("06_exp3_deltas", Path("data/mipa_exp3/tables/README.md"), "README.md"),
    ("06_exp3_deltas", Path("data/mipa_exp3/tables/f1_deltas.md"), "f1_deltas.md"),
    ("06_exp3_deltas", Path("data/mipa_exp3/tables/recall_deltas.md"), "recall_deltas.md"),
    ("06_exp3_deltas", Path("data/mipa_exp3/tables/flips.md"), "flips.md"),
    (
        "06_exp3_deltas",
        Path("data/mipa_exp3/tables/density_vs_impact.md"),
        "density_vs_impact.md",
    ),
    (
        "06_exp3_deltas",
        Path("data/mipa_exp3/tables/probe_scorecard.md"),
        "probe_scorecard.md",
    ),
    ("06_exp3_deltas", Path("data/mipa_exp3/deltas.csv"), "deltas.csv"),
    ("06_exp3_deltas", Path("data/mipa_exp3/phenotype_metrics.csv"), "phenotype_metrics.csv"),
)


def clinical_share(directory: Path) -> float | None:
    """Share of content tokens the targeting rule calls clinical."""
    table = directory / "table1.json"
    if not table.exists():
        return None
    block = json.loads(table.read_text(encoding="utf-8"))["by_level"].get("clinical_content")
    if not block:
        return None
    clinical, other = block["clinical"]["total"], block["non_clinical"]["total"]
    return clinical / (clinical + other) if clinical + other else None


def collect(out: Path) -> tuple[list[tuple[str, str, float | None]], list[Path]]:
    """Copy everything in. Returns the delta rows and anything missing."""
    missing: list[Path] = []
    for subdir, source, name in SINGLES:
        if not source.exists():
            missing.append(source)
            continue
        (out / subdir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out / subdir / name)

    rows: list[tuple[str, str, float | None]] = []
    for experiment, subdir in (("exp1", "04_exp1_deltas"), ("exp2", "05_exp2_deltas")):
        for directory in sorted((EXPERIMENTS / experiment).glob("*/*")):
            delta = directory / "table1_delta.md"
            if not delta.exists():
                continue
            corruption, severity = directory.parent.name, directory.name
            (out / subdir).mkdir(parents=True, exist_ok=True)
            name = f"{corruption}_{severity}_delta.md"
            shutil.copy2(delta, out / subdir / name)
            rows.append((experiment, f"{corruption}/{severity}", clinical_share(directory)))
    return rows, missing


def readme(rows, base: float | None, sample: float | None) -> str:  # type: ignore[no-untyped-def]
    order = {"low": 0, "medium": 1, "high": 2}
    L = [
        "# Generated tables",
        "",
        "Copies, gathered for reading. The originals live beside the corpora and",
        "measurements they describe and stay canonical — regenerate with",
        "`experiments/exp1_exp2/regen_tables.py`,",
        "`experiments/exp1_exp2/sample_table1.py`, `analysis/table1_short.py`,",
        "`analysis/sample_appropriateness.py` and",
        "`analysis/targeting_showcase.py`, then re-run",
        "`analysis/collect_tables.py`.",
        "",
        "| Directory | What it answers |",
        "|---|---|",
        "| `01_baseline/` | What the clean corpus looks like, over all 1,388 notes. "
        "`table1_short.md` is the one-page version to print; `table1.md` is the full "
        "auditable characterisation; `phenotype_density.md` is concepts declared vs "
        "observed per phenotype, with the UMLS validation and category breakdown |",
        "| `02_sample/` | The same table over the **500 notes actually evaluated** — the "
        "denominator the F1 results share. `sample_appropriateness.md` compares the two "
        "populations phenotype by phenotype; `phenotype_density.md` is the concept "
        "density and coverage the corruption experiments acted on |",
        "| `03_targeting/` | Did Experiment 2 hit clinical content? Includes the class "
        "definitions and their measured error rates |",
        "| `04_exp1_deltas/` | What each **untargeted** corruption did to the text (27) |",
        "| `05_exp2_deltas/` | The same for the **clinically-targeted** arm (6) |",
        "| `06_exp3_deltas/` | Experiment 3: per-phenotype **full-dose** targeted corruption vs "
        "baseline F1 — headline deltas, recall, paired flips, density-vs-impact, and the "
        "probe scorecard |",
        "",
        "## Clinical content, at a glance",
        "",
        "Share of content tokens the `ClinicalSalience` rule calls clinical. A",
        "corruption that destroys clinical content pulls it *down*; the gap between the",
        "two experiments at matched severity is the targeting working. Class",
        "definitions and the rule's measured precision (0.820) are in",
        "`03_targeting/targeting_showcase.md`.",
        "",
    ]
    if base is not None:
        L.append(f"* Baseline, all 1,388 notes: **{base:.1%}**")
    if sample is not None:
        L.append(f"* Baseline, the 500 evaluated notes: **{sample:.1%}**")
    L += [
        "",
        "| Corruption | Severity | exp1 (untargeted) | exp2 (targeted) |",
        "|---|---|---:|---:|",
    ]
    by_cond: dict[tuple[str, str], dict[str, float | None]] = {}
    for experiment, cond, share in rows:
        corruption, severity = cond.rsplit("/", 1)
        by_cond.setdefault((corruption, severity), {})[experiment] = share
    for (corruption, severity), arms in sorted(
        by_cond.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 3))
    ):
        if "exp2" not in arms:  # structural corruptions run untargeted only
            continue
        a, b = arms.get("exp1"), arms.get("exp2")
        fa = f"{a:.1%}" if a is not None else "—"
        fb = f"**{b:.1%}**" if b is not None else "—"
        L.append(f"| `{corruption}` | {severity} | {fa} | {fb} |")
    L += [
        "",
        "Experiment 1 also covers seven structural corruptions with no targeted",
        "counterpart; those are in `04_exp1_deltas/` and are absent from the table above",
        "because there is nothing to compare them against.",
        "",
        "## The other kind of delta",
        "",
        "These describe what corruption did to the **text**. What it did to the",
        "**model** is separate: `results/exp2/run1/robustness_deltas.csv`, with",
        "per-phenotype detail in `phenotype_metrics.csv`. Both are needed — this folder",
        "says what was damaged, that file says whether it mattered.",
        "",
        "Note that those result files carry **both experiments**: exp1 conditions appear",
        "unprefixed, exp2 conditions as `exp2/...`. Grouping on `corruption` alone",
        "silently merges the two arms.",
        "",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/tables"))
    args = ap.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    rows, missing = collect(args.out)
    base = clinical_share(EXPERIMENTS / "baseline")
    sample = clinical_share(Path("data/mipa_exp1/table1_sample"))
    (args.out / "README.md").write_text(readme(rows, base, sample), encoding="utf-8")

    for directory in sorted(p for p in args.out.iterdir() if p.is_dir()):
        print(f"  {directory.name}/  {len(list(directory.iterdir()))} file(s)")
    print(f"\nwrote {args.out}/README.md")
    if missing:
        print(f"\n{len(missing)} source(s) MISSING — regenerate and re-run:")
        for path in missing:
            print(f"  {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
