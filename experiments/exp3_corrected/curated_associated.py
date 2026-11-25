"""Curated additions to the associated tier, with the reasoning recorded.

The gap audit finds terms the target misses. It does not decide which of them
*should* be reached, and that difference is where a raw count misleads.

**The measurement that prompted this, and why its shape was wrong.** Scanning
the corpus for candidate terms produced rows like `cardiomyopathy: 82
occurrences, 0 covered`, which reads as a large miss. Reading the 82 says
otherwise: five are `lupus cardiomyopathy`, three `hypertrophic
cardiomyopathy`, and hypertrophic cardiomyopathy is a different disease with
preserved or supranormal ejection fraction. Corrupting those as HFrEF evidence
would be wrong, so most of that zero is correct.

A denominator of every string match is not a denominator of things that should
be reached. Only the qualified forms belong, and bare `cardiomyopathy` stays out
for the same reason bare `thrombosis` stays out of deep vein thrombosis: the
word alone spans conditions that are not this phenotype.

**What these have in common.** Every term here is how the condition is
*evidenced in a chart* rather than how the diagnosis is *named*. HFrEF is
recorded as a cardiomyopathy with systolic dysfunction far more often than as
the string `HFrEF`; alcohol use disorder appears as withdrawal management and
CIWA scoring; type 1 diabetes appears as an insulin pump. The anchor proposal
asks what the diagnosis is called and the facet proposals ask what accompanies
it, and this class falls between the two questions.

They enter at tier `associated`, never `anchor`, so they support the phenotype
without counting toward the diagnosis denominator the reach gate uses.

Usage::

    python experiments/exp3_corrected/curated_associated.py \\
        --anchors <RobustEHR checkout>/src/robustehr/resources/phenotype_anchors.yaml
"""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

#: What the ledger records for this pass. Deliberately not a path: the
#: resource ships inside RobustEHR and a reader holding only that library
#: cannot resolve a filename in this repository.
SOURCE_NOTE = ("hand-curated beside the study that needed them; the terms and "
               "their exclusions are recorded in this file")

#: The anchor resource of the installed `robustehr`. To change the resource rather
#: than read it, pass `--anchors` the copy in a RobustEHR checkout.
DEFAULT_ANCHORS = Path(str(files("robustehr.resources"))) / "phenotype_anchors.yaml"

#: term -> why it is safe, per phenotype. The reason is required, because a
#: curated list without one is indistinguishable from a list someone guessed.
CURATED: dict[str, dict[str, str]] = {
    "hfref": {
        "ischemic cardiomyopathy": "qualified: ischaemic aetiology implies reduced EF",
        "nonischemic cardiomyopathy": "qualified: the dilated/non-ischaemic phenotype",
        "non-ischemic cardiomyopathy": "spelling variant of the above",
        "dilated cardiomyopathy": "dilatation implies systolic impairment",
        "idiopathic dilated cardiomyopathy": "qualified dilated form",
        "systolic dysfunction": "the defining functional abnormality",
        "left ventricular systolic dysfunction": "same, stated in full",
        "lv systolic dysfunction": "same, abbreviated as charts write it",
        "global hypokinesis": "diffuse wall-motion abnormality, not regional",
        "left ventricular hypokinesis": "same, stated in full",
        "biventricular systolic dysfunction": "qualified systolic impairment",
        # NOT `cardiomyopathy` alone: 82 occurrences in the corpus, of which
        # lupus and hypertrophic forms are other diseases. NOT `hypokinesis`
        # alone: regional hypokinesis after infarct is not HFrEF.
    },
    "alcohol_use_disorder": {
        "alcohol withdrawal": "withdrawal presupposes dependence",
        "etoh withdrawal": "same, as charts abbreviate it",
        "alcohol withdrawal syndrome": "named syndrome",
        "delirium tremens": "severe withdrawal, pathognomonic",
        "withdrawal seizure": "complication of alcohol withdrawal",
        "ciwa": "the withdrawal severity instrument; scored only in this setting",
        "ciwa-ar": "the revised instrument",
        "heavy alcohol use": "the consumption pattern the diagnosis rests on",
        "chronic heavy alcohol use": "same, qualified",
        # NOT `alcoholic cirrhosis` or `alcoholic hepatitis`: organ disease from
        # alcohol is its own diagnosis, and a coder records it separately.
    },
    "type_1_diabetes": {
        "insulin pump": "continuous subcutaneous infusion is type 1 practice",
        "continuous subcutaneous insulin infusion": "same, stated in full",
        "continuous glucose monitor": "type 1 monitoring standard",
        "basal-bolus insulin": "the regimen type 1 requires",
        "islet cell antibody": "type 1 specific autoantibody",
        "glutamic acid decarboxylase antibody": "type 1 specific autoantibody",
        "gad65 antibody": "same, as charts abbreviate it",
        # NOT `dka`: already covered at 66 of 78 occurrences through the concept
        # warrant, and euglycaemic DKA on SGLT2 inhibitors occurs in type 2.
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    loaded: Any = yaml.safe_load(args.anchors.read_text(encoding="utf-8"))
    blocks = loaded["phenotypes"]
    added = 0
    for name, terms in CURATED.items():
        block = blocks.setdefault(name, {"anchors": [], "associated": [], "stop_surfaces": []})
        current = {str(t).strip().lower() for t in block.get("associated", ())}
        declared = {str(a).strip().lower() for a in block.get("anchors", ())}
        fresh = [t for t in terms if t not in current and t not in declared]
        print(f"  {name:28s} +{len(fresh):2d} ({len(current)} already)")
        for t in fresh:
            print(f"        {t:44s} {terms[t]}")
        block["associated"] = sorted(current | set(fresh))
        added += len(fresh)

    if args.dry_run:
        print(f"\ndry run: would add {added}")
        return 0
    # Recorded once and numbered after the last pass. An unconditional append
    # made the shipped ledger claim a pass that had not run twice, and the
    # provenance field named a path outside the library the resource ships in,
    # which made it unresolvable to anyone holding only that library.
    passes = loaded.setdefault("passes", [])
    identity = {"role": "curated associated terms", "by": "hand"}
    if not any({k: v for k, v in e.items() if k != "pass"} == dict(
            identity, source=SOURCE_NOTE) for e in passes):
        passes.append(dict(identity, source=SOURCE_NOTE,
                           **{"pass": max((e.get("pass", 0) for e in passes), default=0) + 1}))
    args.anchors.write_text(
        yaml.safe_dump(loaded, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    print(f"\n{args.anchors}: +{added} associated terms")
    print(json.dumps({"added": added, "phenotypes": sorted(CURATED)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
