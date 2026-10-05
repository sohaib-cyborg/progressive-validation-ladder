"""Tests for the judge-independence runner (experiments/run_judge_independence.py).

Synthetic rows only; none of it is a result.
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from data.loaders.runbugrun import RunBugRunEntry
from experiments.run_judge_independence import (
    AsGenerator,
    JudgeRow,
    TestJudgement,
    evaluate_entry,
    summarize,
)
from experiments.run_mutation_arms import ArmResult, MutationRow
from toolvalidator.contracts import CapabilityRequest, IOExample
from toolvalidator.llm.scads_client import LLMResult, ScadsClient
from toolvalidator.llm.trace import TracingClient, merge_traces, trace_context, writer_for_run
from toolvalidator.mutation.kill import SuiteScore
from toolvalidator.stages import s3_testgen

REQUEST = CapabilityRequest(name="p1", capability="p1", description="Read n, print n+1.")


def _entry() -> RunBugRunEntry:
    return RunBugRunEntry(
        entry_id=7, split="valid", problem_id="p1", request=REQUEST,
        buggy_code="print(int(input()) + 2)", fixed_code="print(int(input()) + 1)",
        tests=[IOExample(input="1", output="2")], examples=[IOExample(input="1", output="2")],
        bug_labels=[],
    )  # fmt: skip


class _Client:
    """Scripted LLM: a 3-test suite; the batch judge rejects the tests at ``reject``."""

    def __init__(self, reject: set[int] | None, broken: bool = False) -> None:
        self.reject = reject or set()
        self.broken = broken
        self.roles: list[str] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.roles.append(role)
        if "black-box tests" in system:
            reply: Any = {"tests": [{"input": i, "output": o} for i, o in
                                    (("1", "2"), ("5", "6"), ("7", "9"))]}  # fmt: skip
        elif self.broken:
            return self._result("no json")
        else:
            reply = {"verdicts": [{"index": i, "valid": i not in self.reject} for i in range(3)]}
        return self._result(json.dumps(reply))

    @staticmethod
    def _result(content: str) -> LLMResult:
        return LLMResult(model="m", content=content, reasoning=None, prompt_tokens=1,
                         completion_tokens=1, latency_s=0.0)  # fmt: skip


def _record(tmp_path: Path, reject: set[int]) -> Path:
    writer = writer_for_run(tmp_path, "rq3-eval")
    client = cast(ScadsClient, TracingClient(cast(ScadsClient, _Client(reject)), writer))
    with trace_context(run_id="rq3-eval", tool_id="7"):
        s3_testgen.build_suite(client, REQUEST, code=None, n=3, batch_judge=True)
    return tmp_path / "rq3-eval"


def _mut(variant: str, tool: list[bool]) -> MutationRow:
    arm = ArmResult(mutants=[], candidates=0, dropped=0, mutant_passes=[],
                    scores={s: SuiteScore(killed=0, total=0, usable_tests=0, score=None)
                            for s in ("examples", "generated", "judged")},
                    sandbox_seconds=0.0)  # fmt: skip
    return MutationRow(
        entry_id=7, problem_id="p1", variant="fixed" if variant == "fixed" else "buggy",
        is_correct=variant == "fixed", bug_labels=[],
        suites={"examples": [0], "generated": [1, 2, 3], "judged": [1, 2]},
        tool_passes=tool, tool_stable=True, rq3_mismatches=[], arms={"A": arm, "B": arm},
        seconds=0.0,
    )  # fmt: skip


MUTATION = {
    "fixed": _mut("fixed", [True, True, True, False]),  # generated test 2 ("7 -> 9") is wrong
    "buggy": _mut("buggy", [False, False, False, True]),
}


def test_both_judges_are_recorded_against_the_fixed_tool_ground_truth(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, reject={2}))  # RQ3's judge rejected the wrong test
    same = _Client(reject={0, 2})
    row = evaluate_entry(
        _entry(), MUTATION, calls, cast(ScadsClient, AsGenerator(same)), True, n_tests=3
    )
    assert [t.different for t in row.tests] == [True, True, False]
    assert [t.same for t in row.tests] == [False, True, False]
    assert [t.fixed_passes for t in row.tests] == [True, True, False]
    assert [t.buggy_passes for t in row.tests] == [False, False, True]
    assert same.roles == ["generator"]  # the judge prompt went to the generator's model


def test_an_unusable_same_family_reply_is_missing(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, reject=set()))
    broken = cast(ScadsClient, AsGenerator(_Client(None, broken=True)))
    row = evaluate_entry(_entry(), MUTATION, calls, broken, True, n_tests=3)
    assert row.same_error is not None
    assert all(t.same is None for t in row.tests)


def test_suite_and_mutation_rows_must_line_up(tmp_path: Path) -> None:
    calls = merge_traces(_record(tmp_path, reject=set()))
    short = {"fixed": _mut("fixed", [True, True]), "buggy": MUTATION["buggy"]}
    short["fixed"] = short["fixed"].model_copy(
        update={"suites": {"examples": [], "generated": [0, 1], "judged": []}}
    )
    with pytest.raises(ValueError, match="generated tests"):
        evaluate_entry(
            _entry(), short, calls, cast(ScadsClient, AsGenerator(_Client(None))), True, n_tests=3
        )


def _t(fixed: bool, buggy: bool, different: bool, same: bool | None) -> TestJudgement:
    return TestJudgement(fixed_passes=fixed, buggy_passes=buggy, different=different, same=same)


def test_summary_scores_each_judge_on_the_same_tests() -> None:
    rows = [
        JudgeRow(entry_id=1, problem_id="p1", fixed_reliable=True, same_error=None, tests=[
            _t(True, False, True, True),    # valid test, both keep it
            _t(False, True, False, True),   # invalid; different-family rejects, same keeps
            _t(True, True, True, False),    # valid; same-family wrongly rejects
        ]),
        JudgeRow(entry_id=2, problem_id="p2", fixed_reliable=False, same_error=None,
                 tests=[_t(False, False, True, True)]),  # excluded: fixed tool unreliable
        JudgeRow(entry_id=3, problem_id="p3", fixed_reliable=True, same_error="x",
                 tests=[_t(True, False, True, None)]),  # excluded from the paired comparison
    ]  # fmt: skip
    summary = summarize(rows)
    assert summary["entries"] == {"total": 3, "excluded_unreliable_fixed": 1, "same_errors": 1,
                                  "paired": 1}  # fmt: skip
    judges = summary["judges"]
    assert isinstance(judges, dict)
    assert judges["different"]["invalid_caught"] == 1 and judges["different"]["valid_rejected"] == 0
    assert judges["same"]["invalid_caught"] == 0 and judges["same"]["valid_rejected"] == 1
    assert judges["different"]["recall"] == 1.0 and judges["same"]["recall"] == 0.0
    tools = summary["tools"]
    assert isinstance(tools, dict)
    # buggy tool: fails test 0 (kept by every judge) -> caught everywhere
    assert tools["no_judge"]["bugs_caught"] == 1 and tools["same"]["bugs_caught"] == 1
    # fixed tool: fails test 1 (invalid) -> rejected unless the judge removed that test
    assert tools["no_judge"]["correct_rejected"] == 1
    assert tools["different"]["correct_rejected"] == 0 and tools["same"]["correct_rejected"] == 1
