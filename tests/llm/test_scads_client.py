"""Tests for the SCADS LLM client (toolvalidator/llm/scads_client.py)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import openai
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


# --- rate limits -------------------------------------------------------------------

_NOW = datetime(2026, 9, 24, 18, 34, 0, tzinfo=UTC)


def _rate_limited(reset: str = "2026-09-24 18:34:40 UTC") -> openai.RateLimitError:
    message = f"Rate limit exceeded ... Limit type: tokens. Limit resets at: {reset}"
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    return openai.RateLimitError(message, response=httpx.Response(429, request=request), body=None)


class _Throttled(_FakeCompletions):
    def __init__(self, failures: list[Exception], response: Any) -> None:
        super().__init__(response)
        self.failures = failures

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return self.response


def _throttled_client(
    failures: list[Exception], **settings: Any
) -> tuple[ScadsClient, list[float]]:
    completions = _Throttled(failures, _response("ok"))
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    waits: list[float] = []
    client = ScadsClient(
        SETTINGS.model_copy(update=settings),
        openai_client=fake,
        sleep=waits.append,
        clock=lambda: _NOW,
    )
    return client, waits


def test_rate_limit_waits_until_the_stated_reset_then_retries() -> None:
    client, waits = _throttled_client([_rate_limited(), _rate_limited()])
    assert client.complete("judge", system="s", user="u").content == "ok"
    assert waits == [41.0, 41.0]  # 40 s to the reset, plus a 1 s margin


def test_rate_limit_without_a_reset_time_waits_the_fallback() -> None:
    client, waits = _throttled_client([_rate_limited(reset="soon")])
    client.complete("judge", system="s", user="u")
    assert waits == [60.0]


def test_rate_limit_wait_is_capped() -> None:
    client, waits = _throttled_client(
        [_rate_limited(reset="2026-09-24 20:00:00 UTC")], max_rate_limit_wait_s=90.0
    )
    client.complete("judge", system="s", user="u")
    assert waits == [90.0]


def test_rate_limit_gives_up_after_the_configured_waits() -> None:
    client, waits = _throttled_client([_rate_limited()] * 3, rate_limit_waits=2)
    with pytest.raises(LLMError, match="rate limit"):
        client.complete("judge", system="s", user="u")
    assert len(waits) == 2


# --- completion cap ------------------------------------------------------------------


def test_every_call_caps_completion_tokens() -> None:
    fake = _fake_openai(_response("x"))
    ScadsClient(SETTINGS, openai_client=fake).complete("judge", system="s", user="u")
    assert fake.completions.calls[0]["max_tokens"] == 8192
    capped = SETTINGS.model_copy(update={"max_completion_tokens": 100})
    ScadsClient(capped, openai_client=fake).complete("judge", system="s", user="u")
    assert fake.completions.calls[1]["max_tokens"] == 100


def test_a_reply_cut_off_at_the_cap_is_unusable() -> None:
    response = _response('{"verdicts": [')
    response.choices[0].finish_reason = "length"
    fake = _fake_openai(response)
    with pytest.raises(LLMOutputError, match="truncated"):
        ScadsClient(SETTINGS, openai_client=fake).complete("judge", system="s", user="u")
