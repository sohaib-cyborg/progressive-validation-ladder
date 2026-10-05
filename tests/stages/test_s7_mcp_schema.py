"""Tests for S7 MCP schema (toolvalidator/stages/s7_mcp_schema.py)."""

import json
from typing import Any

import pytest
from pydantic import JsonValue

from tests.conftest import FakeSandbox
from toolvalidator.contracts import CapabilityRequest, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult
from toolvalidator.llm.trace import current_context
from toolvalidator.stages import s7_mcp_schema
from toolvalidator.stages.s7_mcp_schema import schema_problems

REQUEST = CapabilityRequest(name="convert", capability="convert", description="Converts money.")
TOOL = ToolArtifact(
    tool_id="t1", code='def convert(amount: float, to: str = "EUR") -> str:\n    ...'
)
GOOD: dict[str, JsonValue] = {
    "name": "convert",
    "description": "Converts money.",
    "inputSchema": {
        "type": "object",
        "properties": {"amount": {"type": "number"}, "to": {"type": "string", "default": "EUR"}},
        "required": ["amount"],
    },
    "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}}},
}


class _Client:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []
        self.prompt_ids: list[str | None] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, user))
        self.prompt_ids.append(current_context().prompt_id)
        return LLMResult(model="m", content=self.content, reasoning=None, prompt_tokens=1,
                         completion_tokens=1, latency_s=0.0)  # fmt: skip


def _record() -> ValidationRecord:
    return ValidationRecord(request=REQUEST)


def test_a_valid_schema_is_recorded_and_the_stage_passes(fake_sandbox: FakeSandbox) -> None:
    client: Any = _Client(json.dumps(GOOD))
    record = _record()
    result = s7_mcp_schema.run(TOOL, record, fake_sandbox, client=client)
    assert result.stage == "s7_mcp_schema" and result.passed
    assert result.data["schema"] == GOOD
    assert result.data["valid"] is True and result.data["problems"] == []
    assert record.results == [result]
    assert fake_sandbox.calls == []  # reading code only; nothing runs


def test_the_generator_sees_the_request_and_the_code(fake_sandbox: FakeSandbox) -> None:
    client = _Client(json.dumps(GOOD))
    s7_mcp_schema.run(TOOL, _record(), fake_sandbox, client=client)  # type: ignore[arg-type]
    [(role, user)] = client.calls
    assert role == "generator"
    assert "Converts money." in user and "def convert(amount" in user
    assert client.prompt_ids == ["generate_mcp_schema"]


def test_an_invalid_schema_still_passes_with_its_problems(fake_sandbox: FakeSandbox) -> None:
    inputs = {"type": "object", "properties": {"a": {"type": "float"}}, "required": ["b"]}
    bad = {"name": "convert", "inputSchema": inputs}
    client: Any = _Client(json.dumps(bad))
    result = s7_mcp_schema.run(TOOL, _record(), fake_sandbox, client=client)
    assert result.passed
    assert result.data["valid"] is False
    assert result.category == "invalid_schema"


def test_a_reply_with_no_json_raises(fake_sandbox: FakeSandbox) -> None:
    with pytest.raises(LLMOutputError):
        s7_mcp_schema.run(TOOL, _record(), fake_sandbox, client=_Client("sorry"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("schema", "problem"),
    [
        ({"inputSchema": {"type": "object", "properties": {}}}, "name"),
        ({"name": "x"}, "inputSchema"),
        ({"name": "x", "inputSchema": {"type": "array", "properties": {}}}, "type"),
        ({"name": "x", "inputSchema": {"type": "object", "properties": {"a": {"type": "float"}}}},
         "a"),
        ({"name": "x", "inputSchema": {"type": "object", "properties": {}, "required": ["a"]}},
         "required"),
        ({"name": "x", "inputSchema": {"type": "object", "properties": {}},
          "outputSchema": {"type": "object", "properties": {"r": {}}}}, "r"),
    ],
)  # fmt: skip
def test_structural_rules(schema: dict[str, JsonValue], problem: str) -> None:
    problems = schema_problems(schema)
    assert problems and any(problem in p for p in problems)


def test_the_good_schema_has_no_problems() -> None:
    assert schema_problems(GOOD) == []
    union = {"name": "x", "inputSchema": {"type": "object",
             "properties": {"a": {"type": ["string", "null"]}}}}  # fmt: skip
    assert schema_problems(union) == []
