"""Choosing which notes the experiment runs on, and why those.

The full design — 28 conditions x 3 models x 1,388 notes x 16 phenotypes — is
2.5 million API calls and about a week of wall clock. A subsample is the only way
this finishes, so the subsample has to be good enough that the numbers still mean
something.

**One sample, shared by every condition and model.** Not a fresh draw per
condition. Because baseline and corrupted are then measured on the *same* notes,
every delta is a paired comparison and between-note variance — which is by far
the largest source of noise here, since notes range from 2k to 40k characters —
cancels out of it entirely. That buys back most of what subsampling costs, but
only for the deltas, which are the actual result.

**Stratified on seventeen things at once**: the 16 phenotype labels at their
corpus prevalence, and concept density in tertiles. Prevalence matters because
`hypertension` is 67.7% of notes and `vte_complication` 2.8%; a naive draw would
leave the rare ones with single-digit positives and unusable per-phenotype F1.
Density matters because a corruption dosed on eligible units does more to a
concept-dense note, so a sample skewed on density would confound corruption
severity with note composition.

Exact proportional allocation across 16 *overlapping* labels is not achievable —
a note positive for hypertension is usually positive for something else — so this
uses **iterative stratification** (Sechidis, Tsoumakas & Vlahavas 2011): fill the
scarcest stratum first, because that is the one a greedy or random draw gets
wrong, and let the abundant ones absorb the slack.

**A floor on the rare phenotypes, because proportional alone is unusable there.**
Plain proportional allocation at n=500 gives `vte_complication` 14 positives and
`c_diff_complication` 15 — per-phenotype F1 on 14 positives is barely
interpretable. `min_positives` raises those to 30 each **at identical compute**:
the sample is the same size, it simply spends its slots on notes that carry the
scarce labels. What it costs is prevalence fidelity on exactly those phenotypes,
which `report` surfaces as a positive deviation rather than hiding (max 0.032 at
n=500, floor 30, against 0.001 unfloored).

Chasing further is a bad trade and was measured before being rejected: covering
80% of every rare phenotype needs ~1,094 notes — **79% of the corpus** — because
the rare positives are scattered across different notes. At that point the
remaining 21% buys away the sampling caveat entirely, so the honest choices are a
modest floored sample or the whole corpus, not something in between.

`n_pos` still travels on every row of `phenotype_metrics.csv`: 30 positives is
usable, not generous, and a reader should be able to see it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mipa.protocol import PHENOTYPES

#: Values that count as a positive label. MIPA writes both `0` and `0.0` into one
#: file; treating the float as truthy would make every note positive for
#: everything. Mirrors MIPA's own rule in `metrics/describe.read_groups`.
NEGATIVE = ("", "0", "0.0", None)

#: Concept-density bands. Three, not more: the point is to stop the sample
#: skewing dense or sparse, and finer bands would fight the 16 label strata for
#: the same 500 slots.
DENSITY_BANDS = 3

#: Default sample size, and the floor on positives per phenotype.
#:
#: The floor is free — it does not change the sample size, only which notes fill
#: it — and it doubles the positives on the two phenotypes that most need it.
#: Both are overridable; see the module docstring for why chasing 80% coverage
#: is not worth it.
DEFAULT_SAMPLE_SIZE = 500
DEFAULT_MIN_POSITIVES = 30


@dataclass(frozen=True, slots=True)
class Note:
    """One candidate, with everything the sampler stratifies on."""

    hadm_id: str
    note_id: str
    labels: frozenset[str]
    concepts: int
    density_band: int = 0

    def strata(self) -> frozenset[str]:
        """Every stratum this note belongs to.

        **Both poles of every label**, not just the positives. A note that is
        negative for hypertension belongs to `hypertension-`, and that is what
        makes label-poor notes selectable at all: scored on positives alone they
        serve no open stratum, are never preferred, and the sample drifts
        multi-morbid. Measured on MIPA at n=500, positives-only left *every*
        phenotype over-represented (mean deviation +0.017, hypertension +0.059)
        because the deviation can only go one way when the sampler can only ever
        add labels.
        """
        return frozenset(
            {f"{p}+" for p in self.labels}
            | {f"{p}-" for p in PHENOTYPES if p not in self.labels}
            | {f"_density_{self.density_band}"}
        )


@dataclass
class SampleReport:
    """Achieved versus target, so the sample is auditable rather than asserted."""

    n: int
    corpus_n: int
    per_stratum: dict[str, dict[str, Any]] = field(default_factory=dict)

    def worst_deviation(self) -> tuple[str, float]:
        """The stratum furthest from its target proportion, and by how much."""
        if not self.per_stratum:
            return ("", 0.0)
        name = max(self.per_stratum, key=lambda s: abs(self.per_stratum[s]["deviation"]))
        return name, self.per_stratum[name]["deviation"]

    def as_rows(self) -> list[dict[str, Any]]:
        return [{"stratum": k, **v} for k, v in sorted(self.per_stratum.items())]


def read_labels(path: Path) -> dict[str, frozenset[str]]:
    """`hadm_id` -> the phenotypes it is positive for."""
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        str(r["hadm_id"]): frozenset(p for p in PHENOTYPES if r.get(p) not in NEGATIVE)
        for r in rows
    }


def read_concept_counts(cache_root: Path, texts: dict[str, str]) -> dict[str, int]:
    """`hadm_id` -> number of UMLS mentions, straight from the annotation cache.

    The cache is keyed by note SHA-256 under a single matcher-config digest, so
    the count is a file read rather than a re-tag — the corpus is already fully
    annotated. Deliberately does NOT construct a `ConceptMatcher`: loading a
    5 GB QuickUMLS index to compute a directory name would be the most expensive
    part of sampling.

    A note with no cache entry gets 0 and lands in the lowest band. That is
    honest — an untagged note has no measured density — and it is reported.
    """
    digests = [d for d in cache_root.iterdir() if d.is_dir()] if cache_root.exists() else []
    if len(digests) != 1:
        raise SystemExit(
            f"expected exactly one matcher-config digest under {cache_root}, found "
            f"{len(digests)}. Two configurations cannot be mixed in one sample; "
            "point --cache at the one this experiment should use."
        )
    root = digests[0]
    counts: dict[str, int] = {}
    for hadm_id, text in texts.items():
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        entry = root / sha[:2] / f"{sha}.json"
        if entry.exists():
            counts[hadm_id] = len(json.loads(entry.read_text(encoding="utf-8"))["mentions"])
        else:
            counts[hadm_id] = 0
    return counts


def assign_density_bands(notes: list[Note]) -> list[Note]:
    """Split into equal-count concept-density bands by quantile.

    Quantiles rather than equal-width bins: concept counts are right-skewed, and
    equal-width would put almost every note in the bottom band and stratify on
    nothing.
    """
    if not notes:
        return notes
    counts = sorted(n.concepts for n in notes)
    cuts = [
        counts[min(len(counts) - 1, (len(counts) * i) // DENSITY_BANDS)]
        for i in range(1, DENSITY_BANDS)
    ]
    out = []
    for note in notes:
        band = sum(1 for cut in cuts if note.concepts >= cut)
        out.append(Note(note.hadm_id, note.note_id, note.labels, note.concepts, band))
    return out


def _rank(hadm_id: str, salt: str) -> bytes:
    """Deterministic tie-break, the same BLAKE2b hash-rank the operators use.

    Makes the sample a pure function of (corpus, salt, n): reproducible on any
    machine, and — because ranks do not depend on n — a larger sample is a
    superset of a smaller one wherever the stratum targets allow.
    """
    return hashlib.blake2b(f"{salt}\x1fsample\x1f{hadm_id}".encode(), digest_size=16).digest()


def select(notes: list[Note], n: int, salt: str = "rep0", min_positives: int = 0) -> list[Note]:
    """Iterative stratification over labels and density bands.

    At each step: find the stratum with the smallest remaining quota, and fill it
    from the note that best serves the *other* still-unfilled strata. Scarcest
    first is the whole trick — an abundant stratum can be satisfied by many notes
    later, a scarce one by very few, so spending its candidates on anything else
    is what makes rare phenotypes come out wrong.
    """
    if n >= len(notes):
        return sorted(notes, key=lambda x: x.hadm_id)

    corpus = len(notes)
    strata = sorted({s for note in notes for s in note.strata()})
    # Exact-integer targets; a stratum present in the corpus but rounding to zero
    # still gets one, so no phenotype silently vanishes from the sample.
    quota = {
        s: max(1, round(n * sum(1 for x in notes if s in x.strata()) / corpus)) for s in strata
    }
    if min_positives:
        # A floor on POSITIVE strata only. Proportional allocation is honest but
        # gives `vte_complication` 14 positives at n=500, and per-phenotype F1 on
        # 14 positives is nearly uninterpretable. Raising the floor buys
        # precision on the rare phenotypes and pays for it in prevalence
        # fidelity, which `report` then shows as a positive deviation on exactly
        # those phenotypes. Capped by what the corpus actually holds.
        for phenotype in PHENOTYPES:
            key = f"{phenotype}+"
            available = sum(1 for x in notes if key in x.strata())
            if key in quota:
                quota[key] = max(quota[key], min(min_positives, available))

    remaining = {note.hadm_id: note for note in notes}
    chosen: list[Note] = []
    while len(chosen) < n and remaining:
        open_strata = {s: q for s, q in quota.items() if q > 0}
        candidates: list[Note]
        if open_strata:
            scarcest = min(open_strata, key=lambda s: (open_strata[s], s))
            candidates = [x for x in remaining.values() if scarcest in x.strata()]
            if not candidates:
                # The stratum is exhausted before its quota — the corpus simply
                # does not contain enough. Drop it rather than spin.
                quota[scarcest] = 0
                continue
        else:
            candidates = list(remaining.values())

        def served(note: Note) -> tuple[int, int, bytes]:
            """Prefer notes that fill open strata *without* overshooting full ones.

            The overshoot term is what keeps prevalence honest. Without it the
            sampler is biased hard toward multi-morbid notes: a note positive for
            six phenotypes scores well on the one stratum still open and silently
            adds five more to strata already at quota. Measured on MIPA at n=500,
            that put hypertension at 0.814 against a corpus prevalence of 0.677
            — every phenotype over-represented, the common ones worst.
            """
            helps = sum(1 for s in note.strata() if quota.get(s, 0) > 0)
            overshoot = sum(1 for s in note.strata() if quota.get(s, 0) <= 0)
            return (-helps, overshoot, _rank(note.hadm_id, salt))

        pick = min(candidates, key=served)
        del remaining[pick.hadm_id]
        chosen.append(pick)
        for s in pick.strata():
            if s in quota:
                quota[s] -= 1

    return sorted(chosen, key=lambda x: x.hadm_id)


def report(sample: list[Note], corpus: list[Note]) -> SampleReport:
    """Achieved versus corpus proportion, per stratum."""
    out = SampleReport(n=len(sample), corpus_n=len(corpus))
    strata = sorted({s for note in corpus for s in note.strata()})
    for s in strata:
        corpus_n = sum(1 for x in corpus if s in x.strata())
        sample_n = sum(1 for x in sample if s in x.strata())
        target = corpus_n / len(corpus) if corpus else 0.0
        achieved = sample_n / len(sample) if sample else 0.0
        out.per_stratum[s] = {
            "corpus_n": corpus_n,
            "corpus_prevalence": round(target, 4),
            "sample_n": sample_n,
            "sample_prevalence": round(achieved, 4),
            "deviation": round(achieved - target, 4),
        }
    return out


def load_corpus(notes_csv: Path, labels_csv: Path, cache_root: Path) -> list[Note]:
    """Every candidate note, with its labels and concept density attached."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with notes_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    text_column = "note_text" if "note_text" in rows[0] else "text"
    texts = {str(r["hadm_id"]): r[text_column] for r in rows}
    labels = read_labels(labels_csv)
    missing = set(texts) - set(labels)
    if missing:
        raise SystemExit(
            f"{len(missing)} notes have no gold label (e.g. {sorted(missing)[:3]}). "
            "Every sampled note must join, or its predictions cannot be scored."
        )
    counts = read_concept_counts(cache_root, texts)
    notes = [
        Note(
            hadm_id=str(r["hadm_id"]),
            note_id=str(r.get("note_id", "")),
            labels=labels[str(r["hadm_id"])],
            concepts=counts.get(str(r["hadm_id"]), 0),
        )
        for r in rows
    ]
    return assign_density_bands(notes)


def write_sample(sample: list[Note], path: Path) -> None:
    """`sample.csv` — the selection, auditable.

    Carries the strata as well as the ids, so a reader can check the sampling
    claim without rerunning the sampler.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["hadm_id", "note_id", "concepts", "density_band", *PHENOTYPES],
        )
        writer.writeheader()
        for note in sample:
            writer.writerow(
                {
                    "hadm_id": note.hadm_id,
                    "note_id": note.note_id,
                    "concepts": note.concepts,
                    "density_band": note.density_band,
                    **{p: int(p in note.labels) for p in PHENOTYPES},
                }
            )


def read_sample(path: Path) -> list[Note]:
    """Load `sample.csv` back.

    The run reads the *file*, never re-derives the selection. Re-running the
    sampler on the VM would make the sample depend on the concept cache and the
    corpus being present there too, and a resume after a code change could
    silently evaluate a different 500 notes than the predictions already in the
    store belong to.
    """
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        Note(
            hadm_id=str(r["hadm_id"]),
            note_id=str(r["note_id"]),
            labels=frozenset(p for p in PHENOTYPES if r.get(p) not in NEGATIVE),
            concepts=int(r["concepts"]),
            density_band=int(r["density_band"]),
        )
        for r in rows
    ]


def summarise(sample: list[Note], corpus: list[Note]) -> str:
    """A human-readable check of the sample, for `preflight` and the log."""
    rep = report(sample, corpus)
    lines = [
        f"sample {rep.n} of {rep.corpus_n} notes",
        "",
        f"{'stratum':<26} {'corpus':>8} {'target':>8} {'sample':>8} {'got':>8} {'dev':>8}",
    ]
    # Positive strata carry the `+` suffix; indexing the bare name would return
    # nothing and silently print a table with no phenotype rows at all.
    wanted = [(p, f"{p}+") for p in PHENOTYPES]
    wanted += [(f"density {i}", f"_density_{i}") for i in range(DENSITY_BANDS)]
    for label, key in wanted:
        row = rep.per_stratum.get(key)
        if not row:
            continue
        lines.append(
            f"{label:<26} {row['corpus_n']:>8} {row['corpus_prevalence']:>8.3f} "
            f"{row['sample_n']:>8} {row['sample_prevalence']:>8.3f} "
            f"{row['deviation']:>+8.3f}"
        )
    worst, dev = rep.worst_deviation()
    lines += [
        "",
        f"worst deviation: {worst} {dev:+.4f}",
        f"concepts/note: corpus median {statistics.median([n.concepts for n in corpus]):,.0f}"
        f"  sample median {statistics.median([n.concepts for n in sample]):,.0f}",
    ]
    thin = 20
    rare = [
        (p, rep.per_stratum[f"{p}+"]["sample_n"])
        for p in PHENOTYPES
        if rep.per_stratum[f"{p}+"]["sample_n"] < thin
    ]
    if rare:
        lines += [
            "",
            "thin phenotypes (per-phenotype F1 will be noisy; n_pos travels on every metric row):",
            *(f"    {p:<24} {n:>3} positives" for p, n in sorted(rare, key=lambda kv: kv[1])),
        ]
    return "\n".join(lines)


__all__ = [
    "DENSITY_BANDS",
    "Note",
    "SampleReport",
    "load_corpus",
    "read_concept_counts",
    "read_labels",
    "read_sample",
    "report",
    "select",
    "summarise",
    "write_sample",
]
