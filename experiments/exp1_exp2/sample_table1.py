"""Table 1 over the 500 sampled notes, not the whole corpus.

`data/experiments/baseline/table1.json` characterises all 1,388 MIPA notes. The
experiment does not run on all 1,388 — it runs on the 500 in
`data/mipa_exp1/sample.csv` — so the corpus-level table describes a population
the results were not produced from. Anyone reading "median 11,546 characters"
beside an F1 computed on the sample is reading two different denominators.

This produces the same table over exactly the evaluated notes, through the same
`_measure_all` / `write_table1` path `run_experiments.py` uses, so the two are
comparable line for line and any difference is a real difference rather than an
instrument change.

Concept annotation comes from the existing cache — all 1,388 notes are already
tagged — so this costs a few file reads rather than 20 minutes of QuickUMLS.

    python experiments/exp1_exp2/sample_table1.py
    python experiments/exp1_exp2/sample_table1.py --out data/mipa_exp1/table1_sample
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_experiments import (
    _INDEX,
    _measure_all,
    annotate_all,
    load_lexicon,
    read_corpus,
    write_table1,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/mipa_exp1/table1_sample"))
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon/clinical_tokens.txt"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    from robustehr.document import Document
    from robustehr.segment.wrap import wrap_width

    from mipa import sample as mipa_sample

    sample = mipa_sample.read_sample(args.sample)
    wanted = {n.hadm_id for n in sample}

    records = read_corpus(args.corpus, None)
    selected = [r for r in records if str(r.get("hadm_id", "")) in wanted]
    if len(selected) != len(wanted):
        raise SystemExit(
            f"{len(wanted)} sampled notes but {len(selected)} matched in {args.corpus}; "
            "the sample and the corpus disagree"
        )
    print(f"corpus {len(records)} notes -> sample {len(selected)}", flush=True)

    lexicon = load_lexicon(args.lexicon)
    _INDEX.append(str(args.index))

    documents = {r["note_id"]: Document.from_text(r["text"], uid=r["note_id"]) for r in selected}
    docs = [documents[r["note_id"]] for r in selected]
    # Pinned per note exactly as the sweep does. Not needed for a clean-only
    # table, but keeping the call identical is what makes this comparable to
    # `baseline/table1.json` rather than merely similar.
    {uid: wrap_width(doc.lines) for uid, doc in documents.items()}

    concepts: dict[str, object] = {}
    if args.index.exists():
        concepts = annotate_all(docs, args.index, args.cache, args.workers, "sample")
    else:
        print(f"no UMLS index at {args.index}; concept levels will be absent", flush=True)

    start = time.time()
    write_table1(
        _measure_all(docs, lexicon, concepts),
        args.out,
        f"MIPA evaluation sample ({len(selected)} notes)",
        lexicon,
    )
    print(f"table1: {time.time() - start:.1f}s", flush=True)
    for name in ("table1.md", "table1.json"):
        print(f"  {args.out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
