"""Tests for the mutation-arms runner (experiments/run_mutation_arms.py)."""

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast

import pytest

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import Variant
from experiments.run_mutation_arms import (
    MutationRow,
    completed_entries,
    done_entries,
    evaluate_entry,
    evaluate_tool,
    rebuild_suite,
    summarize,
    union_suite,
)
from experiments.run_testgen_strategies import StrategyOutcome
from toolvalidator.config import Settings
from toolvalidator.contracts import CapabilityRequest, ExecResult, IOExample
from toolvalidator.llm.replay import ReplayMissError
from toolvalidator.llm.scads_client import LLMResult, ScadsClient
from toolvalidator.llm.trace import TracingClient, merge_traces, trace_context, writer_for_run
from toolvalidator.stages import s3_testgen

REQUEST = CapabilityRequest(name="p1", capability="p1", description="Read n, print n+1.")
FIXED = "print(int(input()) + 1)"
BUGGY = "print(int(input()) + 2)"


def _entry(entry_id: int = 7) -> RunBugRunEntry:
    return RunBugRunEntry(
        entry_id=entry_id,
        split="valid",
        problem_id="p1",
        request=REQUEST,
        buggy_code=BUGGY,
        fixed_code=FIXED,
        tests=[IOExample(input="9", output="10")],
        examples=[IOExample(input="1", output="2")],
        bug_labels=["literal.number"],
    )


class _Client:
    """Scripted LLM: a generated suite, a batch verdict (last test rejected), Arm B mutants."""

    def __init__(self, tests: list[tuple[str, str]], mutants: list[str] | None = None) -> None:
        self.tests = tests
        self.mutants = mutants
        self.calls: list[str] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        if "black-box tests" in system:
            reply: Any = {"tests": [{"input": i, "output": o} for i, o in self.tests]}
        elif "numbered list" in system:
            last = len(self.tests) - 1
            reply = {"verdicts": [{"index": i, "valid": i != last} for i in range(len(self.tests))]}
        elif "buggy variants" in system:
            if self.mutants is None:
                return self._result("no json here")
            reply = {"mutants": [{"description": "m", "code": c} for c in self.mutants]}
        else:
            raise AssertionError(f"unexpected prompt: {system[:60]}")
        self.calls.append(system[:20])
        return self._result(json.dumps(reply))

    @staticmethod
    def _result(content: str) -> LLMResult:
        return LLMResult(
            model="m",
            content=content,
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_s=0.0,
        )


def _record(tmp_path: Path, suites: dict[int, list[tuple[str, str]]]) -> Path:
    """Write a trace the way RQ3 did: one blind suite per entry, tagged with its id."""
    writer = writer_for_run(tmp_path, "rq3-eval")
    for entry_id, tests in suites.items():
        client = cast(ScadsClient, TracingClient(cast(ScadsClient, _Client(tests)), writer))
        with trace_context(run_id="rq3-eval", tool_id=str(entry_id)):
            s3_testgen.build_suite(client, REQUEST, code=None, n=3, batch_judge=True)
    return tmp_path / "rq3-eval"


# --- rebuilding RQ3's suites offline ------------------------------------------------


def test_each_entry_replays_its_own_suite_even_when_prompts_are_identical(
    tmp_path: Path,
) -> None:
    run_dir = _record(tmp_path, {7: [("1", "2"), ("5", "6")], 8: [("3", "4"), ("0", "1")]})
    calls = merge_traces(run_dir)
    first = rebuild_suite(calls, _entry(7), n_tests=3)
    second = rebuild_suite(calls, _entry(8), n_tests=3)
    assert [t.input for t, _ in first.judged] == ["1", "5"]
    assert [t.input for t, _ in second.judged] == ["3", "0"]
    assert [t.input for t in first.accepted] == ["1"]


def test_an_entry_missing_from_the_trace_raises(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, {7: [("1", "2")]}))
    with pytest.raises(ReplayMissError):
        rebuild_suite(calls, _entry(9), n_tests=3)


def test_union_suite_is_samples_then_generated_with_judged_a_subset(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, {7: [("1", "2"), ("5", "6"), ("7", "9")]}))
    suite = rebuild_suite(calls, _entry(7), n_tests=3)
    tests, indices = union_suite(_entry(7), suite)
    assert [t.input for t in tests] == ["1", "1", "5", "7"]
    assert indices == {"examples": [0], "generated": [1, 2, 3], "judged": [1, 2]}


# --- one tool -----------------------------------------------------------------------


class _Box:
    """Fake sandbox: per-test pass/fail computed by a rule on (code, input). Runs nothing."""

    def __init__(self) -> None:
        self.codes: list[str] = []

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        payload = json.loads(stdin)
        code = payload["code"]
        self.codes.append(code)
        results = [
            {"index": i, "passed": _passes(code, t["input"], t["output"]), "timed_out": False,
             "exit_code": 0}
            for i, t in enumerate(payload["tests"])
        ]  # fmt: skip
        return ExecResult(stdout=json.dumps({"results": results}), stderr="", exit_code=0,
                          duration_s=0.1)  # fmt: skip


def _passes(code: str, given: str, expected: str) -> bool:
    """Only FIXED is correct; every other program is wrong except on input 7 (which says 9)."""
    if code == FIXED:
        return int(given) + 1 == int(expected)
    return given == "7"


def _rq3_row(variant: str, failed: dict[str, bool]) -> StrategyOutcome:
    arms = {
        arm: {"n_tests": 1, "pass_rate": 0.0 if bad else 1.0, "category": "wrong_output" if bad
              else None, "failed_tests": []}
        for arm, bad in failed.items()
    }  # fmt: skip
    return StrategyOutcome.model_validate(
        {"entry_id": 7, "problem_id": "p1", "split": "valid", "variant": variant,
         "is_correct": variant == "fixed", "bug_labels": [], "gate_category": None,
         "suite_generated": 3, "suite_accepted": 2, "arms": arms, "semantics_score": None,
         "semantic_violation": None, "signals": None}
    )  # fmt: skip


def _suite(tmp_path: Path) -> s3_testgen.JudgedSuite:
    calls = merge_traces(_record(tmp_path, {7: [("1", "2"), ("5", "6"), ("7", "9")]}))
    return rebuild_suite(calls, _entry(7), n_tests=3)


def test_fixed_tool_gets_scores_per_arm_and_per_suite(tmp_path: Path) -> None:
    box = _Box()
    client = cast(ScadsClient, _Client([], mutants=["print(int(input()) * 1)"]))
    rq3 = _rq3_row("fixed", {"examples": False, "generated": True, "judged": False})
    row = evaluate_tool(_entry(), "fixed", _suite(tmp_path), rq3, client, box, Settings())
    assert row.tool_passes == [True, True, True, False]  # the generated "7 -> 9" is wrong
    assert row.rq3_mismatches == []
    a, b = row.arms["A"], row.arms["B"]
    assert a.error is None and a.mutants  # FIXED has a "+" and a "1" to mutate
    assert [m.code for m in b.mutants] == ["print(int(input()) * 1)"]
    # every mutant fails inputs 1 and 5, which the tool passes: all are killed by every suite
    for arm in (a, b):
        for name in ("examples", "generated", "judged"):
            assert arm.scores[name].score == 1.0
    assert box.codes.count(FIXED) == 2  # once per arm, so each arm's sandbox time is its own
    assert row.tool_stable
    assert a.sandbox_seconds > 0 and b.sandbox_seconds > 0


def test_buggy_tool_can_only_be_killed_by_tests_it_passes(tmp_path: Path) -> None:
    client = cast(ScadsClient, _Client([], mutants=["print(0)"]))
    rq3 = _rq3_row("buggy", {"examples": True, "generated": True, "judged": True})
    row = evaluate_tool(_entry(), "buggy", _suite(tmp_path), rq3, client, _Box(), Settings())
    assert row.tool_passes == [False, False, False, True]
    judged = row.arms["B"].scores["judged"]
    assert (judged.usable_tests, judged.killed, judged.score) == (0, 0, 0.0)
    assert row.arms["B"].scores["generated"].usable_tests == 1


def test_a_disagreement_with_rq3_is_recorded_not_hidden(tmp_path: Path) -> None:
    client = cast(ScadsClient, _Client([], mutants=[]))
    rq3 = _rq3_row("fixed", {"examples": True, "generated": True, "judged": False})
    row = evaluate_tool(_entry(), "fixed", _suite(tmp_path), rq3, client, _Box(), Settings())
    assert row.rq3_mismatches == ["examples"]


def test_an_unusable_arm_b_reply_keeps_arm_a(tmp_path: Path) -> None:
    client = cast(ScadsClient, _Client([], mutants=None))
    rq3 = _rq3_row("fixed", {"examples": False, "generated": True, "judged": False})
    row = evaluate_tool(_entry(), "fixed", _suite(tmp_path), rq3, client, _Box(), Settings())
    assert row.arms["B"].error is not None
    assert row.arms["B"].scores["judged"].score is None
    assert row.arms["A"].scores["judged"].score is not None


def _box_factory() -> Any:
    return lambda: nullcontext(_Box())


def test_evaluate_entry_rebuilds_once_and_runs_both_variants(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, {7: [("1", "2"), ("5", "6"), ("7", "9")]}))
    rq3 = {
        "fixed": _rq3_row("fixed", {"examples": False, "generated": True, "judged": False}),
        "buggy": _rq3_row("buggy", {"examples": True, "generated": True, "judged": True}),
    }
    client = cast(ScadsClient, _Client([], mutants=["print(0)"]))
    rows = evaluate_entry(_entry(), rq3, calls, client, _box_factory(), Settings(), n_tests=3)
    assert [r.variant for r in rows] == ["buggy", "fixed"]
    assert all(r.rq3_mismatches == [] for r in rows)


def test_a_rebuilt_suite_that_differs_from_rq3_s_counts_raises(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, {7: [("1", "2"), ("5", "6"), ("7", "9")]}))
    wrong = _rq3_row("fixed", {"examples": False, "generated": True, "judged": False})
    rq3 = {"fixed": wrong.model_copy(update={"suite_accepted": 3}), "buggy": wrong}
    client = cast(ScadsClient, _Client([], mutants=[]))
    with pytest.raises(ValueError, match="does not match RQ3"):
        evaluate_entry(_entry(), rq3, calls, client, _box_factory(), Settings(), n_tests=3)


# --- selection, resume, summary -------------------------------------------------------


def test_completed_entries_need_both_variants_past_the_gates() -> None:
    fixed = _rq3_row("fixed", {"examples": False, "generated": False, "judged": False})
    buggy = _rq3_row("buggy", {"examples": True, "generated": True, "judged": True})
    assert completed_entries([fixed, buggy]) == {7}
    assert completed_entries([fixed]) == set()
    gated = buggy.model_copy(update={"gate_category": "bandit"})
    assert completed_entries([fixed, gated]) == set()


def test_done_entries_and_summary(tmp_path: Path) -> None:
    client = cast(ScadsClient, _Client([], mutants=["print(0)"]))
    rows: list[MutationRow] = []
    variants: list[tuple[Variant, dict[str, bool]]] = [
        ("fixed", {"examples": False, "generated": True, "judged": False}),  # "7 -> 9" is wrong
        ("buggy", {"examples": True, "generated": True, "judged": True}),
    ]
    for variant, failed in variants:
        rq3 = _rq3_row(variant, failed)
        suite = _suite(tmp_path / variant)
        rows.append(evaluate_tool(_entry(), variant, suite, rq3, client, _Box(), Settings()))
    path = tmp_path / "rows.jsonl"
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    assert done_entries(path) == {7}
    summary = summarize(rows)
    assert summary["n_tools"] == 2
    assert summary["rq3_mismatched_tools"] == 0
    arms = summary["arms"]
    assert isinstance(arms, dict)
    fixed_b = arms["B"]["fixed"]["judged"]  # type: ignore[index]
    assert fixed_b == {"mean_score": 1.0, "n_scored": 1, "n_missing": 0}
