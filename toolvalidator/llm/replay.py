"""Replay recorded LLM calls offline, so a published number can be re-derived.

A hosted MoE endpoint is not bit-reproducible even at temperature 0, so we do not
claim it is. What is reproducible is the *artifact*: every call was recorded, and
``ReplayClient`` answers from that recording.

It never falls back to the network and never invents a reply: an unrecorded prompt
raises ``ReplayMissError`` (CLAUDE.md rule 7).
"""

from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Self

from toolvalidator.llm.scads_client import LLMError, LLMResult, Role
from toolvalidator.llm.trace import LLMCall, merge_traces, read_trace


class ReplayMissError(LLMError):
    """The requested prompt is not in the trace, so it cannot be answered offline."""


class ReplayClient:
    """Answers ``complete`` from a recorded trace. Same shape as ScadsClient."""

    def __init__(self, calls: Iterable[LLMCall]) -> None:
        self._queues: defaultdict[tuple[str, str, str], deque[LLMCall]] = defaultdict(deque)
        self._models: dict[str, str] = {}
        self.call_count = 0
        for call in calls:
            if call.system is None or call.user is None:
                raise ReplayMissError(
                    "this trace was written without prompt text; re-record with "
                    "trace_full_text enabled to replay it"
                )
            self._queues[(call.role, call.system, call.user)].append(call)
            if call.model_requested is not None:
                self._models.setdefault(call.role, call.model_requested)
            self.call_count += 1

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(read_trace(path))

    @classmethod
    def from_run(cls, run_dir: Path) -> Self:
        return cls(merge_traces(run_dir))

    def model_for(self, role: Role) -> str | None:
        return self._models.get(role)

    def complete(self, role: Role, *, system: str, user: str) -> LLMResult:
        queue = self._queues.get((role, system, user))
        if not queue:
            raise ReplayMissError(
                f"{role} prompt is not in the trace (or its recorded calls are exhausted): "
                f"{user[:120]!r}"
            )
        call = queue.popleft()
        if not call.ok:
            raise LLMError(call.error or "recorded failure")
        if call.content is None:  # pragma: no cover - guarded in __init__
            raise ReplayMissError("recorded call has no content")
        return LLMResult(
            model=call.model_returned or call.model_requested or "replay",
            content=call.content,
            reasoning=call.reasoning,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            latency_s=call.latency_s,
        )
