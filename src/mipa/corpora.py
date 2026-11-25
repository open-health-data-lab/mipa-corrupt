"""Finding the 28 corpora and reading the 500 notes out of each.

The corruption engine writes `data/experiments/baseline/notes.csv` and
`data/experiments/exp1/<corruption>/<severity>/notes.csv`. That layout *is* the
condition list — enumerating the directory rather than hardcoding 28 names means
a condition that failed to generate shows up as a missing corpus at preflight
instead of as a silently absent row in the results table.

Notes are read one condition at a time and filtered to the sample as they are
read. All 28 corpora together are ~450 MB of clinical text, which does not fit
comfortably on the 2 GB VM alongside a Python process holding 24,000 in-flight
request bodies; one condition's 500 notes is about 5 MB.
"""

from __future__ import annotations

import csv
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

BASELINE = "baseline"
EXPERIMENT = "exp1"

#: The baseline writes `note_text`, corrupted corpora write `note_corrupted`.
#: Both are accepted and neither is guessed at: a corpus carrying both, or
#: neither, is a generation bug worth failing on rather than papering over.
TEXT_COLUMNS = ("note_text", "note_corrupted")

#: MIMIC-IV notes run to 40k characters and the corpus is 1,388 of them, so the
#: default 128 KB field limit truncates silently — which would send a clipped
#: note to the model and report the result as a corruption effect.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


@dataclass(frozen=True, slots=True)
class Condition:
    """One corpus: the clean baseline, or one corruption at one severity."""

    name: str
    corruption: str
    severity: str
    notes_csv: Path
    #: Which experiment produced this corpus. `exp1` corrupts the whole
    #: document; `exp2` restricts to clinical content via `ClinicalSalience`.
    experiment: str = EXPERIMENT

    @property
    def is_baseline(self) -> bool:
        return self.name == BASELINE


def discover(root: Path, experiment: str = EXPERIMENT) -> list[Condition]:
    """Every condition present under `root`, baseline first.

    Baseline first because the runner writes results in this order and a partial
    run is far more useful with the reference arm complete: every delta needs it,
    and without it the corrupted arms cannot be interpreted at all.
    """
    conditions = []

    baseline = root / BASELINE / "notes.csv"
    if baseline.exists():
        conditions.append(
            Condition(name=BASELINE, corruption="none", severity="none", notes_csv=baseline)
        )

    experiment_root = root / experiment
    if experiment_root.exists():
        for corruption in sorted(p for p in experiment_root.iterdir() if p.is_dir()):
            for severity in sorted(p for p in corruption.iterdir() if p.is_dir()):
                notes = severity / "notes.csv"
                if notes.exists():
                    conditions.append(
                        Condition(
                            name=_condition_name(experiment, corruption.name, severity.name),
                            corruption=corruption.name,
                            severity=severity.name,
                            experiment=experiment,
                            notes_csv=notes,
                        )
                    )
    return conditions


def _condition_name(experiment: str, corruption: str, severity: str) -> str:
    """`typographical_errors/low` for exp1, `exp2/typographical_errors/low` beyond.

    Two reasons the experiment has to be in the name rather than only in a column:

    * **Store keys.** A prediction is keyed on
      ``sha256(document|model|condition|phenotype)``. Experiment 1 and Experiment 2
      both contain `typographical_errors/low` over the same 500 notes, so an
      unprefixed name makes them the same key — the second run would look
      complete on arrival and silently return the first run's answers.
    * **Reading the results.** The two conditions differ only in *where* the
      corruption landed: whole document versus clinical content. A results table
      that calls both `typographical_errors/low` cannot be read correctly, which
      is the ambiguity `docs/validation-protocol.md` §9 exists to forbid.

    Experiment 1 keeps its bare names so the completed run's keys stay valid.
    """
    return (
        f"{corruption}/{severity}"
        if experiment == EXPERIMENT
        else (f"{experiment}/{corruption}/{severity}")
    )


def read_notes(path: Path, keep: Iterable[str] | None = None) -> dict[str, str]:
    """`hadm_id` -> note text, restricted to `keep` if given.

    Filtering during the read rather than after: the whole file is 16 MB and the
    sample is 36% of it, and on a 2 GB VM the difference between streaming and
    materialising is the difference between working and being OOM-killed
    mid-condition.
    """
    wanted = set(keep) if keep is not None else None
    notes: dict[str, str] = {}

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        column = _text_column(reader.fieldnames or [], path)
        for row in reader:
            hadm_id = str(row["hadm_id"])
            if wanted is None or hadm_id in wanted:
                notes[hadm_id] = row[column]

    if wanted is not None and (missing := wanted - set(notes)):
        raise SystemExit(
            f"{path} is missing {len(missing)} sampled note(s), e.g. {sorted(missing)[:3]}. "
            "The sample and this corpus were built from different corpora; rerun `sample` "
            "or regenerate the condition."
        )
    return notes


def _text_column(fieldnames: Iterable[str], path: Path) -> str:
    present = [c for c in TEXT_COLUMNS if c in fieldnames]
    if len(present) != 1:
        raise SystemExit(
            f"{path} has {len(present)} of the expected text columns {TEXT_COLUMNS} "
            f"(found {sorted(set(fieldnames) & set(TEXT_COLUMNS))}). A corpus must carry "
            "exactly one, or the runner would have to guess which text to send."
        )
    return present[0]


__all__ = [
    "BASELINE",
    "EXPERIMENT",
    "TEXT_COLUMNS",
    "Condition",
    "discover",
    "read_notes",
]
