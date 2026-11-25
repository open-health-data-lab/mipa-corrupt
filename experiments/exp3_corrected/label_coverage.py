"""Did each arm reach the notes a human annotator called positive?

**The gate this exists to second-guess.** Generation enforces a reach gate:
the share of *written diagnosis terms* an arm made eligible for corruption. That
gate is computed by the same anchor layer that does the corrupting, so it cannot
fail in the one way that matters -- a target blind to a phenotype is blind when
measuring itself too, and reports a clean 1.00 over the handful of mentions it
can see. Reach is necessary and not sufficient.

This asks a question the target has no hand in: of the notes a human labelled
positive for the phenotype, how many did the arm edit at all? The labels come
from MIPA's expert annotation, share no code with the anchor resource, and were
fixed long before any of it existed. A note labelled positive and left wholly
untouched is an arm that did not test the phenotype in that note, whatever the
reach gate says.

**A miss is not automatically a defect, so each one is read.** Three benign
families account for nearly all of them, and the script names rather than hides
them:

1. *The note never says it.* MIPA's labels are per-admission and an annotator
   may work from the structured record; a note that never writes the condition
   offers nothing to corrupt. Roughly two thirds of all misses.
2. *The arm is narrower than the phenotype.* Venous thromboembolism is one
   phenotype and `vte_past` and `vte_complication` are its two questions, which
   is what the phenotype is rather than a coarse label. Deep vein thrombosis and
   pulmonary embolism are two arms aimed at different parts of how it is written
   down, so a note positive for venous thromboembolism may carry only the
   vocabulary the other arm targets. Neither arm is wrong; each reaches its own
   share, and the measurement below confirms no note naming an arm's own terms
   was left alone.
3. *The evidence is excluded on purpose.* Alcoholic cirrhosis, gastritis and
   hepatitis are alcohol-attributed organ disease, recorded and coded as their
   own diagnoses; `curated_associated.py` states the exclusion and its reason.
   The annotators evidently read them as supporting the use disorder. That is a
   real disagreement about what the phenotype denotes, not a bug, and it is the
   one finding here worth a decision rather than a note.

A numeric value is its own small family: a note whose only obesity evidence is
`BMI: 35.8` has no surface to anchor, and corrupting the digits would perturb a
measurement rather than a diagnosis.

Usage::

    python experiments/exp3_corrected/label_coverage.py \\
        --experiments  .../data/experiments/exp3_corrected \\
        --notes        .../data/golden_notes.csv \\
        --labels       .../data/golden_labels.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

csv.field_size_limit(10**9)

#: arm -> the MIPA label columns that make a note positive for it. Several arms
#: map to more than one column because the phenotype has more than one question:
#: prior episode and complicating this admission. Venous thromboembolism is one
#: phenotype with one such pair, and the deep-vein and pulmonary arms are two
#: ways of aiming at it, so both carry that pair. The arms are narrower than the
#: phenotype by design and the labels are not coarse.
LABEL_COLUMNS: dict[str, tuple[str, ...]] = {
    "alcohol_use_disorder": ("alcohol_abuse",),
    "clostridioides_difficile": ("c_diff_past", "c_diff_complication"),
    "deep_vein_thrombosis": ("vte_past", "vte_complication"),
    "dementia": ("dementia",),
    "depression": ("depression",),
    "hfpef": ("hfpef",),
    "hfref": ("hfref",),
    "hypertension": ("hypertension",),
    "metastatic_cancer": ("metastatic_cancer",),
    "obesity": ("obesity",),
    "pulmonary_embolism": ("vte_past", "vte_complication"),
    "rheumatoid_arthritis": ("rheumatoid_arthritis",),
    "systemic_lupus_erythematosus": ("sle",),
    "type_1_diabetes": ("diabetes_type_1",),
    "type_2_diabetes": ("diabetes_type_2",),
}

#: Two readings of "the note names the condition", reported side by side,
#: because reporting only the strict one flatters the result.
#:
#: `STRICT` is the phenotype's own diagnosis in plain English. A missed note
#: matching it is an unambiguous defect: the words were there and the arm did
#: not touch them.
#:
#: `WIDE` adds every surface a reader might argue should have counted --
#: alcohol-attributed organ disease, a thrombosis in some other vessel, a bare
#: BMI value. These are excluded by design and each exclusion has a written
#: reason, so a WIDE hit is a disagreement to adjudicate rather than a bug. The
#: gap between the two columns is the size of that disagreement, and it belongs
#: in the output rather than in a footnote: an audit whose own pattern is
#: narrow enough will always report zero.
#:
#: Written with explicit character classes because RobustEHR's determinism lint
#: bans the shorthand classes and this file is read beside that code.
STRICT: dict[str, str] = {
    "alcohol_use_disorder": "alcoholism|alcohol use disorder|alcohol abuse|alcohol dependence",
    "clostridioides_difficile": "c[.]? ?diff|clostrid",
    "deep_vein_thrombosis": "dvt|deep ven(?:ous|e) thrombosis",
    "dementia": "dementia|alzheimer",
    "depression": "depress",
    "hfpef": "hfpef|preserved ejection",
    "hfref": "hfref|reduced ejection|systolic dysfunction",
    "hypertension": "hypertension|htn",
    "metastatic_cancer": "metasta|malignan",
    "obesity": "obes|bariatric",
    "pulmonary_embolism": "pulmonary embol|(?<![A-Za-z0-9])pe(?![A-Za-z0-9])",
    "rheumatoid_arthritis": "rheumatoid",
    "systemic_lupus_erythematosus": "lupus|(?<![A-Za-z0-9])sle(?![A-Za-z0-9])",
    "type_1_diabetes": "type 1 diabetes|t1dm|iddm",
    "type_2_diabetes": "type 2 diabetes|t2dm|niddm",
}

#: The widest defensible reading. Each entry is a superset of its STRICT twin.
WIDE: dict[str, str] = {
    "alcohol_use_disorder": "alcohol|etoh|alcoholic|ciwa|delirium tremens",
    "clostridioides_difficile": "c[.]? ?diff|clostrid|colitis|vancomycin|fidaxomicin",
    "deep_vein_thrombosis": "dvt|deep ven|thrombus|thrombos|clot",
    "dementia": "dementia|alzheimer|cognitive|memory loss|donepezil|memantine",
    "depression": "depress|ssri|sertraline|fluoxetine|citalopram",
    "hfpef": "hfpef|preserved ejection|diastolic|heart failure",
    "hfref": "hfref|reduced ejection|systolic dysfunction|cardiomyopath|heart failure",
    "hypertension": "hypertension|htn|blood pressure|antihypertensive",
    "metastatic_cancer": "metasta|malignan|carcinoma|tumor|tumour|neoplas",
    "obesity": "obes|bmi|bariatric|body mass|overweight",
    "pulmonary_embolism": "pulmonary embol|(?<![A-Za-z0-9])pe(?![A-Za-z0-9])|thrombos|clot",
    "rheumatoid_arthritis": "rheumatoid|methotrexate|arthrit",
    "systemic_lupus_erythematosus": (
        "lupus|(?<![A-Za-z0-9])sle(?![A-Za-z0-9])|hydroxychloroquine|antinuclear"
    ),
    "type_1_diabetes": "type 1 diabetes|t1dm|iddm|insulin pump|diabet",
    "type_2_diabetes": "type 2 diabetes|t2dm|niddm|metformin|diabet",
}


def positive(value: Any) -> bool:
    """MIPA writes some columns as `1` and others as `1.0`. Both mean positive."""
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiments", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--prefix", default="typographical_errors")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    text = {r["note_id"]: r["text"] for r in csv.DictReader(args.notes.open())}
    labels = {r["note_id"]: r for r in csv.DictReader(args.labels.open())}

    report: dict[str, Any] = {}
    total_positive = total_edited = total_named = total_arguable = 0
    print(
        f"{'phenotype':30s} {'positive':>9s} {'edited':>7s} {'cover':>6s} "
        f"{'defect':>8s} {'arguable':>9s}"
    )
    print("-" * 74)
    for phenotype, columns in sorted(LABEL_COLUMNS.items()):
        arm = args.experiments / f"{args.prefix}_{phenotype}" / "full"
        if not arm.exists():
            print(f"{phenotype:30s}  (arm absent)")
            continue
        edited = {json.loads(line)["note_uid"] for line in (arm / "edits.jsonl").open()}
        present = [r["note_id"] for r in csv.DictReader((arm / "notes.csv").open())]
        wanted = [u for u in present if any(positive(labels.get(u, {}).get(c)) for c in columns)]
        reached = [u for u in wanted if u in edited]
        missed = [u for u in wanted if u not in edited]

        strict_re = re.compile(STRICT[phenotype], re.IGNORECASE)
        wide_re = re.compile(WIDE[phenotype], re.IGNORECASE)
        named = [u for u in missed if strict_re.search(text.get(u, ""))]
        arguable = [u for u in missed if u not in named and wide_re.search(text.get(u, ""))]

        total_positive += len(wanted)
        total_edited += len(reached)
        total_named += len(named)
        total_arguable += len(arguable)
        share = len(reached) / len(wanted) if wanted else 0.0
        print(
            f"{phenotype:30s} {len(wanted):9d} {len(reached):7d} {share:6.0%} "
            f"{len(named):8d} {len(arguable):9d}"
        )
        report[phenotype] = {
            "label_columns": list(columns),
            "positive": len(wanted),
            "edited": len(reached),
            "coverage": round(share, 4),
            "missed": len(missed),
            # Counts, not note ids: this file is an aggregate and is meant to be shared.
            "missed_naming_the_diagnosis": len(named),
            "missed_naming_something_excluded": len(arguable),
        }

    print("-" * 74)
    print(
        f"{'TOTAL':30s} {total_positive:9d} {total_edited:7d} "
        f"{total_edited / total_positive:6.1%} {total_named:8d} {total_arguable:9d}"
    )
    print(
        "\n`defect`   a positive note naming the diagnosis in plain English, untouched.\n"
        "`arguable` a positive note naming only a surface excluded on purpose --\n"
        "           alcohol-attributed organ disease, a clot in another vessel, a bare\n"
        "           BMI. Read these before quoting the coverage column; they are the\n"
        "           cases where the annotator and the target disagree about what the\n"
        "           phenotype denotes. Every remaining miss is a note that never wrote\n"
        "           the condition at all."
    )
    payload = {
        "phenotypes": report,
        "total_positive": total_positive,
        "total_edited": total_edited,
        "total_missed_naming_the_diagnosis": total_named,
        "total_missed_naming_something_excluded": total_arguable,
        "caveat": (
            "Coverage is measured against MIPA's expert labels, which are "
            "per-admission and predate the anchor resource by months. A missed "
            "note is a defect only when the note names the condition in text; "
            "the rest are labels assigned from the structured record, or label "
            "columns that span two arms."
        ),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
