"""Tests for kill counting (toolvalidator/mutation/kill.py)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest

from toolvalidator.config import SandboxSettings
from toolvalidator.contracts import CapabilityRequest, ExecResult, IOExample
from toolvalidator.mutation import Mutant
from toolvalidator.mutation.kill import KillMatrix, run_matrix, suite_score
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import DockerSandbox
from toolvalidator.stages.s4_execute import HarnessError

REQUEST = CapabilityRequest(name="add_one", capability="add_one", description="Read n, print n+1.")
TOOL = "print(int(input()) + 1)"
TESTS = [IOExample(input="1", output="2"), IOExample(input="5", output="6")]


def _mutant(code: str) -> Mutant:
    return Mutant(operator="arithmetic", line=1, description="d", code=code)


class _ByCodeSandbox:
    """Answers each harness call from a table: program code -> per-test pass/fail.

    Executes nothing. ``None`` in the table means the whole call timed out.
    """

    def __init__(self, table: dict[str, list[bool] | None]) -> None:
        self.table = table
        self.codes: list[str] = []

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        code = json.loads(stdin)["code"]
        self.codes.append(code)
        passes = self.table[code]
        if passes is None:
            return ExecResult(stdout="", stderr="", exit_code=137, duration_s=1.0, timed_out=True)
        results = [
            {"index": i, "passed": p, "timed_out": False, "exit_code": 0}
            for i, p in enumerate(passes)
        ]
        return ExecResult(
            stdout=json.dumps({"results": results}), stderr="", exit_code=0, duration_s=0.1
        )


def test_matrix_runs_the_tool_and_each_mutant_once() -> None:
    sandbox = _ByCodeSandbox({TOOL: [True, True], "m1": [False, True], "m2": [True, True]})
    matrix = run_matrix(TOOL, [_mutant("m1"), _mutant("m2")], REQUEST, TESTS, sandbox)
    assert sandbox.codes == [TOOL, "m1", "m2"]
    assert matrix.tool == [True, True]
    assert matrix.mutants == [[False, True], [True, True]]


def test_a_test_kills_only_when_the_tool_passes_and_the_mutant_fails() -> None:
    matrix = KillMatrix(
        tool=[True, False, True],
        mutants=[[False, True, True], [True, False, True], [True, True, True]],
        seconds=0.0,
    )
    score = suite_score(matrix, [0, 1, 2])
    # mutant 0: killed by test 0; mutant 1: fails only test 1, which the tool fails too.
    assert (score.killed, score.total, score.usable_tests) == (1, 3, 2)
    assert score.score == pytest.approx(1 / 3)


def test_scores_use_only_the_suite_s_own_tests() -> None:
    matrix = KillMatrix(tool=[True, True], mutants=[[False, True], [True, False]], seconds=0.0)
    assert suite_score(matrix, [0]).killed == 1
    assert suite_score(matrix, [1]).killed == 1
    assert suite_score(matrix, [0, 1]).killed == 2


def test_a_mutant_that_hangs_the_whole_call_fails_every_test() -> None:
    sandbox = _ByCodeSandbox({TOOL: [True, True], "loop": None})
    matrix = run_matrix(TOOL, [_mutant("loop")], REQUEST, TESTS, sandbox)
    assert matrix.mutants == [[False, False]]
    assert suite_score(matrix, [0, 1]).killed == 1


def test_a_tool_that_hangs_passes_nothing_so_nothing_is_killed() -> None:
    sandbox = _ByCodeSandbox({TOOL: None, "m": [False, False]})
    matrix = run_matrix(TOOL, [_mutant("m")], REQUEST, TESTS, sandbox)
    score = suite_score(matrix, [0, 1])
    assert (score.killed, score.usable_tests, score.score) == (0, 0, 0.0)


def test_no_mutants_or_an_empty_suite_is_missing_not_zero() -> None:
    sandbox = _ByCodeSandbox({TOOL: [True, True]})
    matrix = run_matrix(TOOL, [], REQUEST, TESTS, sandbox)
    assert suite_score(matrix, [0, 1]).score is None
    full = KillMatrix(tool=[True], mutants=[[False]], seconds=0.0)
    assert suite_score(full, []).score is None


def test_no_tests_runs_nothing() -> None:
    sandbox = _ByCodeSandbox({})
    matrix = run_matrix(TOOL, [_mutant("m")], REQUEST, [], sandbox)
    assert sandbox.codes == []
    assert (matrix.tool, matrix.mutants) == ([], [[]])


def test_a_harness_reply_with_missing_tests_raises() -> None:
    sandbox = _ByCodeSandbox({TOOL: [True]})  # two tests sent, one outcome back
    with pytest.raises(HarnessError):
        run_matrix(TOOL, [], REQUEST, TESTS, sandbox)


# --- real Docker -----------------------------------------------------------------


@pytest.fixture(scope="module")
def sandbox(docker_client: Any, sandbox_image: str) -> Iterator[DockerSandbox]:
    settings = SandboxSettings()
    with provision(docker_client, settings) as container:
        yield DockerSandbox(container, settings)


@pytest.mark.slow
def test_real_kills_in_the_container(sandbox: DockerSandbox) -> None:
    mutants = [
        _mutant("print(int(input()) - 1)"),  # killed by both tests
        _mutant("n = int(input())\nprint(n + 1 if n < 5 else n)"),  # killed only by test 1
        _mutant("print(1 + int(input()))"),  # equivalent: never killed
        _mutant("while True:\n    pass"),  # hangs: every test times out
    ]
    matrix = run_matrix(TOOL, mutants, REQUEST, TESTS, sandbox, timeout_s=1.0)
    assert matrix.tool == [True, True]
    assert matrix.mutants == [[False, False], [True, False], [True, True], [False, False]]
    score = suite_score(matrix, [0, 1])
    assert (score.killed, score.total) == (3, 4)
    assert suite_score(matrix, [0]).killed == 2
