"""Second-pass review of the surface anchors, and the sheet a clinician signs.

RobustEHR ships the first pass: `validation/phenotype/scripts/phenotype_anchors.py`
asks a cheap model to list the ways a diagnosis is written, and writes the result
as candidates. This is the review that decides which of those candidates ship.

**Why it lives here and not there.** The library's pass is part of its published
method and belongs in its tree. This one is a study-side decision about how much
review the study's own anchor set received before the study used it, run once
against a stronger model, and putting it in the library would present a
study-specific review step as part of the package's method. It is not.

**What it produces, and what that is worth.** Two things:

* the merged resource, which RobustEHR then ships, with both passes named in its
  header. A reader can see that the set was proposed by one model and reviewed
  by another, and neither pass is hidden.
* `anchor_review.md`, one line per decision with the model's reason. That sheet
  is the point. A surface anchor set is roughly fifteen phenotypes by a dozen
  forms, which is small enough for a clinician to read end to end in a sitting,
  and until one has, the set is machine-reviewed and the header says exactly
  that: `vetted_by: llm`.

  Signing the sheet is what changes the claim. `--signed-by` records the
  reviewer and flips the header to `llm+clinician`, which is the state
  `validation/protocol.md` §10 asks any result leaning on a `pheno=` target to
  report. Passing it without having read the sheet would put a name on a review
  that did not happen, so it is a flag and not a default.

The review is narrow on purpose. It answers one question per candidate — does
this string, alone, mean this diagnosis — and it cannot add forms the proposer
missed. Recall belongs to the first pass, where it can be measured against the
corpus; this pass only removes.

Usage::

    export OPENROUTER_API_KEY=...
    python experiments/exp3_corrected/vet_anchors.py \\
        --anchors <RobustEHR checkout>/src/robustehr/resources/phenotype_anchors.yaml \\
        --review experiments/exp3_corrected/anchor_review.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
KEY_ENV = "OPENROUTER_API_KEY"

#: The mid tier, against the cheap tier that proposed. A review by the same
#: model that generated is not a review; it agrees with itself.
DEFAULT_MODEL = "openai/gpt-5.6-terra"

#: The anchor resource of the installed `robustehr`. To change the resource rather
#: than read it, pass `--anchors` the copy in a RobustEHR checkout.
DEFAULT_ANCHORS = Path(str(files("robustehr.resources"))) / "phenotype_anchors.yaml"
DEFAULT_REVIEW = Path("experiments/exp3_corrected/anchor_review.md")
DEFAULT_CACHE = Path("data/llm_cache")

PROMPT = """You are reviewing candidate surface forms for one clinical diagnosis.

DIAGNOSIS: {label}

A surface form belongs in this set if, seeing that string in a discharge
summary, a physician would take it to refer to this diagnosis.

Drop a form ONLY if one of these is true:
- it has an established DIFFERENT clinical meaning a reader could plausibly
  intend in a discharge summary, so the string alone is genuinely ambiguous
  ("ra" is room air as often as rheumatoid arthritis)
- it names a related but different condition, including a sibling this
  phenotype is defined against
- it is a drug, test, lab value, symptom, risk factor or complication rather
  than the diagnosis itself
- it is an ordinary English word used in its ordinary sense

Do NOT drop a form merely because it is partial, informal, elliptical or
shorthand. That is how discharge summaries are written. "lupus", "mets" and
"rheumatoid" are what clinicians type, and dropping them for being incomplete
removes the target's reach over exactly the text it exists to find. If the only
objection is that a fuller phrasing exists, keep it.

Keep a form if it is the diagnosis as clinicians write it, including
abbreviations, punctuation variants, the causative organism where the condition
is named by its organism, and the qualifying adjective where the qualifier is
what makes the diagnosis.

When you are unsure, keep. A form wrongly kept costs some off-target matching;
a form wrongly dropped means the diagnosis is invisible wherever it is written
that way.

Reply with one line per form, exactly `<number>|<keep|drop>|<3-8 word reason>`.
No preamble, no blank lines.

{items}"""


def complete(model: str, key: str, cache: Path, prompt: str) -> str:
    """One cached completion. Same contract as the library's client."""
    import hashlib

    digest = hashlib.blake2b(f"{model}\x1f{prompt}".encode(), digest_size=16).hexdigest()
    hit = cache / f"anchor-vet-{digest}.json"
    if hit.exists():
        payload = json.loads(hit.read_text(encoding="utf-8"))
        return str(payload["choices"][0]["message"]["content"])
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "provider": {"data_collection": "deny"},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    if "choices" not in payload:
        raise RuntimeError(f"no choices in reply: {str(payload)[:200]}")
    cache.mkdir(parents=True, exist_ok=True)
    hit.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return str(payload["choices"][0]["message"]["content"])


def review(model: str, key: str, cache: Path, label: str, forms: list[str]) -> dict[str, dict]:
    """One verdict per candidate form.

    An unparseable line leaves the form undecided, and the caller DROPS it. The
    asymmetry matches the library's vetting pass and exists for the same reason:
    a silent parse failure that kept forms would widen the set exactly where the
    evidence for keeping it is weakest.
    """
    items = "\n".join(f"{i + 1}. {form}" for i, form in enumerate(forms))
    reply = complete(model, key, cache, PROMPT.format(label=label, items=items))
    verdicts: dict[str, dict] = {}
    for line in reply.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3 or not parts[0].rstrip(".").isdigit():
            continue
        index = int(parts[0].rstrip(".")) - 1
        if not 0 <= index < len(forms):
            continue
        verdicts[forms[index]] = {
            "verdict": "keep" if parts[1].lower().startswith("keep") else "drop",
            "reason": parts[2][:70],
        }
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--signed-by",
        default="",
        help="name of the clinician who has READ anchor_review.md and accepts it. "
        "Flips the resource header to llm+clinician. Do not pass it otherwise: "
        "it records that a person reviewed the set, and that claim has to be true",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.anchors.exists():
        print(
            f"{args.anchors} does not exist. Run the first pass in RobustEHR:\n"
            "  ROBUSTEHR_LLM_MODEL=openai/gpt-5.6-luna \\\n"
            "  python validation/phenotype/scripts/phenotype_anchors.py",
            file=sys.stderr,
        )
        return 2

    loaded: Any = yaml.safe_load(args.anchors.read_text(encoding="utf-8"))
    blocks = loaded["phenotypes"]

    if args.dry_run:
        total = sum(len(b.get("anchors", ())) for b in blocks.values())
        print(f"would review {total} candidate surfaces over {len(blocks)} phenotypes")
        return 0

    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"set {KEY_ENV}", file=sys.stderr)
        return 2

    # Labels come from the library's own definitions so the two passes are
    # asking about the same thing under the same name.
    from robustehr.concepts.phenotype import load_definitions

    definitions = load_definitions()

    rows: list[tuple[str, str, str, str]] = []
    kept_total = dropped_total = 0
    for name in sorted(blocks):
        forms = list(blocks[name].get("anchors", ()))
        if not forms:
            continue
        verdicts = review(args.model, key, args.cache, definitions[name].label, forms)
        kept = [f for f in forms if verdicts.get(f, {}).get("verdict") == "keep"]
        for form in forms:
            decision = verdicts.get(form, {"verdict": "drop", "reason": "undecided; excluded"})
            rows.append((name, form, decision["verdict"], decision["reason"]))
        blocks[name]["anchors"] = kept
        blocks[name]["reviewed_n"] = len(verdicts)
        blocks[name]["pass"] = 2
        kept_total += len(kept)
        dropped_total += len(forms) - len(kept)
        print(f"  {name}: kept {len(kept)}, dropped {len(forms) - len(kept)}")

    signed = bool(args.signed_by)
    loaded["passes"] = [
        *[p for p in loaded.get("passes", []) if p.get("pass") != 2],
        {"pass": 2, "role": "review", "model": args.model, "by": "llm"},
    ]
    if signed:
        loaded["passes"].append({"pass": 3, "role": "accept", "by": args.signed_by})
    loaded["vetted_by"] = "llm+clinician" if signed else "llm"
    loaded["undecided_policy"] = "excluded"
    args.anchors.write_text(
        yaml.safe_dump(loaded, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )

    lines = [
        "# Surface anchor review",
        "",
        f"Proposed by `{loaded['passes'][0].get('model', '?')}`, reviewed by `{args.model}`.",
        "",
        f"**{kept_total} kept, {dropped_total} dropped.** Every drop is listed with the",
        "reviewing model's stated reason, so the set can be checked without rerunning it.",
        "",
        "Until a clinician has read this sheet end to end, the resource header reads",
        "`vetted_by: llm` and every result leaning on a `pheno=` target should say so.",
        "Reading it and passing `--signed-by` is what makes the stronger claim true.",
        "",
        "| phenotype | surface | verdict | reason |",
        "|---|---|---|---|",
    ]
    lines += [f"| {n} | `{f}` | {v} | {r} |" for n, f, v, r in rows]
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n{args.anchors}: {kept_total} anchors, vetted_by={loaded['vetted_by']}")
    print(f"{args.review}: {len(rows)} decisions to read")
    if not signed:
        print("\nNot clinician-signed. Read the sheet, then rerun with --signed-by '<name>'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
