"""The placement audit must classify a token the way the targeting rule does.

`edit_placement.py` answers "did exp2's edits land on clinical content", and it
can only answer that if its notion of *clinical* is the one the targeting rule
used when it selected the spans. Two implementations of the same predicate is
exactly the situation where they drift, so this pins them together.

The package-side property — that `ClinicalSalience` admits a drug regardless of
its salience — is asserted in RobustEHR's own `tests/test_clinical_salience.py`.
What is checked here is narrower and belongs with the study: that this script
agrees with it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[1] / "analysis" / "edit_placement.py"


def _load_audit():  # type: ignore[no-untyped-def]
    """Import `edit_placement.py` by path — `analysis/` is not a package."""
    spec = importlib.util.spec_from_file_location("edit_placement", AUDIT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["edit_placement"] = module
    spec.loader.exec_module(module)
    return module


def test_a_low_salience_drug_is_clinical() -> None:
    """`metoprolol` sits at salience 0.004 because the gold never annotates
    drugs; the targeting rule still admits it via the drug clause, and the
    placement audit must agree — checking the salience table first mislabelled
    exactly these tokens and understated exp2's clinical share.
    """
    from robustehr.drugs import load_synonyms

    if "metoprolol" not in load_synonyms().to_brand:
        pytest.skip("drug synonym map not built")
    kind = _load_audit().classify_fn()
    for drug in ("metoprolol", "acetaminophen", "lisinopril"):
        assert kind(drug) == "clinical", drug


def test_prose_is_still_not_clinical() -> None:
    kind = _load_audit().classify_fn()
    assert kind("patient") == "non-clinical"
    assert kind("she") == "non-clinical"
