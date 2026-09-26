"""Tests for the RQ3 runner (experiments/run_testgen_strategies.py)."""

import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from data.loaders.runbugrun import RunBugRunEntry
from experiments.run_testgen_strategies import (
    ArmOutcome,
    StrategyOutcome,
    done_entries,
    evaluate_entry,
    summarize_strategies,
    tier2_entries,
)
from tests.conftest import FakeSandbox
from toolvalidator.config import Settings
from toolvalidator.contracts import CapabilityRequest, ExecResult, IOExample
from toolvalidator.llm.scads_client import LLMResult

RAW = Path(__file__).resolve().parents[2] / "data" / "runbugrun_py" / "raw"


def _entry(buggy: str = "print(2)") -> RunBugRunEntry:
    return RunBugRunEntry(
        entry_id=7,
        split="valid",
        problem_id="p1",
        request=CapabilityRequest(name="p1", capability="p1", description="Print 1."),
        buggy_code=buggy,
        fixed_code="print(1)",
        tests=[IOExample(input="", output="1")],
        examples=[IOExample(input="", output="1")],
        bug_labels=["literal.number"],
    )


class _Client:
    """Answers each prompt by what it asks for; records (role, prompt id) per call."""

    def __init__(self, broken_compare: bool = False) -> None:
        self.calls: list[str] = []
        self.broken_compare = broken_compare

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        if "black-box tests" in system:
            kind, reply = "generate", {"tests": [{"input": "", "output": "1"}] * 2}
        elif "numbered list" in system:
            kind = "judge_batch"
            reply = {"verdicts": [{"index": 0, "valid": True}, {"index": 1, "valid": False}]}
        elif "explain" in system:
            kind, reply = "explain", {"explanation": "Prints a number."}
        else:
            kind = "compare"
            reply = {"requirements": [{"requirement": "print 1", "status": "met"}]}
        self.calls.append(kind)
        content = "no json" if kind == "compare" and self.broken_compare else json.dumps(reply)
        return LLMResult(
            model="m",
            content=content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.0,
        )


def _sandbox_factory(pass_all: bool) -> tuple[FakeSandbox, object]:
    result = {"index": 0, "passed": pass_all, "timed_out": False, "exit_code": 0}
    payload = json.dumps({"results": [result | {"actual": "2", "stderr": ""}]})
    box = FakeSandbox(ExecResult(stdout=payload, stderr="", exit_code=0, duration_s=0.1))
    return box, lambda: nullcontext(box)


def test_one_blind_suite_per_entry_shared_by_both_tools() -> None:
    client = _Client()
    box, factory = _sandbox_factory(True)
    rows = evaluate_entry(_entry(), client, factory, Settings())  # type: ignore[arg-type]
    assert [r.variant for r in rows] == ["buggy", "fixed"]
    # one generation + one batched judgement for the entry; S5b twice per tool
    assert client.calls.count("generate") == 1
    assert client.calls.count("judge_batch") == 1
    assert client.calls.count("explain") == 2 and client.calls.count("compare") == 2
    for row in rows:
        assert set(row.arms) == {"examples", "generated", "judged"}
        assert (row.suite_generated, row.suite_accepted) == (2, 1)
        assert row.arms["generated"].n_tests == 2 and row.arms["judged"].n_tests == 1
        assert row.signals is not None and row.signals.test_pass_rate is not None
        assert row.semantics_score == 1.0
    first_prompt = box.calls[0]
    assert first_prompt  # tests really went through the (fake) sandbox


def test_hard_gate_rejection_skips_arms_and_semantics() -> None:
    client = _Client()
    _, factory = _sandbox_factory(True)
    buggy, fixed = evaluate_entry(_entry(buggy="print(2"), client, factory, Settings())  # type: ignore[arg-type]
    assert buggy.gate_category == "syntax_error"
    assert buggy.arms == {} and buggy.signals is None
    assert fixed.gate_category is None and fixed.arms
    assert client.calls.count("explain") == 1  # only the fixed tool reached S5b


def _row(correct: bool, judged: ArmOutcome, violation: bool | None = False) -> StrategyOutcome:
    ok = ArmOutcome(n_tests=1, pass_rate=1.0, category=None)
    return StrategyOutcome(
        entry_id=1,
        problem_id="p",
        split="valid",
        variant="fixed" if correct else "buggy",
        is_correct=correct,
        bug_labels=[],
        gate_category=None,
        suite_generated=1,
        suite_accepted=1,
        arms={"examples": ok, "generated": ok, "judged": judged},
        semantics_score=None,
        semantic_violation=violation,
        signals=None,
    )


def test_summary_counts_detection_false_rejection_and_semantic_extras() -> None:
    fail = ArmOutcome(n_tests=4, pass_rate=0.5, category="wrong_output")
    ok = ArmOutcome(n_tests=4, pass_rate=1.0, category=None)
    empty = ArmOutcome(n_tests=0, pass_rate=None, category="no_tests")
    rows = [
        _row(False, fail),
        _row(False, ok, violation=True),  # execution missed it, rubber-duck did not
        _row(False, empty),
        _row(True, ok),
        _row(True, fail),
    ]
    summary = summarize_strategies(rows)
    judged = summary["arms"]["judged"]  # type: ignore[index, call-overload]
    assert judged["detection_rate"] == pytest.approx(1 / 3)
    assert judged["false_rejection_rate"] == pytest.approx(1 / 2)
    assert judged["buggy_without_tests"] == 1
    semantic = summary["semantic"]  # type: ignore[index]
    assert semantic["extra_catches_over_judged"] == 1  # type: ignore[index, call-overload]
    assert semantic["errors"] == 0  # type: ignore[index, call-overload]


def test_done_entries_needs_both_variants(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    fail = ArmOutcome(n_tests=1, pass_rate=0.0, category="wrong_output")
    both = [_row(False, fail), _row(True, fail)]
    lone = _row(False, fail).model_copy(update={"entry_id": 2})
    path.write_text("".join(r.model_dump_json() + "\n" for r in [*both, lone]), encoding="utf-8")
    assert done_entries(path) == {1}
    assert done_entries(tmp_path / "missing.jsonl") == set()


def test_dev_and_eval_sets_are_disjoint_and_sized() -> None:
    if not (RAW / "python_valid0.jsonl.gz").exists():
        pytest.skip("RunBugRun raw files not downloaded")
    dev = tier2_entries(RAW, "dev", seed=20260917)
    evaluation = tier2_entries(RAW, "eval", seed=20260917)
    assert (len(dev), len(evaluation)) == (50, 300)
    assert not {e.entry_id for e in dev} & {e.entry_id for e in evaluation}


def test_an_unusable_rubberduck_reply_keeps_the_entry_with_semantics_missing() -> None:
    _, factory = _sandbox_factory(True)
    rows = evaluate_entry(_entry(), _Client(broken_compare=True), factory, Settings())  # type: ignore[arg-type]
    for row in rows:
        assert set(row.arms) == {"examples", "generated", "judged"}  # execution arms kept
        assert row.semantics_score is None and row.semantic_violation is None
        assert row.semantic_error is not None and "LLMOutputError" in row.semantic_error
        assert row.signals is not None and row.signals.semantics_score is None
