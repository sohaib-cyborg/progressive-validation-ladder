"""Tests for shared experiment plumbing (experiments/common.py)."""

import json
from pathlib import Path

import pytest

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import (
    ToolOutcome,
    evaluate_tool,
    sample_entries,
    summarize,
    worker_count,
    write_jsonl,
)
from tests.conftest import FakeSandbox
from toolvalidator.config import Settings
from toolvalidator.contracts import CapabilityRequest, ExecResult, IOExample

RAW = Path(__file__).resolve().parents[2] / "data" / "runbugrun_py" / "raw"


def _entry(entry_id: int, problem_id: str = "p1", buggy: str = "print(2)") -> RunBugRunEntry:
    return RunBugRunEntry(
        entry_id=entry_id,
        split="valid",
        problem_id=problem_id,
        request=CapabilityRequest(name=problem_id, capability=problem_id, description="Print 1."),
        buggy_code=buggy,
        fixed_code="print(1)",
        tests=[IOExample(input="", output="1")],
        examples=[],
        bug_labels=["literal.number.integer.change"],
    )


# --- worker_count ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("cpus", "docker_mem_gb", "expected"),
    [(12, 1.9, 3), (12, 8.0, 10), (4, 64.0, 2), (2, 64.0, 1), (12, 0.4, 1)],
)
def test_worker_count_respects_cpus_and_docker_memory(
    cpus: int, docker_mem_gb: float, expected: int
) -> None:
    assert (
        worker_count(cpus, int(docker_mem_gb * 1024**3), mem_limit_bytes=512 * 1024**2) == expected
    )


# --- sampling -------------------------------------------------------------------


def test_sampling_is_deterministic_and_caps_entries_per_problem() -> None:
    if not (RAW / "python_valid0.jsonl.gz").exists():
        pytest.skip("RunBugRun raw files not downloaded")
    first = sample_entries(RAW, splits=("valid",), n=40, seed=7, max_per_problem=2)
    again = sample_entries(RAW, splits=("valid",), n=40, seed=7, max_per_problem=2)
    other = sample_entries(RAW, splits=("valid",), n=40, seed=8, max_per_problem=2)
    assert [e.entry_id for e in first] == [e.entry_id for e in again]
    assert [e.entry_id for e in first] != [e.entry_id for e in other]
    assert len(first) == 40
    counts: dict[str, int] = {}
    for entry in first:
        counts[entry.problem_id] = counts.get(entry.problem_id, 0) + 1
    assert max(counts.values()) <= 2


# --- evaluate_tool ---------------------------------------------------------------


def _sandbox(pass_all: bool) -> FakeSandbox:
    results = [
        {
            "index": 0,
            "passed": pass_all,
            "timed_out": False,
            "exit_code": 0,
            "actual": "2",
            "stderr": "",
        }
    ]
    payload = json.dumps({"results": results})
    return FakeSandbox(ExecResult(stdout=payload, stderr="", exit_code=0, duration_s=0.1))


def test_evaluate_fixed_variant_passes_both_configs() -> None:
    outcome = evaluate_tool(_entry(1), "fixed", _sandbox(True), Settings())
    assert outcome.variant == "fixed"
    assert outcome.is_correct is True
    assert outcome.verdict_static == "ACCEPT"
    assert outcome.verdict_dynamic == "ACCEPT"
    assert outcome.pass_rate == 1.0
    assert outcome.n_tests == 1


def test_evaluate_buggy_variant_slips_past_static_but_execution_catches_it() -> None:
    outcome = evaluate_tool(_entry(2), "buggy", _sandbox(False), Settings())
    assert outcome.is_correct is False
    assert outcome.verdict_static == "ACCEPT"  # static analysis cannot see a wrong literal
    assert outcome.verdict_dynamic == "REJECT"
    assert outcome.category_dynamic == "wrong_output"
    assert outcome.pass_rate == 0.0
    assert outcome.bug_labels == ["literal.number.integer.change"]


def test_evaluate_syntax_error_is_rejected_by_static_without_executing() -> None:
    sandbox = _sandbox(True)
    outcome = evaluate_tool(_entry(3, buggy="print(2"), "buggy", sandbox, Settings())
    assert outcome.verdict_static == "REJECT"
    assert outcome.category_static == "syntax_error"
    assert outcome.verdict_dynamic == "REJECT"
    assert sandbox.calls == []  # short-circuited before S4


# --- output ---------------------------------------------------------------------


def test_write_jsonl_round_trip(tmp_path: Path) -> None:
    outcomes = [evaluate_tool(_entry(4), "fixed", _sandbox(True), Settings())]
    path = tmp_path / "out.jsonl"
    write_jsonl(path, outcomes)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["entry_id"] == 4
    assert ToolOutcome.model_validate(rows[0]) == outcomes[0]


# --- summarize -------------------------------------------------------------------


def _outcome(**kw: object) -> ToolOutcome:
    base: dict[str, object] = {
        "entry_id": 1,
        "problem_id": "p1",
        "split": "valid",
        "variant": "buggy",
        "is_correct": False,
        "n_tests": 3,
        "bug_labels": ["literal.number.integer.change"],
        "verdict_static": "ACCEPT",
        "category_static": None,
        "verdict_dynamic": "REJECT",
        "category_dynamic": "wrong_output",
        "pass_rate": 0.0,
    }
    return ToolOutcome.model_validate(base | kw)


def test_summarize_slip_and_false_rejection_rates() -> None:
    outcomes = [
        _outcome(entry_id=1),  # buggy: static accepts (slip), dynamic rejects
        _outcome(entry_id=2, verdict_static="REJECT", category_static="syntax_error"),
        _outcome(
            entry_id=3,
            variant="fixed",
            is_correct=True,
            verdict_dynamic="ACCEPT",
            category_dynamic=None,
            pass_rate=1.0,
        ),
        _outcome(  # a fixed tool wrongly rejected by dynamic checking
            entry_id=4,
            variant="fixed",
            is_correct=True,
            verdict_dynamic="REJECT",
            category_dynamic="wrong_output",
            pass_rate=0.5,
        ),
    ]
    summary = summarize(outcomes)
    assert summary["n_tools"] == 4
    assert summary["n_buggy"] == 2
    assert summary["n_fixed"] == 2
    assert summary["static"]["slip_rate"] == 0.5  # 1 of 2 buggy accepted
    assert summary["static"]["false_rejection_rate"] == 0.0
    assert summary["dynamic"]["slip_rate"] == 0.0
    assert summary["dynamic"]["false_rejection_rate"] == 0.5
    assert summary["unusable_fixed"] == 1  # a fixed tool failing its own tests


def test_summarize_recall_per_bug_category() -> None:
    outcomes = [
        _outcome(entry_id=1, bug_labels=["call.arguments.change"]),
        _outcome(
            entry_id=2,
            bug_labels=["call.arguments.change"],
            verdict_dynamic="ACCEPT",
            category_dynamic=None,
            pass_rate=1.0,
        ),
        _outcome(entry_id=3, bug_labels=["control_flow.branch.if.condition.change"]),
    ]
    summary = summarize(outcomes)
    assert summary["dynamic"]["recall_by_category"] == {"call": 0.5, "control_flow": 1.0}
    assert summary["static"]["recall_by_category"] == {"call": 0.0, "control_flow": 0.0}


def test_summarize_empty_is_explicit() -> None:
    with pytest.raises(ValueError, match="no outcomes"):
        summarize([])
