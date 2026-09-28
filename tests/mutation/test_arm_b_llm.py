"""Tests for Arm B LLM-invented mutants (toolvalidator/mutation/arm_b_llm.py)."""

import json
from typing import Any

import pytest

from toolvalidator.config import load_settings
from toolvalidator.llm.scads_client import LLMOutputError, LLMResult, ScadsClient
from toolvalidator.llm.trace import current_context
from toolvalidator.mutation.arm_b_llm import DEFAULT_N, invent

TOOL = "a, b = map(int, input().split())\nprint(a + b if a < b else a - b)\n"
LE = "a, b = map(int, input().split())\nprint(a + b if a <= b else a - b)\n"
MUL = "a, b = map(int, input().split())\nprint(a * b if a < b else a - b)\n"


class _ScriptedClient:
    """Replies with canned content and records what it was asked."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str, str]] = []
        self.prompt_ids: list[str | None] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, system, user))
        self.prompt_ids.append(current_context().prompt_id)
        return LLMResult(
            model="m",
            content=self.content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.0,
        )


def _client(*mutants: Any) -> Any:
    return _ScriptedClient(json.dumps({"mutants": list(mutants)}))


def test_valid_mutants_are_kept_with_description_and_first_changed_line() -> None:
    result = invent(
        _client(
            {"description": "off by one in the comparison", "code": LE},
            {"description": "product instead of sum", "code": MUL},
        ),
        TOOL,
    )
    assert [m.description for m in result.mutants] == [
        "off by one in the comparison",
        "product instead of sum",
    ]
    assert [m.code for m in result.mutants] == [LE, MUL]
    assert {m.operator for m in result.mutants} == {"llm"}
    assert [m.line for m in result.mutants] == [2, 2]
    assert (result.candidates, result.dropped) == (2, 0)


def test_bad_candidates_are_dropped_and_counted() -> None:
    result = invent(
        _client(
            {"description": "does not parse", "code": "print(("},
            {"description": "same program", "code": TOOL},
            {"description": "only a comment", "code": "# bug\n" + TOOL},
            {"description": "real", "code": LE},
            {"description": "duplicate", "code": LE.replace("<=", " <= ")},
            {"description": "no code"},
            "not an object",
            {"description": "code is not text", "code": 3},
        ),
        TOOL,
    )
    assert [m.code for m in result.mutants] == [LE]
    assert (result.candidates, result.dropped) == (8, 7)


def test_more_than_n_mutants_are_cut_to_n() -> None:
    variants = [TOOL.replace("a - b", f"a - b - {i}") for i in range(1, 8)]
    result = invent(
        _client(*({"description": str(i), "code": c} for i, c in enumerate(variants))), TOOL
    )
    assert len(result.mutants) == DEFAULT_N
    assert (result.candidates, result.dropped) == (7, 2)


def test_fenced_json_reply_is_read() -> None:
    reply = "Here you go:\n```json\n" + json.dumps({"mutants": [{"code": LE}]}) + "\n```"
    result = invent(_ScriptedClient(reply), TOOL)
    assert [m.code for m in result.mutants] == [LE]
    assert result.mutants[0].description == ""


@pytest.mark.parametrize("reply", ["I cannot help.", json.dumps({"mutants": "none"})])
def test_unusable_reply_raises(reply: str) -> None:
    with pytest.raises(LLMOutputError):
        invent(_ScriptedClient(reply), TOOL)


def test_asks_the_generator_with_code_only_and_traces_the_prompt() -> None:
    client = _client({"code": LE})
    invent(client, TOOL, n=3)
    [(role, _system, user)] = client.calls
    assert role == "generator"
    assert TOOL.strip() in user
    assert "3" in user
    assert client.prompt_ids == ["invent_mutants"]


def test_unparsable_original_raises() -> None:
    with pytest.raises(SyntaxError):
        invent(_client(), "def (:")


@pytest.mark.slow
def test_real_generator_invents_usable_mutants() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not settings.generator_model:
        pytest.skip("SCADS not configured")
    result = invent(ScadsClient(settings), TOOL)
    assert result.mutants, f"no usable mutants ({result.candidates} returned)"
    for m in result.mutants:
        assert m.code.strip() != TOOL.strip()
