"""The MIPA zero-shot phenotyping protocol, vendored verbatim.

**Copied, not imported, and that is a decision rather than laziness.** MIPA's
`scripts/llm/llm_module.py` is 4,283 lines; it imports `torch` and
`transformers` at module scope and runs `setup_gcs_access()` — which reads a
service-account file — as an import side effect. Importing it on a 2-vCPU
evaluation VM is not viable, and depending on a sibling checkout that is not
installed, versioned or packaged would make this runner unreproducible.

So the four things that *define* the protocol are copied here, each with the
MIPA file and line it came from, and `tests/test_mipa_protocol.py` reads MIPA's
own source and asserts the copies still match. A silent divergence between this
prompt and MIPA's is the single failure that would invalidate every number the
experiment produces, so it is the one thing tested hardest.

Provenance, all under
``open-health-data-lab/MIPA/`` at the commit these were taken from:

===========================  ==========================================
this module                   MIPA source
===========================  ==========================================
``SYSTEM_PROMPT``             ``scripts/constants.py:246-259``
``PROMPT_ZERO_SHOT``          ``scripts/constants.py:261-281``
``PHENOTYPES``                ``scripts/constants.py:146-148``
``PHENOTYPE_DESCRIPTIONS``    ``scripts/llm/llm_module.py:380-397``
``check_double_bracket``      ``scripts/utils.py:1267-1284``
``fix_json`` ``validate_json``  ``scripts/utils.py:1286-1303``
``clean_json_classic``        ``scripts/utils.py:1333-1398``
``extract_status``            ``scripts/llm/llm_module.py:1177-1186``
===========================  ==========================================

Two deliberate departures from MIPA, both agreed with the experiment owner and
both recorded in ``run_summary.json`` so no reader has to infer them:

**1. `TextCleaner.clean_text` is NOT applied.** MIPA runs
``re.sub(r'\\s+', ' ', text)`` before every prompt (``llm_module.py:231-236``),
which collapses all whitespace. Under that, `render.break_removal` — which
replaces a structural break with a single space — produces text byte-identical
to the baseline, so the `loss_of_text_structure` arm would report exactly zero
degradation at all three severities *by construction*. Since the point of the
experiment is to measure what corruption costs, the corrupted text is sent as
generated. The same cleaner also deletes every character outside
``[\\w\\s.,':-]`` and expands 193 abbreviations, both of which would partially
repair other corruptions.

**2. The system prompt IS sent.** MIPA's sync path sends it
(``llm_module.py:537-556``); the async path that its CLI actually invokes
silently drops it (``llm_module.py:1553-1566``). That asymmetry is a bug rather
than a design choice, so the documented protocol is reproduced. ``SEND_SYSTEM_PROMPT``
below flips it for anyone who wants async-faithful numbers.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Prompts — MIPA/scripts/constants.py:246-281
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are a medical researcher specializing in analyzing discharge summaries for phenotype classification in epidemiologic studies.
Your task is to determine the presence or absence of a given condition based on the available evidence in the discharge summary.

Guidelines:
- Thoroughly examine the discharge summary for all relevant medical information.
- Prioritize documented clinical evidence over speculation.
- Interpret standard medical abbreviations and terminologies accurately.

Classification approach:
- Make decisive classifications based on the strongest available evidence.
- For uncertain cases, favor classifications supported by evidence.
- Maintain high accuracy, as your classifications will directly impact the study's validity.
"""

PROMPT_ZERO_SHOT = """
Analyze the discharge summary or a specific segment of it provided below to determine the presence of {phenotype}.
Use your professional judgment to critically assess the information presented and determine if the history, symptoms and treatments described indicate that the patient has {phenotype}.
It is critical to ensure accuracy in your analysis, as errors can have significant consequences.
Conclude with a JSON object stating the status of {phenotype} presence.
Only output 1 if the evidence is conclusive.

Discharge Summary or Segment to Analyze:
{discharge_summary}

Assessment Instructions:
1. Review all clinical information.
2. Determine whether there is conclusive evidence supporting a diagnosis of **{phenotype}**.
   - If conclusive evidence exists, respond with "status": "1"
   - If no conclusive evidence exists, respond with "status": "0"

- Your response must only contain a JSON object on a new line.
- Do not provide any explanations or additional text.
- The JSON object should follow this exact format:
{{"phenotype": "{phenotype}", "status": "1 or 0"}}
"""

#: Send the system prompt. True reproduces MIPA's sync path and its documented
#: intent; False reproduces the async path its CLI actually runs.
SEND_SYSTEM_PROMPT = True

# ---------------------------------------------------------------------------
# Phenotypes — MIPA/scripts/constants.py:146-148
# ---------------------------------------------------------------------------

PHENOTYPES: tuple[str, ...] = (
    "c_diff_complication",
    "c_diff_past",
    "dementia",
    "depression",
    "diabetes_type_1",
    "diabetes_type_2",
    "hfref",
    "hfpef",
    "hypertension",
    "sle",
    "metastatic_cancer",
    "obesity",
    "rheumatoid_arthritis",
    "alcohol_abuse",
    "vte_complication",
    "vte_past",
)

#: What the prompt actually interpolates — MIPA/scripts/llm/llm_module.py:380-397.
#:
#: The prompt receives the human-readable DESCRIPTION, not the snake_case key,
#: for every non-ETP strategy (`llm_module.py:417-430`). The two typos below are
#: MIPA's and are reproduced deliberately: "Before During" (for the past-infection
#: phenotype) and "Thromboembolis (occuring". They are part of the prompt the
#: published numbers were produced with, so correcting them would silently change
#: the protocol.
PHENOTYPE_DESCRIPTIONS: dict[str, str] = {
    "diabetes_type_1": "Type 1 Diabetes",
    "diabetes_type_2": "Type 2 Diabetes",
    "c_diff_complication": "Clostridium Difficile Infection During Current Hospital Stay",
    "c_diff_past": "Clostridium Difficile Before During Current Hospital Stay",
    "dementia": "Dementia",
    "depression": "Depression",
    "hypertension": "Hypertension",
    "hfpef": "Heart Failure with Preserved Ejection Fraction",
    "hfref": "Heart Failure with Reduced Ejection Fraction",
    "sle": "Systemic Lupus Erythematosus",
    "rheumatoid_arthritis": "Rheumatoid Arthritis (seropositive or seronegative)",
    "metastatic_cancer": "Solid Tumor with Metastasis (Stage IV)",
    "obesity": "Obesity",
    "alcohol_abuse": "Alcohol Abuse",
    "vte_past": (
        "Past Venous Thromboembolism (including DVT, PE, Splanchnic Venous "
        "Thrombosis, Cerebral Venous Sinus Thrombosis)"
    ),
    "vte_complication": (
        "Venous Thromboembolis (occuring during current hospital stay including "
        "DVT, PE, Splanchnic Venous Thrombosis, Cerebral Venous Sinus Thrombosis)"
    ),
}

# ---------------------------------------------------------------------------
# Generation parameters — MIPA/scripts/llm/llm_module.py:451, 1553-1573
# ---------------------------------------------------------------------------

#: MIPA's default and never overridden on the phenotyping path
#: (`llm_comprehensive_evaluation.py:1154-1159` constructs `LLMParser` without one).
TEMPERATURE = 0.5

#: MIPA sets no `max_tokens`, `top_p`, `seed` or `stop`. Absence is the setting;
#: adding any of them would be a protocol change.
RESPONSE_FORMAT: dict[str, str] = {"type": "json_object"}


def build_messages(phenotype: str, discharge_summary: str) -> list[dict[str, str]]:
    """The exact message list MIPA's zero-shot strategy sends for one note.

    One call per (note, phenotype) — MIPA never batches phenotypes into a single
    prompt (`llm_comprehensive_evaluation.py:734-738`), so neither does this.
    """
    description = PHENOTYPE_DESCRIPTIONS.get(phenotype)
    if description is None:
        raise KeyError(f"unknown phenotype {phenotype!r}; known: {list(PHENOTYPES)}")
    user = PROMPT_ZERO_SHOT.format(phenotype=description, discharge_summary=discharge_summary)
    if not SEND_SYSTEM_PROMPT:
        return [{"role": "user", "content": user}]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Parsing — MIPA/scripts/utils.py:1267-1398, llm_module.py:1111-1186
# ---------------------------------------------------------------------------


def fix_json(text: str) -> str:
    """MIPA/scripts/utils.py:1286-1296 — add a missing brace at either end."""
    if text.strip() and not text.strip().startswith("{"):
        text = "{" + text
    if text.strip() and not text.strip().endswith("}"):
        text += "}"
    return text


def validate_json(text: str) -> bool:
    """MIPA/scripts/utils.py:1299-1303."""
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def check_double_bracket(text: str) -> str | None:
    """MIPA/scripts/utils.py:1267-1284 — pull the innermost object out of nesting.

    A model that wraps its answer in an envelope (``{"result": {"status": "1"}}``)
    has the real object one level down, and MIPA takes the inner one.
    """
    match = re.search(r"\{[^{}]*\{[^{}]*\}[^{}]*\}", text, re.DOTALL)
    if match:
        inner = re.search(r"\{[^{}]*\}", match.group(), re.DOTALL)
        return inner.group() if inner else None
    fixed = fix_json(text)
    return fixed if validate_json(fixed) else text


def clean_json_classic(text: str) -> str | None:
    """MIPA/scripts/utils.py:1333-1398 — normalise a near-JSON string.

    Smart quotes and backticks to plain quotes, `//` comments stripped, sliced to
    the outermost braces, then bare keys and bare word values force-quoted. The
    justification-repair branch of MIPA's original is omitted: it exists for the
    COT strategies, and zero-shot returns no ``justification`` field.
    """
    if not text:
        return None
    text = re.sub(r"[“”]", '"', text)
    text = text.replace("`", '"').replace("\\_", "_")
    text = re.sub(r"//.*", "", text)
    text = text.replace(r"\"", '"').replace("\\\\", "\\")
    try:
        json_str = text[text.index("{") : text.rindex("}") + 1]
    except ValueError:
        return None
    json_str = re.sub(r"(\w+)\s*:", r'"\1":', json_str)
    json_str = re.sub(r":\s*([a-zA-Z]+)", r': "\1"', json_str)
    return json_str if validate_json(json_str) else None


def extract_json(output: str) -> dict[str, Any] | None:
    """MIPA/scripts/llm/llm_module.py:1111-1159 — the full extraction chain."""
    if not output:
        return None
    json_str = check_double_bracket(output)
    if not json_str:
        return None
    cleaned = clean_json_classic(json_str)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_status(parsed: dict[str, Any] | None) -> str | None:
    """MIPA/scripts/llm/llm_module.py:1177-1186 — the first digit run in ``status``.

    Returns a *string* of digits, as MIPA does; ``"1"`` and ``"status: 1"`` both
    give ``"1"``. Numeric coercion happens downstream.
    """
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    if status is None:
        return None
    match = re.search(r"\d+", str(status))
    return match.group(0) if match else None


class ParseStatus:
    """Why a prediction is missing, kept apart from the prediction itself.

    MIPA's `filter_incomplete_parsing` drops any note that failed to parse before
    evaluating. Under corruption, parse failures rise with severity, so that
    silently evaluates an easier subset at every step and flatters the model. The
    failures are recorded here and reported as a rate instead.
    """

    OK = "ok"
    NO_JSON = "no_json"
    NO_STATUS = "no_status"
    BAD_VALUE = "bad_value"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    EXHAUSTED = "exhausted"


def parse_prediction(output: str) -> tuple[int | None, str]:
    """``(prediction, parse_status)`` for one model response.

    A status outside {0, 1} is `bad_value` rather than being coerced: MIPA's
    regex would happily turn ``"status": "10"`` into 10, and silently reading
    that as positive is worse than recording that the model did not answer the
    question asked.
    """
    parsed = extract_json(output)
    if parsed is None:
        return None, ParseStatus.NO_JSON
    status = extract_status(parsed)
    if status is None:
        return None, ParseStatus.NO_STATUS
    if status not in ("0", "1"):
        return None, ParseStatus.BAD_VALUE
    return int(status), ParseStatus.OK


def departures() -> list[dict[str, str]]:
    """The two deliberate divergences from MIPA, machine-readable.

    The module docstring argues them; this puts them in `run_summary.json` beside
    the numbers they affect. A reader who finds this experiment's F1 differing
    from a published MIPA figure should not have to read source code to find out
    why, and a departure that lives only in prose is one that gets lost the first
    time the results are copied into a paper.
    """
    return [
        {
            "departure": "clean_text_not_applied",
            "mipa_source": "llm_module.py:231-236",
            "reason": (
                "MIPA collapses all whitespace before prompting, which makes "
                "loss_of_text_structure byte-identical to baseline — that arm would "
                "report exactly zero degradation by construction."
            ),
        },
        {
            "departure": "system_prompt_sent",
            "mipa_source": "llm_module.py:537-556 (sync) vs 1553-1566 (async)",
            "reason": (
                "MIPA's sync path sends the system prompt and its async path drops it. "
                "The asymmetry is a bug, so the documented protocol is reproduced."
            ),
            "override": "SEND_SYSTEM_PROMPT",
        },
    ]


__all__ = [
    "PHENOTYPES",
    "PHENOTYPE_DESCRIPTIONS",
    "PROMPT_ZERO_SHOT",
    "RESPONSE_FORMAT",
    "SEND_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "TEMPERATURE",
    "ParseStatus",
    "build_messages",
    "check_double_bracket",
    "clean_json_classic",
    "departures",
    "extract_json",
    "extract_status",
    "fix_json",
    "parse_prediction",
    "validate_json",
]
