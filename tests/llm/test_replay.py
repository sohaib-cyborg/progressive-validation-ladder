"""Tests for offline replay of recorded LLM calls (toolvalidator/llm/replay.py)."""

import contextlib
from pathlib import Path
from typing import Any

import pytest

from toolvalidator.contracts import CapabilityRequest
from toolvalidator.llm.replay import ReplayClient, ReplayMissError
from toolvalidator.llm.scads_client import LLMError, LLMResult
from toolvalidator.llm.trace import TraceWriter, TracingClient
from toolvalidator.testgen.judge import judge_test
from toolvalidator.testgen.schemas import GeneratedTest


class _ScriptedClient:
    """Returns the given contents in order; raises if asked for more."""

    def __init__(self, *contents: str | Exception) -> None:
        self.contents = list(contents)
        self.calls = 0

    def model_for(self, role: str) -> str:
        return f"{role}-model"

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls += 1
        item = self.contents.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(
            model="served",
            content=item,
            reasoning=None,
            prompt_tokens=3,
            completion_tokens=4,
            latency_s=0.5,
        )


def _record(path: Path, *contents: str | Exception) -> _ScriptedClient:
    inner = _ScriptedClient(*contents)
    client = TracingClient(inner, TraceWriter(path, run_id="r1"))
    for _ in range(len(contents)):
        with contextlib.suppress(LLMError):
            client.complete("judge", system="sys", user="usr")
    return inner


def test_replay_returns_recorded_content_without_a_network_client(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _record(path, "first", "second")

    replay = ReplayClient.from_file(path)
    assert replay.complete("judge", system="sys", user="usr").content == "first"
    assert replay.complete("judge", system="sys", user="usr").content == "second"


def test_unknown_prompt_raises_instead_of_calling_out(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _record(path, "only")
    replay = ReplayClient.from_file(path)
    with pytest.raises(ReplayMissError, match="not in the trace"):
        replay.complete("judge", system="different", user="prompt")


def test_running_out_of_recorded_calls_raises(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _record(path, "only")
    replay = ReplayClient.from_file(path)
    replay.complete("judge", system="sys", user="usr")
    with pytest.raises(ReplayMissError):
        replay.complete("judge", system="sys", user="usr")


def test_recorded_failures_are_replayed_as_failures(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _record(path, LLMError("scads exploded"))
    replay = ReplayClient.from_file(path)
    with pytest.raises(LLMError, match="scads exploded"):
        replay.complete("judge", system="sys", user="usr")


def test_trace_without_text_cannot_be_replayed(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    client = TracingClient(_ScriptedClient("hi"), TraceWriter(path, include_text=False))
    client.complete("judge", system="sys", user="usr")
    with pytest.raises(ReplayMissError, match="without prompt text"):
        ReplayClient.from_file(path)


def test_from_run_merges_every_process_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run1"
    _record(run_dir / "llm_calls.1.jsonl", "a")
    _record(run_dir / "llm_calls.2.jsonl", "b")
    replay = ReplayClient.from_run(run_dir)
    assert replay.call_count == 2


def test_replay_drives_real_code_and_reproduces_the_result(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    request = CapabilityRequest(name="t", description="Print the sum.")
    test = GeneratedTest(input="2 3", output="5")

    live: Any = TracingClient(
        _ScriptedClient('{"valid": true, "reason": "2+3=5"}'), TraceWriter(path, run_id="r1")
    )
    recorded = judge_test(live, request, test)

    replayed = judge_test(ReplayClient.from_file(path), request, test)
    assert replayed == recorded
    assert replayed.valid is True


def test_model_for_reports_the_recorded_model(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _record(path, "x")
    assert ReplayClient.from_file(path).model_for("judge") == "judge-model"
