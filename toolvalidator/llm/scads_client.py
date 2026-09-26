"""SCADS LLM client: the only place that talks to an LLM over the network.

LLM output is untrusted input (CLAUDE.md §7): callers parse it with
``parse_json_object`` and validate the result before use. Nothing here decides a verdict.
"""

import json
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from openai import APIError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from toolvalidator.config import LLMSettings

type Role = Literal["generator", "judge"]

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)
_OBJECT = TypeAdapter(dict[str, JsonValue])
_RESET = re.compile(r"resets at: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")
FALLBACK_RATE_LIMIT_WAIT_S = 60.0  # the observed SCADS window when no reset is stated
RATE_LIMIT_MARGIN_S = 1.0


class LLMError(RuntimeError):
    """The LLM could not be called (configuration, network, API error after retries)."""


class LLMOutputError(LLMError):
    """The LLM answered, but not with usable output."""


class LLMResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    content: str
    reasoning: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float


class ScadsClient:
    # Any: tests inject a fake with the same ``chat.completions.create`` shape.
    def __init__(
        self,
        settings: LLMSettings,
        *,
        openai_client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if settings.api_key is None:
            raise LLMError("SCADS_API_KEY is not set")
        self._settings = settings
        self._sleep = sleep
        self._clock = clock
        self._client = openai_client or OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_s,
            max_retries=settings.max_retries,
        )

    def complete(self, role: Role, *, system: str, user: str) -> LLMResult:
        model = self.model_for(role)
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        start = time.perf_counter()
        response = self._create(role, model, messages)
        latency = time.perf_counter() - start  # includes any rate-limit waits
        message = response.choices[0].message if response.choices else None
        content = message.content if message is not None else None
        if response.choices and getattr(response.choices[0], "finish_reason", None) == "length":
            cap = self._cap(role)
            raise LLMOutputError(f"{role} ({model}) reply truncated at {cap} completion tokens")
        if not isinstance(content, str):
            raise LLMOutputError(f"{role} ({model}) returned no content")
        usage = response.usage
        return LLMResult(
            model=response.model or model,
            content=content,
            reasoning=_reasoning(message),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            latency_s=latency,
        )

    def _create(self, role: Role, model: str, messages: list[ChatCompletionMessageParam]) -> Any:
        """One completion, waiting out HTTP 429s (never counted as a model answer)."""
        waits = 0
        while True:
            try:
                return self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=self._cap(role),
                )
            except RateLimitError as exc:
                if waits >= self._settings.rate_limit_waits:
                    raise LLMError(f"{role} call to {model}: rate limit persisted: {exc}") from exc
                waits += 1
                delay = self._rate_limit_delay(str(exc))
                print(f"[scads] {model} rate-limited, waiting {delay:.0f}s", file=sys.stderr)
                self._sleep(delay)
            except APIError as exc:
                raise LLMError(f"{role} call to {model} failed: {exc}") from exc

    def _cap(self, role: Role) -> int:
        if role == "generator":
            return self._settings.generator_max_completion_tokens
        return self._settings.max_completion_tokens

    def _rate_limit_delay(self, message: str) -> float:
        found = _RESET.search(message)
        if found is None:
            delay = FALLBACK_RATE_LIMIT_WAIT_S
        else:
            reset = datetime.strptime(found.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            delay = (reset - self._clock()).total_seconds() + RATE_LIMIT_MARGIN_S
        return min(max(delay, RATE_LIMIT_MARGIN_S), self._settings.max_rate_limit_wait_s)

    def model_for(self, role: Role) -> str:
        """The pinned model id for a role. Public so tracing can record what we asked for."""
        model = (
            self._settings.generator_model if role == "generator" else self._settings.judge_model
        )
        if not model:
            raise LLMError(f"no model configured for role {role!r} (SCADS_{role.upper()}_MODEL)")
        return model


def parse_json_object(text: str) -> dict[str, JsonValue]:
    """The first JSON object in ``text``, preferring fenced code blocks.

    Raises LLMOutputError if there is none.
    """
    for candidate in [m.group(1) for m in _FENCE.finditer(text)] + [text]:
        found = _first_object(candidate)
        if found is not None:
            return found
    raise LLMOutputError(f"no JSON object in LLM output: {text[:200]!r}")


def _first_object(text: str) -> dict[str, JsonValue] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, index)
            return _OBJECT.validate_python(value)
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def _reasoning(message: Any) -> str | None:
    # Non-standard field; servers name it differently.
    for field in ("reasoning_content", "reasoning"):
        value = getattr(message, field, None)
        if isinstance(value, str) and value:
            return value
    return None
