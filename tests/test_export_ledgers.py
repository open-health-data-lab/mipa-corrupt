"""The ledger export: what is shared holds no words, and still rebuilds the corpus."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

from robustehr.document import Document
from robustehr.ops import registry
from robustehr.runner import apply_operator, parse_severity
from robustehr.store import read_edits, replay, write_run

SCRIPT = Path(__file__).resolve().parents[1] / "release" / "export_ledgers.py"

NOTES = {
    "n1": "HISTORY: The patient has hypertension and diabetes mellitus. Started lisinopril daily.\n",
    "n2": "ASSESSMENT: Chronic systolic heart failure, stable. Continue furosemide and metoprolol.\n",
}


def load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("export_ledgers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def study_style_run(directory: Path) -> None:
    """A run stored the way the study's were: without the notes, so untrimmed."""
    registry.register_builtins()
    operator = registry.get("input.typo")()
    doses, edits = [], []
    for uid, text in NOTES.items():
        result = apply_operator(
            Document.from_text(text, uid=uid), operator, operator.meta, parse_severity("0.50")
        )
        doses.append(result.dose)
        edits.append(result.apply_result.applied)
    write_run(directory, run_id="t", doses=doses, edits=edits, corpus="corpus")


def test_the_export_keeps_no_word_and_replays(tmp_path: Path) -> None:
    experiments = tmp_path / "experiments"
    condition = experiments / "exp1" / "typographical_errors" / "low"
    study_style_run(condition)
    assert max(len(r.replacement) for r in read_edits(condition)) > 1

    notes = tmp_path / "notes.csv"
    with notes.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["note_id", "text"])
        writer.writerows(NOTES.items())

    out = tmp_path / "release"
    module = load_script()
    args = ["--experiments", str(experiments), "--notes", str(notes), "--out", str(out)]
    assert module.main(args) == 0

    exported = out / "exp1" / "typographical_errors" / "low"
    rows = read_edits(exported)
    assert rows
    assert max(len(r.replacement) for r in rows) == 1
    assert all(r.verified for r in replay(exported, NOTES))
    assert (exported / "dose.jsonl").read_bytes() == (condition / "dose.jsonl").read_bytes()

    manifest = json.loads((exported / "manifest.json").read_text())
    assert manifest["replacement_form"] == "minimal_diff"
    assert manifest["export"]["cells_verified"] == len(NOTES)
    index = json.loads((out / "index.json").read_text())
    assert index["conditions"] == 1
    assert index["replacement_chars_exported"] < index["replacement_chars_as_generated"]


def test_an_export_with_nothing_to_export_fails_loudly(tmp_path: Path) -> None:
    notes = tmp_path / "notes.csv"
    notes.write_text("note_id,text\n", encoding="utf-8")
    args = ["--experiments", str(tmp_path), "--notes", str(notes), "--out", str(tmp_path / "o")]
    assert load_script().main(args) == 1
