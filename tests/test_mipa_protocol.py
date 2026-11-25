"""The vendored MIPA protocol must not drift from MIPA's own source.

`mipa_protocol.py` copies MIPA's prompt, phenotype list, descriptions and JSON
parser rather than importing them, because importing MIPA pulls in torch,
transformers and a service-account read at module scope. The cost of copying is
that the copy can rot, and a rotted prompt invalidates every number the
experiment produces while looking completely fine.

So these tests read MIPA's actual files and compare. They **skip** when the MIPA
checkout is absent — CI has no copy — which means they protect the developer who
has both repos, which is the only person who can introduce the drift.

Whitespace is normalised before comparison: MIPA's prompt literals carry trailing
spaces on several lines, our copy does not, and neither the model nor the
comparison should care. Everything else must match exactly, including MIPA's two
typos.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from mipa import protocol as proto

#: The MIPA checkout this protocol is vendored from. An environment variable
#: rather than a path: the comparison is a provenance check that only the author
#: of a given machine can run, and hardcoding one developer's home directory made
#: it unrunnable everywhere else while looking like it should work.
MIPA = Path(os.environ.get("MIPA_SOURCE_ROOT", "/nonexistent"))
CONSTANTS = MIPA / "scripts" / "constants.py"
LLM_MODULE = MIPA / "scripts" / "llm" / "llm_module.py"

needs_mipa = pytest.mark.skipif(
    not CONSTANTS.exists(),
    reason="set MIPA_SOURCE_ROOT to a MIPA checkout to run the provenance checks",
)


def literal(path: Path, name: str) -> object:
    """A module-level literal from a MIPA file, without importing it.

    `ast` rather than `import`: importing `constants.py` runs `load_dotenv` and
    importing `llm_module` pulls in torch. Parsing the source gets the value with
    no side effects at all.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found at module level in {path}")


def squash(text: str) -> str:
    """Collapse runs of whitespace, so trailing spaces do not fail a comparison."""
    return re.sub(r"\s+", " ", text).strip()


class TestPrompts:
    @needs_mipa
    def test_system_prompt_matches(self) -> None:
        assert squash(proto.SYSTEM_PROMPT) == squash(str(literal(CONSTANTS, "SYSTEM_PROMPT")))

    @needs_mipa
    def test_zero_shot_prompt_matches(self) -> None:
        assert squash(proto.PROMPT_ZERO_SHOT) == squash(str(literal(CONSTANTS, "PROMPT_ZERO_SHOT")))

    @needs_mipa
    def test_the_prompt_placeholders_are_unchanged(self) -> None:
        """`{phenotype}` and `{discharge_summary}`, and the literal-brace JSON example.

        A stray `.format()`-visible brace would raise at prompt-build time on the
        first real call rather than here, which is a bad place to find out.
        """
        mipa = str(literal(CONSTANTS, "PROMPT_ZERO_SHOT"))
        for field in ("{phenotype}", "{discharge_summary}"):
            assert field in proto.PROMPT_ZERO_SHOT
            assert proto.PROMPT_ZERO_SHOT.count(field) == mipa.count(field)


class TestPhenotypes:
    @needs_mipa
    def test_the_sixteen_phenotypes_match_in_content(self) -> None:
        assert set(proto.PHENOTYPES) == set(literal(CONSTANTS, "PHENOTYPES"))

    def test_there_are_sixteen(self) -> None:
        assert len(proto.PHENOTYPES) == 16
        assert len(set(proto.PHENOTYPES)) == 16

    def test_every_phenotype_has_a_description(self) -> None:
        """The prompt interpolates the description; a missing one is a KeyError mid-run."""
        assert set(proto.PHENOTYPE_DESCRIPTIONS) == set(proto.PHENOTYPES)

    @needs_mipa
    def test_descriptions_match_mipa(self) -> None:
        """Parsed out of the function body, since MIPA defines these inside a method."""
        source = LLM_MODULE.read_text(encoding="utf-8")
        start = source.index("phenotypes_string = {")
        block = source[start + source[start:].index("{") :]
        depth, end = 0, None
        for i, ch in enumerate(block):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                end = i + 1
                break
        assert end is not None
        mipa_descriptions = ast.literal_eval(block[:end])
        assert mipa_descriptions == proto.PHENOTYPE_DESCRIPTIONS

    def test_mipa_typos_are_preserved(self) -> None:
        """Two typos are part of the published prompt and must not be 'fixed'.

        Correcting them would silently change the protocol and make our numbers
        incomparable with MIPA's, for a cosmetic gain.
        """
        assert (
            proto.PHENOTYPE_DESCRIPTIONS["c_diff_past"]
            == "Clostridium Difficile Before During Current Hospital Stay"
        )
        assert proto.PHENOTYPE_DESCRIPTIONS["vte_complication"].startswith(
            "Venous Thromboembolis (occuring"
        )


class TestGenerationParameters:
    @needs_mipa
    def test_temperature_matches_mipas_default(self) -> None:
        """MIPA's phenotyping path never overrides `LLMParser`'s default."""
        source = LLM_MODULE.read_text(encoding="utf-8")
        match = re.search(
            r"def __init__\(self, model_name.*?temperature\s*=\s*([\d.]+)", source, re.DOTALL
        )
        assert match, "could not find LLMParser.__init__ temperature default"
        assert float(match.group(1)) == proto.TEMPERATURE

    def test_no_extra_generation_parameters_crept_in(self) -> None:
        """MIPA sets no max_tokens/top_p/seed/stop. Absence is the setting."""
        assert proto.RESPONSE_FORMAT == {"type": "json_object"}


class TestMessageConstruction:
    def test_the_system_prompt_is_sent_by_default(self) -> None:
        messages = proto.build_messages("hypertension", "note text")
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_the_user_message_carries_the_description_not_the_key(self) -> None:
        messages = proto.build_messages("hfpef", "note text")
        user = messages[-1]["content"]
        assert "Heart Failure with Preserved Ejection Fraction" in user
        assert "hfpef" not in user
        assert "note text" in user

    def test_an_unknown_phenotype_fails_loudly(self) -> None:
        with pytest.raises(KeyError, match="unknown phenotype"):
            proto.build_messages("not_a_phenotype", "note")

    def test_the_json_example_survives_formatting(self) -> None:
        """`{{...}}` must render as literal braces, not blow up `.format()`."""
        user = proto.build_messages("obesity", "note")[-1]["content"]
        assert '{"phenotype": "Obesity", "status": "1 or 0"}' in user


class TestParser:
    """MIPA's parser is permissive by design; these pin the behaviour it has."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('{"phenotype": "Obesity", "status": "1"}', 1),
            ('{"phenotype": "Obesity", "status": "0"}', 0),
            ('{"status": 1}', 1),
            ('```json\n{"status": "1"}\n```', 1),
            ('Here is my answer:\n{"status": "0"}', 0),
            ('{"result": {"phenotype": "X", "status": "1"}}', 1),  # innermost wins
            ('{status: "1"}', 1),  # unquoted key
            ('{"status": "1"} // confident', 1),  # comment stripped
        ],
    )
    def test_accepted_shapes(self, raw: str, expected: int) -> None:
        prediction, status = proto.parse_prediction(raw)
        assert (prediction, status) == (expected, proto.ParseStatus.OK)

    @pytest.mark.parametrize(
        ("raw", "expected_status"),
        [
            ("", proto.ParseStatus.NO_JSON),
            ("I cannot answer that.", proto.ParseStatus.NO_JSON),
            ('{"phenotype": "Obesity"}', proto.ParseStatus.NO_STATUS),
            ('{"status": "yes"}', proto.ParseStatus.NO_STATUS),
        ],
    )
    def test_rejected_shapes(self, raw: str, expected_status: str) -> None:
        prediction, status = proto.parse_prediction(raw)
        assert prediction is None
        assert status == expected_status

    def test_an_out_of_range_status_is_recorded_not_coerced(self) -> None:
        """MIPA's regex would read `"10"` as 10; reading that as positive is worse
        than admitting the model did not answer the question."""
        prediction, status = proto.parse_prediction('{"status": "10"}')
        assert prediction is None
        assert status == proto.ParseStatus.BAD_VALUE

    def test_parsing_is_pure(self) -> None:
        """No global state — the runner calls this from many coroutines at once."""
        raw = '{"status": "1"}'
        assert proto.parse_prediction(raw) == proto.parse_prediction(raw)
