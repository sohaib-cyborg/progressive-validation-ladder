"""Tests for the independent judge (toolvalidator/testgen/judge.py)."""

import json
from typing import Any

import pytest

from toolvalidator.config import load_settings
from toolvalidator.contracts import CapabilityRequest
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult, ScadsClient
from toolvalidator.testgen.judge import build_user_prompt, judge_batch, judge_suite, judge_test
from toolvalidator.testgen.schemas import GeneratedTest

REQUEST = CapabilityRequest(
    name="add_two",
    capability="add_two",
    description="Read two integers separated by a space and print their sum.",
)
GOOD = GeneratedTest(input="2 3\n", output="5\n")
BAD = GeneratedTest(input="2 3\n", output="6\n")


class _FakeClient:
    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[tuple[str, str]] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, user))
        content = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        return LLMResult(
            model="m",
            content=content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.1,
        )


def _client(*contents: str) -> Any:
    return _FakeClient(*contents)


def test_judge_prompt_never_contains_the_tool_code() -> None:
    prompt = build_user_prompt(REQUEST, GOOD)
    assert "Read two integers" in prompt
    assert "expected output" in prompt
    assert "Program source" not in prompt and "```python" not in prompt


def test_judge_uses_the_judge_role_and_parses_verdict() -> None:
    fake = _client(json.dumps({"valid": True, "reason": "2+3=5"}))
    verdict = judge_test(fake, REQUEST, GOOD)
    assert verdict.valid is True
    assert fake.calls[0][0] == "judge"


def test_judge_suite_returns_one_verdict_per_test() -> None:
    fake = _client(json.dumps({"valid": True}), json.dumps({"valid": False, "reason": "2+3=5"}))
    verdicts = judge_suite(fake, REQUEST, [GOOD, BAD])
    assert [v.valid for _, v in verdicts] == [True, False]
    assert len(fake.calls) == 2


def test_judge_rejects_unusable_output() -> None:
    with pytest.raises(LLMOutputError):
        judge_test(_client("maybe?"), REQUEST, GOOD)


@pytest.mark.slow
def test_real_judge_accepts_correct_and_rejects_wrong_test() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not settings.judge_model:
        pytest.skip("SCADS not configured")
    client = ScadsClient(settings)
    assert judge_test(client, REQUEST, GOOD).valid is True
    assert judge_test(client, REQUEST, BAD).valid is False


# --- batched judging (one call per suite) -----------------------------------------


def _batch(*items: tuple[int, bool]) -> str:
    return json.dumps({"verdicts": [{"index": i, "valid": v, "reason": f"r{i}"} for i, v in items]})


def test_judge_batch_makes_one_judge_call_and_keeps_test_order() -> None:
    fake = _client(_batch((1, False), (0, True)))  # the model may answer out of order
    verdicts = judge_batch(fake, REQUEST, [GOOD, BAD])
    assert [(t, v.valid, v.reason) for t, v in verdicts] == [
        (GOOD, True, "r0"),
        (BAD, False, "r1"),
    ]
    assert len(fake.calls) == 1 and fake.calls[0][0] == "judge"
    prompt = fake.calls[0][1]
    assert "Test 0" in prompt and "Test 1" in prompt
    assert "Program source" not in prompt and "```python" not in prompt


@pytest.mark.parametrize(
    "reply",
    [_batch((0, True)), _batch((0, True), (0, False)), _batch((0, True), (1, True), (2, True))],
    ids=["missing", "duplicate", "out-of-range"],
)
def test_judge_batch_needs_exactly_one_verdict_per_test(reply: str) -> None:
    with pytest.raises(LLMOutputError, match="index"):
        judge_batch(_client(reply), REQUEST, [GOOD, BAD])


def test_judge_batch_of_nothing_makes_no_call() -> None:
    fake = _client(_batch())
    assert judge_batch(fake, REQUEST, []) == []
    assert fake.calls == []


@pytest.mark.slow
def test_real_batch_judge_accepts_correct_and_rejects_wrong_test() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not settings.judge_model:
        pytest.skip("SCADS not configured")
    verdicts = judge_batch(ScadsClient(settings), REQUEST, [GOOD, BAD])
    assert [v.valid for _, v in verdicts] == [True, False]
