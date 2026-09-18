"""Trace every LLM call to JSONL: the basis of the cost table and of replay.

``TracingClient`` wraps any object with ``ScadsClient``'s ``complete`` shape, so every
existing caller is traced without a signature change. Context (which agent, node, skill,
prompt version, attempt) travels in a ContextVar set by ``trace_context``.

One file per process (``llm_calls.<pid>.jsonl``): processes never share a handle, so
the experiment's process pool needs no locks. Full prompt text can be switched off;
hashes are always stored, so call counting and deduplication survive either way.
"""

import contextvars
import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

from toolvalidator.llm.scads_client import LLMResult, Role


class TraceContext(BaseModel):
    """Where a call came from. Every field is optional so tracing never blocks a call."""

    model_config = ConfigDict(frozen=True)

    run_id: str | None = None
    tool_id: str | None = None
    variant: str | None = None
    agent: str | None = None
    node: str | None = None
    skill: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    attempt: int = 0


class LLMCall(TraceContext):
    """One row of the trace."""

    ts: float
    role: str
    model_requested: str | None
    model_returned: str | None
    system_sha256: str
    user_sha256: str
    system: str | None
    user: str | None
    content: str | None
    reasoning: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float
    ok: bool
    error: str | None


_CONTEXT: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "llm_trace_context", default=None
)


@contextmanager
def trace_context(**fields: object) -> Iterator[None]:
    """Attach fields to every call made inside the block. Nested blocks merge."""
    token = _CONTEXT.set(current_context().model_copy(update=fields))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_context() -> TraceContext:
    return _CONTEXT.get() or TraceContext()


class TraceWriter:
    """Appends rows to one JSONL file. Opened lazily, line-buffered."""

    def __init__(
        self,
        path: Path,
        *,
        include_text: bool = True,
        enabled: bool = True,
        run_id: str | None = None,
    ) -> None:
        self.path = path
        self.include_text = include_text
        self.enabled = enabled
        self.run_id = run_id
        self._handle: Any = None

    def write(self, call: LLMCall) -> None:
        if not self.enabled:
            return
        if call.run_id is None and self.run_id is not None:
            # The writer owns the run id, so rows stay attributable even if a caller
            # forgets to set the trace context.
            call = call.model_copy(update={"run_id": self.run_id})
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8", buffering=1)
        self._handle.write(call.model_dump_json() + "\n")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def writer_for_run(results_dir: Path, run_id: str, *, include_text: bool = True) -> TraceWriter:
    """``<results_dir>/<run_id>/llm_calls.<pid>.jsonl`` — one file per worker process."""
    path = results_dir / run_id / f"llm_calls.{os.getpid()}.jsonl"
    return TraceWriter(path, include_text=include_text, run_id=run_id)


class TracingClient:
    """Wraps an LLM client and records every call, successful or not."""

    # Any: the wrapped client is structural (ScadsClient, or a fake in tests).
    def __init__(self, inner: Any, writer: TraceWriter) -> None:
        self._inner = inner
        self._writer = writer

    def model_for(self, role: Role) -> str | None:
        model_for = getattr(self._inner, "model_for", None)
        if model_for is None:
            return None
        requested: str | None = model_for(role)
        return requested

    def complete(self, role: Role, *, system: str, user: str) -> LLMResult:
        started = time.perf_counter()
        try:
            result: LLMResult = self._inner.complete(role, system=system, user=user)
        except Exception as exc:
            self._record(role, system, user, None, time.perf_counter() - started, exc)
            raise
        self._record(role, system, user, result, time.perf_counter() - started, None)
        return result

    def _record(
        self,
        role: Role,
        system: str,
        user: str,
        result: LLMResult | None,
        latency_s: float,
        error: Exception | None,
    ) -> None:
        keep_text = self._writer.include_text
        call = LLMCall(
            **current_context().model_dump(),
            ts=time.time(),
            role=role,
            model_requested=self.model_for(role),
            model_returned=result.model if result is not None else None,
            system_sha256=_sha256(system),
            user_sha256=_sha256(user),
            system=system if keep_text else None,
            user=user if keep_text else None,
            content=result.content if (result is not None and keep_text) else None,
            reasoning=result.reasoning if (result is not None and keep_text) else None,
            prompt_tokens=result.prompt_tokens if result is not None else None,
            completion_tokens=result.completion_tokens if result is not None else None,
            latency_s=latency_s if result is None else result.latency_s,
            ok=error is None,
            error=f"{type(error).__name__}: {error}" if error is not None else None,
        )
        self._writer.write(call)


def read_trace(path: Path) -> list[LLMCall]:
    with path.open("r", encoding="utf-8") as handle:
        return [LLMCall.model_validate_json(line) for line in handle if line.strip()]


def merge_traces(run_dir: Path) -> list[LLMCall]:
    """Every process's rows for one run, ordered by timestamp."""
    calls = [
        call for path in sorted(run_dir.glob("llm_calls.*.jsonl")) for call in read_trace(path)
    ]
    return sorted(calls, key=lambda call: call.ts)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_key(model: str | None, system: str, user: str) -> str:
    """Stable identity of one request, used by the replay client."""
    return _sha256(json.dumps([model, system, user], ensure_ascii=False))
