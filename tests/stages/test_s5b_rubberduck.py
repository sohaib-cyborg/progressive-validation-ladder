"""Tests for S5b rubber-duck semantic checking (toolvalidator/stages/s5b_rubberduck.py)."""

import json
from typing import Any

import pytest

from tests.conftest import FakeSandbox
from toolvalidator.config import load_settings
from toolvalidator.contracts import CapabilityRequest, ParamSpec, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult, ScadsClient
from toolvalidator.llm.trace import current_context
from toolvalidator.stages import s5b_rubberduck

TOOL = ToolArtifact(tool_id="t1", code="c = float(input())\nprint(c * 9 / 5 + 32)")
EXPLANATION = "Reads one number C from stdin and prints C * 9 / 5 + 32."


class _ScriptedClient:
    """Answers the explainer (generator) and the comparer (judge) from canned content."""

    def __init__(self, explainer: str, comparer: str) -> None:
        self.replies = {"generator": explainer, "judge": comparer}
        self.calls: list[tuple[str, str]] = []
        self.prompt_ids: list[str | None] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, user))
        self.prompt_ids.append(current_context().prompt_id)
        return LLMResult(
            model="m",
            content=self.replies[role],
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.0,
        )


def _client(*statuses: str, explanation: str = EXPLANATION) -> Any:
    checks = [
        {"requirement": f"r{i}", "status": status, "evidence": f"e{i}"}
        for i, status in enumerate(statuses)
    ]
    return _ScriptedClient(
        json.dumps({"explanation": explanation}), json.dumps({"requirements": checks})
    )


def test_all_requirements_met_scores_one(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_client("met", "met"))
    assert result.stage == "s5b_rubberduck"
    assert result.passed
    assert result.data["semantics_score"] == 1.0
    assert (result.data["met"], result.data["violated"], result.data["unknown"]) == (2, 0, 0)
    assert result.data["violations"] == []
    assert result.data["explanation"] == EXPLANATION
    assert record.results == [result]


def test_score_is_met_over_decided_and_unknown_is_left_out(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client("met", "met", "met", "violated", "unknown")
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=client)
    assert result.data["semantics_score"] == 0.75
    assert result.data["violations"] == [{"requirement": "r3", "evidence": "e3"}]


def test_violations_never_fail_the_stage(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    # An LLM never decides a verdict (CLAUDE.md rule 5): S5b only records a signal.
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_client("violated"))
    assert result.passed
    assert result.data["semantics_score"] == 0.0
    assert "1 violated" in result.detail


def test_no_decided_requirement_gives_no_score(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_client("unknown", "unknown"))
    assert result.passed
    assert result.data["semantics_score"] is None  # missing evidence is missing, not 0 or 1


def test_explainer_sees_only_code_and_comparer_only_the_request(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client("met")
    s5b_rubberduck.run(TOOL, record, fake_sandbox, client=client)
    (explain_role, explain_prompt), (compare_role, compare_prompt) = client.calls
    assert (explain_role, compare_role) == ("generator", "judge")
    assert TOOL.code in explain_prompt
    assert record.request.description not in explain_prompt
    assert TOOL.code not in compare_prompt
    assert record.request.description in compare_prompt
    assert EXPLANATION in compare_prompt


def test_calls_are_traced_with_their_prompt_ids(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client("met")
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=client)
    assert client.prompt_ids == ["explain_code", "compare_explanation"]
    assert result.data["prompts"] == ["explain_code@v1", "compare_explanation@v1"]


def test_status_is_normalised_before_validation(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    result = s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_client(" Met ", "VIOLATED"))
    assert (result.data["met"], result.data["violated"]) == (1, 1)


@pytest.mark.parametrize(
    ("explainer", "comparer"),
    [
        ("no JSON here", json.dumps({"requirements": []})),
        (json.dumps({"explanation": ""}), json.dumps({"requirements": []})),
        (json.dumps({"explanation": "x"}), json.dumps({"requirements": []})),
        (
            json.dumps({"explanation": "x"}),
            json.dumps({"requirements": [{"requirement": "r", "status": "maybe"}]}),
        ),
    ],
    ids=["no-json", "empty-explanation", "no-requirements", "unknown-status"],
)
def test_unusable_llm_output_raises(
    record: ValidationRecord, fake_sandbox: FakeSandbox, explainer: str, comparer: str
) -> None:
    with pytest.raises(LLMOutputError):
        s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_ScriptedClient(explainer, comparer))
    assert record.results == []  # infrastructure failures are not results


def test_executes_nothing(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    s5b_rubberduck.run(TOOL, record, fake_sandbox, client=_client("met"))
    assert fake_sandbox.calls == []


@pytest.mark.slow
def test_real_rubberduck_separates_a_correct_tool_from_a_wrong_one() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not (settings.generator_model and settings.judge_model):
        pytest.skip("SCADS not configured")
    request = CapabilityRequest(
        name="max_of_list",
        capability="max_of_list",
        description=(
            "The first line holds N. The second line holds N space-separated integers. "
            "Print the largest of them."
        ),
        inputs=[ParamSpec(name="stdin", type="string", description="N, then N integers")],
        outputs=[ParamSpec(name="stdout", type="string", description="The maximum")],
    )
    right = ToolArtifact(tool_id="right", code="input()\nprint(max(map(int, input().split())))")
    wrong = ToolArtifact(tool_id="wrong", code="input()\nprint(min(map(int, input().split())))")
    client = ScadsClient(settings)
    sandbox = FakeSandbox()
    good = s5b_rubberduck.run(right, ValidationRecord(request=request), sandbox, client=client)
    bad = s5b_rubberduck.run(wrong, ValidationRecord(request=request), sandbox, client=client)
    assert good.data["violated"] == 0, good.data
    assert isinstance(bad.data["violated"], int) and bad.data["violated"] >= 1, bad.data
