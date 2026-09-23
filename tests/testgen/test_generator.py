"""Tests for the test generator (toolvalidator/testgen/generator.py)."""

import json
from typing import Any

import pytest

from toolvalidator.config import load_settings
from toolvalidator.contracts import CapabilityRequest, IOExample, ParamSpec
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult, ScadsClient
from toolvalidator.testgen.generator import build_user_prompt, generate_tests

REQUEST = CapabilityRequest(
    name="add_two",
    capability="add_two",
    description="Read two integers separated by a space and print their sum.",
    inputs=[ParamSpec(name="stdin", type="string", description="Two integers, space separated")],
    outputs=[ParamSpec(name="stdout", type="string", description="Their sum")],
    rationale="No available tool adds two numbers from stdin.",
)
EXAMPLES = [IOExample(input="2 3\n", output="5\n")]


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, system, user))
        return LLMResult(
            model="m",
            content=self.content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.1,
        )


def _client(content: str) -> Any:
    return _FakeClient(content)


def test_prompt_contains_the_request_fields_examples_and_code() -> None:
    prompt = build_user_prompt(REQUEST, "print(sum(map(int, input().split())))", 3, EXAMPLES)
    assert "Read two integers" in prompt
    assert "Capability: add_two" in prompt
    assert "stdin: string" in prompt  # declared inputs
    assert "stdout: string" in prompt  # declared outputs
    assert "No available tool adds" in prompt  # rationale
    assert repr(EXAMPLES[0].input) in prompt  # examples appear escaped, not raw
    assert "print(sum" in prompt
    assert "Write 3 test cases" in prompt


def test_optional_inputs_are_marked() -> None:
    request = CapabilityRequest(
        name="search",
        capability="search",
        description="d",
        inputs=[
            ParamSpec(name="q", type="string", description="query"),
            ParamSpec(name="limit", type="integer", description="max hits", required=False),
        ],
    )
    prompt = build_user_prompt(request, None)
    assert "q: string — query" in prompt
    assert "limit: integer (optional)" in prompt


def test_prompt_without_examples_omits_that_section() -> None:
    assert "Examples from the task statement" not in build_user_prompt(REQUEST, None)


def test_prompt_without_code_says_nothing_about_source() -> None:
    assert "Program source" not in build_user_prompt(REQUEST, None)


def test_generate_parses_suite_and_uses_generator_role() -> None:
    fake = _client(
        json.dumps({"tests": [{"input": "1 2\n", "output": "3\n", "rationale": "basic"}]})
    )
    suite = generate_tests(fake, REQUEST, n=1)
    assert [t.output for t in suite.tests] == ["3\n"]
    assert fake.calls[0][0] == "generator"
    assert "DESCRIPTION is the specification" in fake.calls[0][1]


def test_generate_accepts_fenced_json() -> None:
    fake = _client('Here:\n```json\n{"tests": [{"input": "1 1", "output": "2"}]}\n```')
    assert len(generate_tests(fake, REQUEST).tests) == 1


def test_generate_rejects_unusable_output() -> None:
    with pytest.raises(LLMOutputError):
        generate_tests(_client("I cannot help with that."), REQUEST)


@pytest.mark.slow
def test_real_generator_produces_usable_tests() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not settings.generator_model:
        pytest.skip("SCADS not configured")
    suite = generate_tests(ScadsClient(settings), REQUEST, n=4)
    assert suite.tests, "generator returned no tests"
    for test in suite.tests:
        assert test.input and test.output
