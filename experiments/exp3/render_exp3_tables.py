#!/usr/bin/env python
"""Render the experiment-3 manuscript tables from the run's delta artifact.

Reads `data/mipa_exp3/deltas.csv` (written by `experiments/exp3/run_exp3.py`) and
renders the per-phenotype perturbation-vs-baseline story four ways, each a
different reader's question:

    f1_deltas.md        how much did F1 move — the headline manuscript table
    recall_deltas.md    the sensitive axis: recall is what full-dose targeted
                        corruption attacks (lost positives), precision barely
                        moves
    flips.md            the paired per-note view: positives lost vs gained,
                        read against the 0.4% test-retest noise floor
    probe_scorecard.md  predicted vs observed: the causal probe pre-registered
                        which phenotypes should move (H3a) and which should
                        not (H3b); this table scores those predictions

Rows are grouped by the probe's tiers so the table reads as the hypothesis
does. Every file carries the set digests the treatment was fingerprinted
with. Aggregates only — no note text, no identifiers beyond phenotype names —
so the output is licence-safe and lives beside the store it derives from;
`analysis/collect_tables.py` copies it into the shared `data/tables/` tree.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

#: Probe-derived expectation per phenotype (docs/causal-probe-panel.md).
TIERS = {
    "concept-channel-carried (H3a: expect F1 to drop)": [
        "depression", "obesity", "hypertension", "dementia",
        "rheumatoid_arthritis", "hfpef", "type_2_diabetes",
    ],
    "moderate / ceiling-only": [
        "deep_vein_thrombosis", "alcohol_use_disorder", "type_1_diabetes",
    ],
    "resistant (H3b: expect no change beyond noise)": [
        "hfref", "metastatic_cancer", "clostridioides_difficile",
        "pulmonary_embolism", "systemic_lupus_erythematosus",
    ],
}
OPERATORS = ("typographical_errors", "homoglyph_substitutions", "ocr_capped")
NOISE = ("test-retest noise floors: 12b 0.4% (5/1,125), 4b 0.8% (9/1,125) — "
         "causal_probe_retest{,_4b}.json; on 500 notes ≈2 and ≈4 flips of noise "
         "respectively, so 4b's small resistant-tier drifts are borderline")


def phenotype_of(condition: str) -> str:
    corruption = condition.split("/")[1]
    for tier in TIERS.values():
        for name in sorted(tier, key=len, reverse=True):
            if corruption.endswith(f"_{name}"):
                return name
    raise ValueError(condition)


def operator_of(condition: str) -> str:
    corruption = condition.split("/")[1]
    return next(op for op in OPERATORS if corruption.startswith(op))


def fmt(x, digits=3, signed=False):
    if x in (None, ""):
        return "—"
    v = float(x)
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return s


def notes_with_edits(manifest: dict, directory: Path | None) -> int:
    """Notes this arm actually edited, however the generator recorded it.

    exp3 wrote `notes_with_edits` into a hand-built manifest. Arms written by
    `store.write_run` — exp3bis and everything after — do not carry the key,
    because the dose ledger already holds one record per note and a count
    derived from it cannot drift from the ledger the way a copied integer can.
    So it is read where present and counted where not, and an arm with neither
    reports zero rather than raising.
    """
    if "notes_with_edits" in manifest:
        return int(manifest["notes_with_edits"])
    if directory is None:
        return 0
    dose = directory / "dose.jsonl"
    if not dose.exists():
        return 0
    edited = 0
    with dose.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                edited += int(json.loads(line).get("applied_n", 0)) > 0
            except json.JSONDecodeError:
                continue
    return edited


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deltas", type=Path, default=Path("data/mipa_exp3/deltas.csv"))
    parser.add_argument(
        "--metrics", type=Path, default=Path("data/mipa_exp3/phenotype_metrics.csv")
    )
    parser.add_argument(
        "--results", type=Path, default=Path("results/measurements/exp3_results.json")
    )
    parser.add_argument("--out", type=Path, default=Path("data/mipa_exp3/tables"))
    args = parser.parse_args(argv)

    with args.deltas.open(newline="", encoding="utf-8") as handle:
        deltas = list(csv.DictReader(handle))
    with args.metrics.open(newline="", encoding="utf-8") as handle:
        metrics = {(r["model"], r["condition"]): r for r in csv.DictReader(handle)}
    digests = json.loads(args.results.read_text(encoding="utf-8")).get("set_digests", {})
    models = sorted({r["model"] for r in deltas})
    # Only the operators this run actually carries. The layout was inherited
    # from a run that included homoglyph substitution, and exp3_corrected does
    # not, so every homoglyph cell rendered as an em dash in every table -- a
    # column of nothing that a reader has to work out is not a measurement.
    present = {operator_of(r["condition"]) for r in deltas}
    globals()["OPERATORS"] = tuple(op for op in OPERATORS if op in present) or OPERATORS
    short = {m: m.split("/")[-1].replace("gemma-3-", "") for m in models}

    # (phenotype, question, operator, model) -> delta row.
    #
    # The question belongs in the key. Three targets are scored on two questions
    # each -- C. difficile on a prior episode and on an infection complicating
    # this admission, venous thromboembolism on the same pair -- and keying on
    # the arm alone made the second row overwrite the first silently. Twelve of
    # the seventy-two measured rows never reached a rendered table, and the ones
    # that survived were whichever the CSV happened to list last.
    #
    # It matters because the two can move in opposite directions: for C.
    # difficile under capped OCR the complication question loses 0.017 while the
    # prior-episode question gains 0.028. A reader shown one of those has been
    # shown the wrong half, not a rounded version of the whole.
    cell: dict[tuple[str, str, str, str], dict] = {}
    questions: dict[str, list[str]] = {}
    for r in deltas:
        pheno = phenotype_of(r["condition"])
        cell[(pheno, r["phenotype"], operator_of(r["condition"]), r["model"])] = r
        if r["phenotype"] not in questions.setdefault(pheno, []):
            questions[pheno].append(r["phenotype"])
    for qs in questions.values():
        qs.sort()

    args.out.mkdir(parents=True, exist_ok=True)
    provenance = (
        f"\nSets: vetting `{digests.get('phenotype_vetting.yaml', '?')}`, closure "
        f"`{digests.get('phenotype_closure.yaml', '?')}`. Baseline: run1. {NOISE}.\n"
    )

    def tier_table(writer, metric_cols) -> list[str]:
        lines = []
        for tier, phenos in TIERS.items():
            lines.append(f"\n**{tier}**\n")
            lines.append(writer.header)
            lines.append(writer.rule)
            for pheno in phenos:
                lines.append(writer.row(pheno))
        return lines

    # ---- f1_deltas.md ----------------------------------------------------
    lines = [
        "# Experiment 3 — ΔF1 per phenotype, full-dose targeted corruption",
        "",
        "Each cell: that phenotype's question over all 500 sampled notes under",
        "one condition, minus the same question's baseline F1 (same notes, same",
        "model). Rows grouped by the causal probe's pre-registered expectation.",
        provenance,
    ]
    for tier, phenos in TIERS.items():
        lines.append(f"\n### {tier}\n")
        head = "| target phenotype | question | n+ |"
        for m in models:
            for op in OPERATORS:
                head += f" {short[m]} {op.split('_')[0]} ΔF1 |"
        for m in models:
            head += f" {short[m]} baseline F1 |"
        lines.append(head)
        lines.append("|" + "---|" * (head.count("|") - 1))
        for pheno in phenos:
          for question in questions.get(pheno, []):
            some = next(
                (cell[(pheno, question, op, m)] for op in OPERATORS for m in models
                 if (pheno, question, op, m) in cell), None)
            if some is None:
                continue
            npos = metrics.get((models[0], some["condition"]), {}).get("n_pos", "—")
            row = f"| {pheno} | {question} | {npos} |"
            for m in models:
                for op in OPERATORS:
                    r = cell.get((pheno, question, op, m), {})
                    d = r.get("delta_f1")
                    mark = "**" if d not in (None, "") and abs(float(d)) >= 0.05 else ""
                    row += f" {mark}{fmt(d, signed=True)}{mark} |"
            for m in models:
                r = next((cell[(pheno, question, op, m)] for op in OPERATORS
                          if (pheno, question, op, m) in cell), {})
                row += f" {fmt(r.get('baseline_f1'))} |"
            lines.append(row)
    (args.out / "f1_deltas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- recall_deltas.md ------------------------------------------------
    lines = [
        "# Experiment 3 — recall, the axis the treatment attacks",
        "",
        "Full-dose corruption of a phenotype's evidence can only push its",
        "positives toward negative, so recall is where the effect concentrates;",
        "precision moves little (false positives require GAINING a diagnosis",
        "from corrupted text). Baseline → corrupted recall per arm.",
        provenance,
    ]
    for tier, phenos in TIERS.items():
        lines.append(f"\n### {tier}\n")
        head = "| target phenotype | question |"
        for m in models:
            for op in OPERATORS:
                head += f" {short[m]} {op.split('_')[0]} |"
        lines.append(head)
        lines.append("|" + "---|" * (head.count("|") - 1))
        for pheno in phenos:
          for question in questions.get(pheno, []):
            row = f"| {pheno} | {question} |"
            for m in models:
                for op in OPERATORS:
                    r = cell.get((pheno, question, op, m), {})
                    if not r:
                        row += " — |"
                    else:
                        row += (
                            f" {fmt(r.get('baseline_recall'))} → "
                            f"{fmt(r.get('corrupted_recall'))} |"
                        )
            lines.append(row)
    (args.out / "recall_deltas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- flips.md --------------------------------------------------------
    lines = [
        "# Experiment 3 — paired per-note flips vs baseline",
        "",
        "`lost` = baseline predicted positive, corrupted predicts negative —",
        "the causal signal. `gained` = the reverse — instability. Read both",
        f"against the {NOISE}: 500 compared notes ⇒ ~2 flips are noise.",
        provenance,
        "",
        "| target phenotype | model | operator | compared | lost | (lost ∧ label+) | gained |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for tier, phenos in TIERS.items():
        lines.append(f"| **{tier}** | | | | | | |")
        for pheno in phenos:
          for question in questions.get(pheno, []):
            for m in models:
                for op in OPERATORS:
                    r = cell.get((pheno, question, op, m))
                    if not r:
                        continue
                    lines.append(
                        f"| {pheno} ({question}) | {short[m]} | {op.split('_')[0]} "
                        f"| {r['compared']} "
                        f"| {r['lost_positive_pred']} "
                        f"| {r['lost_positive_pred_and_label']} "
                        f"| {r['gained_positive_pred']} |"
                    )
    (args.out / "flips.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- probe_scorecard.md ----------------------------------------------
    lines = [
        "# Experiment 3 — the probe's predictions, scored",
        "",
        "The causal probe (75 notes/phenotype) pre-registered which phenotypes'",
        "calls ride the concept channel. This scores those predictions on the",
        "full 500-note sample with the exp2 operators at full dose. `moved` =",
        "an absolute ΔF1 of 0.05 or more in at least one arm; `noise` = every arm "
        "within 0.02.",
        provenance,
        "",
        "| target phenotype | predicted | largest ΔF1 (arm) | verdict |",
        "|---|---|---|---|",
    ]
    predicted = {p: t.split(" (")[0] for t, ps in TIERS.items() for p in ps}
    for tier, phenos in TIERS.items():
        for pheno in phenos:
            arms = [
                (abs(float(r["delta_f1"])), f"{short[m]}/{op.split('_')[0]}", float(r["delta_f1"]))
                for m in models
                for op in OPERATORS
                for question in questions.get(pheno, [])
                if (r := cell.get((pheno, question, op, m)))
                and r.get("delta_f1") not in (None, "")
            ]
            if not arms:
                continue
            mx, arm, signed_d = max(arms)
            moved = mx >= 0.05
            quiet = all(a[0] <= 0.02 for a in arms)
            expect_move = "H3a" in tier or tier.startswith("concept")
            expect_null = "resistant" in tier
            if expect_move:
                verdict = "as predicted" if moved else ("NOT as predicted" if quiet else "partial")
            elif expect_null:
                verdict = "as predicted" if quiet else ("NOT as predicted" if moved else "partial")
            else:
                verdict = "moderate band"
            lines.append(
                f"| {pheno} | {predicted[pheno]} | {signed_d:+.3f} ({arm}) | {verdict} |"
            )
    (args.out / "probe_scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- density_vs_impact.md --------------------------------------------
    # The cross-phenotype dose-response view: does the amount of corrupted
    # evidence predict the F1 impact? Within the concept-carried tier it
    # roughly should; across tiers it must NOT — high-dose/zero-impact rows
    # (C. difficile, pulmonary embolism) are the measured demonstration that
    # the decision channel, not the treatment dose, determines the effect.
    manifests: dict[tuple[str, str], dict] = {}
    manifest_dir: dict[tuple[str, str], Path] = {}
    for (pheno, _question, op, m), r in cell.items():
        if (pheno, op) in manifests:
            continue
        # condition = <exp>/<corruption>/full -> data/experiments/<exp>/<corruption>/full
        # The experiment is read from the condition rather than hardcoded, so a
        # rendered table cannot quietly describe one experiment's arms using
        # another's manifests.
        parts = r["condition"].split("/")
        path = Path("data/experiments") / parts[0] / parts[1] / "full/manifest.json"
        if path.exists():
            manifests[(pheno, op)] = json.loads(path.read_text(encoding="utf-8"))
            manifest_dir[(pheno, op)] = path.parent
    lines = [
        "# Experiment 3 — evidence density vs corruption impact",
        "",
        "Does the DOSE (how much of a phenotype's evidence a note carries, and",
        "therefore how much got corrupted) predict the IMPACT (ΔF1)? Within the",
        "concept-carried tier, roughly; across tiers, demonstrably not — the",
        "high-dose/zero-impact rows are the measured proof that the decision",
        "channel, not the treatment dose, determines the effect. `Δ/edit` is",
        "ΔF1 per mean edit-per-note — the efficiency of one unit of corruption.",
        provenance,
    ]
    for m in models:
        lines.append(f"\n## {short[m]}\n")
        lines.append(
            "| target phenotype | tier | op | notes edited | edits/note "
            "(edited) | ΔF1 | Δ/edit ×100 |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|")
        rows_out = []
        for tier, phenos in TIERS.items():
            tier_short = tier.split(" (")[0]
            for pheno in phenos:
              for question in questions.get(pheno, []):
                for op in OPERATORS:
                    r = cell.get((pheno, question, op, m))
                    man = manifests.get((pheno, op))
                    if not r or not man or r.get("delta_f1") in (None, ""):
                        continue
                    edited_n = notes_with_edits(man, manifest_dir.get((pheno, op)))
                    per_edited = man["edits"] / edited_n if edited_n else 0.0
                    d = float(r["delta_f1"])
                    eff = 100 * d / per_edited if per_edited else 0.0
                    rows_out.append(
                        (
                            d,
                            f"| {pheno} | {tier_short} | {op.split('_')[0]} "
                            f"| {edited_n}/{man['notes']} | {per_edited:.1f} "
                            f"| {d:+.3f} | {eff:+.2f} |",
                        )
                    )
        for _, row in sorted(rows_out):
            lines.append(row)
    lines += [
        "",
        "Read the extremes: the largest doses sit in phenotypes whose calls",
        "never move (dense but non-decisive evidence — symptoms, drugs shared",
        "across conditions), while the largest impacts include some of the",
        "smallest doses (obesity: few edits, all of them the diagnosis word).",
        "Density is necessary for the treatment to exist, and nowhere near",
        "sufficient for it to matter.",
    ]
    (args.out / "density_vs_impact.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- README ----------------------------------------------------------
    (args.out / "README.md").write_text(
        "# Experiment 3 tables\n\n"
        "Rendered by `experiments/exp3/render_exp3_tables.py` from\n"
        "`data/mipa_exp3/deltas.csv` — regenerate there, never edit here.\n\n"
        "| file | the reader's question |\n|---|---|\n"
        "| [f1_deltas.md](f1_deltas.md) | how much did F1 move (headline) |\n"
        "| [recall_deltas.md](recall_deltas.md) | the axis the treatment attacks |\n"
        "| [flips.md](flips.md) | paired per-note flips, direction split |\n"
        "| [density_vs_impact.md](density_vs_impact.md) | does dose predict impact (no — channel does) |\n"
        "| [probe_scorecard.md](probe_scorecard.md) | predicted vs observed (H3a/H3b) |\n"
        + provenance,
        encoding="utf-8",
    )
    print(f"-> {args.out} (4 tables + README)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
