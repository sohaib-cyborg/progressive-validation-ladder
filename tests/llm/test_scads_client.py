"""Tests for the SCADS LLM client (toolvalidator/llm/scads_client.py)."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from toolvalidator.config import LLMSettings, load_settings
from toolvalidator.llm.scads_client import (
    LLMError,
    LLMOutputError,
    ScadsClient,
    parse_json_object,
)

SETTINGS = LLMSettings(api_key=SecretStr("k"), generator_model="gen-m", judge_model="judge-m")


class _FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _fake_openai(response: Any) -> Any:
    completions = _FakeCompletions(response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions), completions=completions)


def _response(content: str | None, reasoning: str | None = None) -> Any:
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    return SimpleNamespace(model="judge-m", choices=[SimpleNamespace(message=message)], usage=usage)


def test_complete_resolves_role_to_pinned_model_and_maps_result() -> None:
    fake = _fake_openai(_response("hello", reasoning="thinking..."))
    client = ScadsClient(SETTINGS, openai_client=fake)
    result = client.complete("judge", system="sys", user="usr")
    call = fake.completions.calls[0]
    assert call["model"] == "judge-m"
    assert call["temperature"] == 0.0
    assert call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert result.model == "judge-m"
    assert result.content == "hello"
    assert result.reasoning == "thinking..."
    assert (result.prompt_tokens, result.completion_tokens) == (11, 7)
    assert result.latency_s >= 0


def test_generator_role_uses_generator_model() -> None:
    fake = _fake_openai(_response("x"))
    ScadsClient(SETTINGS, openai_client=fake).complete("generator", system="s", user="u")
    assert fake.completions.calls[0]["model"] == "gen-m"


def test_unset_model_for_role_is_an_error() -> None:
    settings = LLMSettings(api_key=SecretStr("k"), generator_model="gen-m")
    with pytest.raises(LLMError, match="judge"):
        ScadsClient(settings, openai_client=_fake_openai(_response("x"))).complete(
            "judge", system="s", user="u"
        )


def test_missing_api_key_is_an_error() -> None:
    with pytest.raises(LLMError, match="SCADS_API_KEY"):
        ScadsClient(LLMSettings(generator_model="g", judge_model="j"))


def test_empty_response_is_an_output_error() -> None:
    no_choices = SimpleNamespace(model="m", choices=[], usage=None)
    with pytest.raises(LLMOutputError):
        ScadsClient(SETTINGS, openai_client=_fake_openai(no_choices)).complete(
            "generator", system="s", user="u"
        )
    with pytest.raises(LLMOutputError):
        ScadsClient(SETTINGS, openai_client=_fake_openai(_response(None))).complete(
            "generator", system="s", user="u"
        )


# --- parse_json_object -----------------------------------------------------------


def test_parse_plain_object() -> None:
    assert parse_json_object('{"a": 1, "b": [true, null]}') == {"a": 1, "b": [True, None]}


def test_parse_fenced_object_with_prose() -> None:
    text = 'Sure! Here you go:\n```json\n{"tests": [{"input": "1 2"}]}\n```\nHope it helps.'
    assert parse_json_object(text) == {"tests": [{"input": "1 2"}]}


def test_parse_rejects_raw_control_characters_inside_strings() -> None:
    # A literal newline inside a JSON string is invalid JSON; don't guess a repair.
    with pytest.raises(LLMOutputError):
        parse_json_object('{"input": "1' + chr(10) + '"}')


def test_parse_object_embedded_in_prose() -> None:
    assert parse_json_object('The answer is {"valid": false} as requested.') == {"valid": False}


@pytest.mark.parametrize("bad", ["", "no json here", "[1, 2]", '{"a": ', "```json\n[]\n```"])
def test_parse_rejects_non_objects_and_malformed(bad: str) -> None:
    with pytest.raises(LLMOutputError):
        parse_json_object(bad)


# --- real SCADS call (skipped without a key) --------------------------------------


@pytest.mark.slow
def test_real_generator_and_judge_calls() -> None:
    settings = load_settings().llm
    if settings.api_key is None or not settings.generator_model or not settings.judge_model:
        pytest.skip("SCADS_API_KEY / model IDs not configured")
    client = ScadsClient(settings)
    for role in ("generator", "judge"):
        result = client.complete(role, system="Answer tersely.", user="Reply with exactly: OK")  # type: ignore[arg-type]
        assert "OK" in result.content
        assert result.model
