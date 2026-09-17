"""Tests for S3 test generation (toolvalidator/stages/s3_testgen.py)."""

import json
from typing import Any

import pytest

from tests.conftest import FakeSandbox
from toolvalidator.contracts import ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult
from toolvalidator.stages import s3_testgen

TOOL = ToolArtifact(tool_id="t1", code="print(int(input()) + 1)")


class _ScriptedClient:
    """Answers generator and judge calls from canned content."""

    def __init__(self, generator: str, *judge: str) -> None:
        self.generator = generator
        self.judge = list(judge)
        self.roles: list[str] = []
        self.prompts: list[str] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.roles.append(role)
        self.prompts.append(user)
        content = self.generator if role == "generator" else self.judge.pop(0)
        return LLMResult(
            model="m",
            content=content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.0,
        )


def _client(tests: list[dict[str, str]], verdicts: list[bool]) -> Any:
    generated = json.dumps({"tests": tests})
    judged = [json.dumps({"valid": v, "reason": "because"}) for v in verdicts]
    return _ScriptedClient(generated, *judged)


def test_accepted_tests_are_recorded_and_stage_passes(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client([{"input": "1", "output": "2"}, {"input": "5", "output": "7"}], [True, False])
    result = s3_testgen.run(TOOL, record, fake_sandbox, client=client, n=2)
    assert result.passed  # S3 never rejects a tool
    assert result.stage == "s3_testgen"
    assert result.data["generated"] == 2
    assert result.data["accepted"] == 1
    assert result.data["tests"] == [{"input": "1", "output": "2"}]
    rejected = result.data["rejected"]
    assert isinstance(rejected, list) and rejected[0]["reason"] == "because"  # type: ignore[index]
    assert record.results == [result]
    assert fake_sandbox.calls == []  # S3 executes nothing


def test_generator_sees_code_and_judge_does_not(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client([{"input": "1", "output": "2"}], [True])
    s3_testgen.run(TOOL, record, fake_sandbox, client=client, n=1)
    assert client.roles == ["generator", "judge"]
    generator_prompt, judge_prompt = client.prompts
    assert TOOL.code in generator_prompt
    assert TOOL.code not in judge_prompt


def test_show_code_false_hides_the_tool_from_the_generator(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client([{"input": "1", "output": "2"}], [True])
    result = s3_testgen.run(TOOL, record, fake_sandbox, client=client, n=1, show_code=False)
    assert TOOL.code not in client.prompts[0]
    assert result.data["saw_code"] is False


def test_all_tests_rejected_still_passes_with_no_tests(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _client([{"input": "1", "output": "9"}], [False])
    result = s3_testgen.run(TOOL, record, fake_sandbox, client=client, n=1)
    assert result.passed
    assert result.data["accepted"] == 0
    assert result.data["tests"] == []


def test_unusable_generator_output_raises(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    client = _ScriptedClient("sorry, no JSON here")
    with pytest.raises(LLMOutputError):
        s3_testgen.run(TOOL, record, fake_sandbox, client=client, n=1)
