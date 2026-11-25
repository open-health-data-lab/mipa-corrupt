"""A reading sample of Experiment 3: clean and corrupted notes side by side.

For each of the 15 phenotypes, five notes from the 500 scored, each as a
directory of five files:

    original.txt          the note as written
    corrupted_typo.txt    the typographical-error arm aimed at this phenotype
    corrupted_ocr.txt     the capped-OCR arm aimed at this phenotype
    delta_typo.tsv        only what changed: one row per corrupted word
    delta_ocr.tsv         the same for the OCR arm

The five are stratified on what the corruption did to the label, read from
Gemma 3 12B under typographical errors on the phenotype's own question(s):

    lost       reference-positive, positive on the clean note, negative after   (2)
    kept       reference-positive, positive before and after                    (2)
    negative   reference-negative                                               (1)

A stratum with too few notes is filled from the next (then from `missed`,
reference-positive but negative on the clean note, then from any edited note),
and the index records the stratum each note actually came from. Only notes the
arm edited are eligible. Within a stratum the choice is a hash rank of the
phenotype and note id, so the sample is the same on every run.

**The output is MIMIC-IV text.** It is written under ``data/``, which is
ignored, and must stay there: never commit it, share it or paste it into an
online service.

Run from the data checkout:

    python <repo>/experiments/exp3_corrected/sample_notes.py \\
        --pairs <analysis repo>/reanalysis/derived/paired_predictions.csv.gz
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

MODEL = "google/gemma-3-12b-it"
ARMS = {"typo": "typographical_errors", "ocr": "ocr_capped"}
QUOTA = (("lost", 2), ("kept", 2), ("negative", 1))
FALLBACK = ("lost", "kept", "negative", "missed", "other")
PER_PHENOTYPE = 5
WORD = re.compile(r"[A-Za-z0-9]+")
CONTEXT = 40


def read_csv_text(path: Path, column: str) -> dict[str, str]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["note_id"]: row[column] for row in csv.DictReader(handle)}


def outcomes(pairs: Path) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """``[phenotype][note][question]`` -> the 12B row for each arm, plus the 4B call."""
    out: dict[str, dict[str, dict[str, dict[str, str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    with gzip.open(pairs, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["experiment"] != "exp3_corrected":
                continue
            arm = next((k for k, v in ARMS.items() if row["operator"] == v), None)
            if arm is None:
                continue
            model = "12b" if row["model"] == MODEL else "4b"
            cell = out[row["target_phenotype"]][row["note_id"]][row["clinical_question"]]
            cell["gold"] = row["gold_label"]
            cell[f"clean_{model}"] = row["clean_prediction"]
            cell[f"{arm}_{model}"] = row["corrupted_prediction"]
            cell[f"{arm}_{model}_transition"] = row["transition"]
            cell[f"{arm}_edited"] = row["note_edited"]
    return out


def stratum(questions: dict[str, dict[str, str]]) -> str:
    """One label per note, from the 12B typographical-error rows of its questions."""
    transitions = {q.get("typo_12b_transition", "") for q in questions.values()}
    golds = {q.get("gold", "0") for q in questions.values()}
    if "exit" in transitions:
        return "lost"
    if "kept_pos" in transitions:
        return "kept"
    if golds == {"0"}:
        return "negative"
    if "missed" in transitions:
        return "missed"
    return "other"


def rank(phenotype: str, note: str) -> str:
    return hashlib.sha256(f"{phenotype}|{note}".encode()).hexdigest()


def choose(phenotype: str, notes: dict[str, dict[str, dict[str, str]]]) -> list[tuple[str, str]]:
    pools: dict[str, list[str]] = defaultdict(list)
    for note, questions in notes.items():
        if all(
            q.get("typo_edited") == "1" and q.get("ocr_edited") == "1" for q in questions.values()
        ):
            pools[stratum(questions)].append(note)
    for pool in pools.values():
        pool.sort(key=lambda n: rank(phenotype, n))
    picked: list[tuple[str, str]] = []
    for name, quota in QUOTA:
        picked += [(name, pools[name].pop(0)) for _ in range(min(quota, len(pools[name])))]
    for name in FALLBACK:
        while len(picked) < PER_PHENOTYPE and pools[name]:
            picked.append((name, pools[name].pop(0)))
    return picked


def delta(clean: str, corrupted: str) -> list[dict[str, object]]:
    """One row per word that differs. Both arms preserve length, so offsets align."""
    if len(clean) != len(corrupted):
        raise ValueError("corrupted note differs in length from the clean note")
    rows = []
    for match in WORD.finditer(clean):
        start, end = match.span()
        if clean[start:end] == corrupted[start:end]:
            continue
        changed = [i for i in range(start, end) if clean[i] != corrupted[i]]
        left = clean[max(0, start - CONTEXT) : start]
        right = clean[end : end + CONTEXT]
        rows.append(
            {
                "offset": start,
                "line": clean.count("\n", 0, start) + 1,
                "original": clean[start:end],
                "corrupted": corrupted[start:end],
                "chars_changed": len(changed),
                "position_in_word": ",".join(str(i - start + 1) for i in changed),
                "context": " ".join(f"{left}[{clean[start:end]}]{right}".split()),
            }
        )
    total = sum(1 for a, b in zip(clean, corrupted, strict=True) if a != b)
    if total != sum(int(str(r["chars_changed"])) for r in rows):
        raise ValueError("a changed character falls outside every word")
    return rows


def write_delta(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "offset",
        "line",
        "original",
        "corrupted",
        "chars_changed",
        "position_in_word",
        "context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiment", type=Path, default=Path("data/experiments/exp3_corrected"))
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--pairs", type=Path, required=True, help="paired_predictions.csv.gz")
    parser.add_argument("--out", type=Path, default=Path("data/exp3_samples"))
    args = parser.parse_args(argv)

    if args.out.resolve().parts.count("data") == 0:
        print("--out must be under a data/ directory: the sample is MIMIC-IV text", file=sys.stderr)
        return 2
    clean = read_csv_text(args.notes, "text")
    by_phenotype = outcomes(args.pairs)
    index = []
    for phenotype in sorted(by_phenotype):
        corrupted = {
            arm: read_csv_text(
                args.experiment / f"{name}_{phenotype}" / "full" / "notes.csv", "note_corrupted"
            )
            for arm, name in ARMS.items()
        }
        for order, (name, note) in enumerate(choose(phenotype, by_phenotype[phenotype]), 1):
            directory = args.out / phenotype / f"{order}_{name}_{note}"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "original.txt").write_text(clean[note], encoding="utf-8")
            row: dict[str, object] = {
                "phenotype": phenotype,
                "set": order,
                "stratum": name,
                "note_id": note,
                "directory": str(directory.relative_to(args.out)),
            }
            for arm in ARMS:
                (directory / f"corrupted_{arm}.txt").write_text(
                    corrupted[arm][note], encoding="utf-8"
                )
                rows = delta(clean[note], corrupted[arm][note])
                write_delta(directory / f"delta_{arm}.tsv", rows)
                row[f"words_corrupted_{arm}"] = len(rows)
            for question, cell in sorted(by_phenotype[phenotype][note].items()):
                index.append(
                    {
                        **row,
                        "question": question,
                        "reference_label": cell.get("gold"),
                        **{
                            k: cell.get(k)
                            for k in (
                                "clean_12b",
                                "typo_12b",
                                "ocr_12b",
                                "clean_4b",
                                "typo_4b",
                                "ocr_4b",
                            )
                        },
                    }
                )
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(index[0]))
        writer.writeheader()
        writer.writerows(index)
    sets = {(r["phenotype"], r["note_id"]) for r in index}
    (args.out / "README.txt").write_text(
        "Experiment 3 reading sample. MIMIC-IV text under the PhysioNet DUA: do not commit,\n"
        "share or upload. Built by experiments/exp3_corrected/sample_notes.py; index.csv lists\n"
        "every set with its stratum, reference label and each model's answer before and after.\n"
        "Predictions are 0/1 for the phenotype's own question(s).\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"phenotypes": len({p for p, _ in sets}), "sets": len(sets), "out": str(args.out)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
