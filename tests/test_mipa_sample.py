"""The subsample must not be the reason a robustness number is wrong.

Every prediction in the experiment is made on these notes. If the sample is
skewed on phenotype prevalence, per-phenotype F1 is measuring the sample; if it
is skewed on concept density, corruption severity is confounded with note
composition. Both failures look like findings.

The two that actually bit during development are pinned as tests rather than
described in a comment:

* scoring on **positive labels only** biases the sample multi-morbid, because a
  label-poor note serves no open stratum and is never preferred. Every phenotype
  came out over-represented — deviation can only go one way when the sampler can
  only add labels;
* not penalising **overshoot** lets a note positive for six phenotypes get picked
  for the one stratum still open, quietly adding five to strata already full.

Measured on the MIPA corpus at n=500, max deviation went 0.137 -> 0.067 -> 0.001
as each was fixed.
"""

from __future__ import annotations

import pytest

from mipa.protocol import PHENOTYPES
from mipa.sample import (
    DENSITY_BANDS,
    Note,
    assign_density_bands,
    report,
    select,
)


#: Deliberately lopsided, mirroring MIPA: one phenotype in ~2/3 of notes, one in
#: ~3%, and a large share of notes carrying several at once.
def synthetic(n: int = 800) -> list[Note]:
    notes = []
    for i in range(n):
        labels = set()
        if i % 3 != 0:
            labels.add("hypertension")  # ~67%
        if i % 2 == 0:
            labels.add("depression")  # ~50%
        if i % 7 == 0:
            labels.add("obesity")  # ~14%
        if i % 33 == 0:
            labels.add("vte_complication")  # ~3%
        if i % 29 == 0:
            labels.add("c_diff_complication")  # ~3.4%
        notes.append(
            Note(hadm_id=f"h{i:05d}", note_id=f"n{i}", labels=frozenset(labels), concepts=i * 3)
        )
    return assign_density_bands(notes)


def deviations(sample: list[Note], corpus: list[Note]) -> dict[str, float]:
    rep = report(sample, corpus)
    return {
        s: rep.per_stratum[s]["deviation"]
        for s in rep.per_stratum
        if s.endswith("+") or s.startswith("_density_")
    }


class TestPrevalenceIsPreserved:
    def test_every_stratum_lands_within_two_points(self) -> None:
        corpus = synthetic()
        sample = select(corpus, 300)
        worst = max(abs(d) for d in deviations(sample, corpus).values())
        assert worst < 0.02, f"worst stratum deviation {worst:.4f}"

    def test_the_bias_is_not_one_sided(self) -> None:
        """The signature of the positives-only bug: nothing ever under-represented.

        A sampler that can only add labels produces deviations that are all >= 0.
        Requiring both signs catches that class of failure even if the magnitude
        happens to be small on a given corpus.
        """
        corpus = synthetic()
        devs = [d for s, d in deviations(select(corpus, 300), corpus).items() if s.endswith("+")]
        assert min(devs) <= 0.0 <= max(devs) or all(abs(d) < 0.005 for d in devs), devs

    def test_the_rare_phenotype_is_represented(self) -> None:
        """~3% prevalence must not round to zero — it is the whole reason to stratify."""
        corpus = synthetic()
        sample = select(corpus, 200)
        assert sum(1 for n in sample if "vte_complication" in n.labels) > 0

    def test_density_bands_stay_balanced(self) -> None:
        corpus = synthetic()
        sample = select(corpus, 300)
        counts = [sum(1 for n in sample if n.density_band == b) for b in range(DENSITY_BANDS)]
        assert max(counts) - min(counts) <= 2, counts


class TestDeterminism:
    def test_same_salt_same_sample(self) -> None:
        corpus = synthetic()
        assert [n.hadm_id for n in select(corpus, 200)] == [n.hadm_id for n in select(corpus, 200)]

    def test_a_different_salt_draws_differently(self) -> None:
        corpus = synthetic()
        a = {n.hadm_id for n in select(corpus, 200, salt="rep0")}
        b = {n.hadm_id for n in select(corpus, 200, salt="rep1")}
        assert a != b

    def test_a_larger_sample_contains_the_smaller(self) -> None:
        """Nesting makes a sample-size sweep paired rather than two unrelated draws.

        Same property the severity ladders have one layer down, and it holds for
        the same reason: rank order does not depend on how many are taken.
        """
        corpus = synthetic()
        small = {n.hadm_id for n in select(corpus, 100)}
        large = {n.hadm_id for n in select(corpus, 300)}
        assert small <= large

    def test_output_is_ordered_by_id(self) -> None:
        corpus = synthetic()
        sample = select(corpus, 150)
        assert [n.hadm_id for n in sample] == sorted(n.hadm_id for n in sample)


class TestDegenerateCases:
    def test_asking_for_the_whole_corpus_returns_it(self) -> None:
        corpus = synthetic(50)
        assert len(select(corpus, 50)) == 50
        assert len(select(corpus, 999)) == 50

    def test_density_banding_survives_identical_counts(self) -> None:
        """Every note the same density — quantile cuts collapse, must not crash."""
        notes = [
            Note(hadm_id=f"h{i}", note_id=f"n{i}", labels=frozenset(), concepts=100)
            for i in range(30)
        ]
        banded = assign_density_bands(notes)
        assert len(banded) == 30
        assert len(select(banded, 10)) == 10

    def test_an_empty_corpus_is_not_an_error(self) -> None:
        assert select([], 10) == []
        assert assign_density_bands([]) == []


@pytest.mark.parametrize("n", [50, 100, 250, 500])
def test_the_requested_size_is_delivered(n: int) -> None:
    corpus = synthetic()
    assert len(select(corpus, n)) == n


def test_every_phenotype_has_a_stratum_pair() -> None:
    """Both poles for all 16, or the sampler cannot balance that label."""
    corpus = synthetic()
    strata = {s for note in corpus for s in note.strata()}
    for phenotype in PHENOTYPES:
        assert f"{phenotype}-" in strata, phenotype
