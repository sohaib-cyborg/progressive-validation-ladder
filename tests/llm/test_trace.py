"""Tests for LLM call tracing (toolvalidator/llm/trace.py)."""

import json
from pathlib import Path
from typing import Any

import pytest

from toolvalidator.llm.scads_client import LLMError, LLMResult
from toolvalidator.llm.trace import (
    LLMCall,
    TraceWriter,
    TracingClient,
    merge_traces,
    read_trace,
    trace_context,
    writer_for_run,
)


class _FakeClient:
    """Minimal stand-in for ScadsClient (same structural complete())."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def model_for(self, role: str) -> str:
        return f"{role}-model"

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.calls.append((role, system, user))
        if self.error is not None:
            raise self.error
        return LLMResult(
            model="served-model",
            content="hello",
            reasoning="thinking",
            prompt_tokens=11,
            completion_tokens=7,
            latency_s=0.25,
        )


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_successful_call_writes_one_row(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    client = TracingClient(_FakeClient(), TraceWriter(path))
    result = client.complete("generator", system="sys", user="usr")

    assert result.content == "hello"
    (row,) = _rows(path)
    assert row["role"] == "generator"
    assert row["model_requested"] == "generator-model"
    assert row["model_returned"] == "served-model"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (11, 7)
    assert row["latency_s"] == 0.25
    assert row["ok"] is True
    assert row["error"] is None
    assert row["system"] == "sys" and row["user"] == "usr" and row["content"] == "hello"


def test_hashes_are_stable_and_independent_of_text_storage(tmp_path: Path) -> None:
    full = tmp_path / "full.jsonl"
    hashed = tmp_path / "hashed.jsonl"
    TracingClient(_FakeClient(), TraceWriter(full)).complete("judge", system="s", user="u")
    TracingClient(_FakeClient(), TraceWriter(hashed, include_text=False)).complete(
        "judge", system="s", user="u"
    )
    (a,), (b,) = _rows(full), _rows(hashed)
    assert a["user_sha256"] == b["user_sha256"]
    assert len(a["user_sha256"]) == 64
    assert b["system"] is None and b["user"] is None and b["content"] is None


def test_context_fields_are_attached(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    client = TracingClient(_FakeClient(), TraceWriter(path))
    with trace_context(run_id="r1", tool_id="t1", variant="buggy", agent="testgen"):
        with trace_context(
            node="generate",
            skill="propose_tests",
            prompt_id="generate_tests",
            prompt_version="v1",
            attempt=2,
        ):
            client.complete("generator", system="s", user="u")
        client.complete("generator", system="s", user="u")

    inner, outer = _rows(path)
    assert inner["agent"] == "testgen" and inner["node"] == "generate"
    assert inner["skill"] == "propose_tests"
    assert (inner["prompt_id"], inner["prompt_version"]) == ("generate_tests", "v1")
    assert inner["attempt"] == 2
    assert (inner["run_id"], inner["tool_id"], inner["variant"]) == ("r1", "t1", "buggy")
    # the nested context is restored, the outer one survives
    assert outer["agent"] == "testgen"
    assert outer["node"] is None and outer["attempt"] == 0


def test_failed_call_is_recorded_then_reraised(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    client = TracingClient(_FakeClient(error=LLMError("boom")), TraceWriter(path))
    with pytest.raises(LLMError, match="boom"):
        client.complete("generator", system="s", user="u")

    (row,) = _rows(path)
    assert row["ok"] is False
    assert "boom" in row["error"]
    assert row["model_returned"] is None
    assert row["latency_s"] >= 0


def test_rows_append_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    client = TracingClient(_FakeClient(), TraceWriter(path))
    for _ in range(3):
        client.complete("judge", system="s", user="u")
    calls = read_trace(path)
    assert len(calls) == 3
    assert all(isinstance(call, LLMCall) for call in calls)
    assert calls[0].role == "judge"


def test_writer_for_run_is_per_process(tmp_path: Path) -> None:
    writer = writer_for_run(tmp_path, run_id="run7")
    TracingClient(_FakeClient(), writer).complete("judge", system="s", user="u")
    files = sorted((tmp_path / "run7").glob("llm_calls.*.jsonl"))
    assert len(files) == 1
    assert str(files[0].name).endswith(".jsonl")
    assert read_trace(files[0])[0].run_id == "run7"


def test_merge_traces_reads_every_process_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run7"
    for pid in ("1", "2"):
        writer = TraceWriter(run_dir / f"llm_calls.{pid}.jsonl")
        TracingClient(_FakeClient(), writer).complete("judge", system="s", user=pid)
    assert len(merge_traces(run_dir)) == 2


def test_tracing_client_works_wherever_scads_client_does() -> None:
    # The skills and stages only need complete(role, *, system, user).
    from toolvalidator.contracts import CapabilityRequest
    from toolvalidator.testgen.judge import judge_test
    from toolvalidator.testgen.schemas import GeneratedTest

    class _JudgeClient(_FakeClient):
        def complete(self, role: str, *, system: str, user: str) -> LLMResult:
            super().complete(role, system=system, user=user)
            return LLMResult(
                model="m",
                content='{"valid": true}',
                reasoning=None,
                prompt_tokens=1,
                completion_tokens=1,
                latency_s=0.0,
            )

    client: Any = TracingClient(_JudgeClient(), TraceWriter(Path("unused"), enabled=False))
    request = CapabilityRequest(name="t", capability="t", description="d")
    assert judge_test(client, request, GeneratedTest(input="1", output="2")).valid is True
