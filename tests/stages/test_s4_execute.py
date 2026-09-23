"""Tests for S4 execute (toolvalidator/stages/s4_execute.py)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import FakeSandbox
from toolvalidator.config import SandboxSettings
from toolvalidator.contracts import (
    CapabilityRequest,
    ExecResult,
    IOExample,
    StageResult,
    ToolArtifact,
    ValidationRecord,
)
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import DockerSandbox
from toolvalidator.stages import s4_execute
from toolvalidator.stages.s4_execute import HarnessError, normalize_output, outputs_match

_REQUEST = CapabilityRequest(name="add_one", capability="add_one", description="Read n, print n+1.")
TESTS = [IOExample(input="1", output="2"), IOExample(input="5", output="6")]
ADD_ONE = "print(int(input()) + 1)"


def _tool(code: str = ADD_ONE) -> ToolArtifact:
    return ToolArtifact(tool_id="t1", code=code)


def _sandbox_returning(results: list[dict[str, Any]]) -> FakeSandbox:
    payload = {"results": results}
    return FakeSandbox(
        ExecResult(stdout=json.dumps(payload), stderr="", exit_code=0, duration_s=0.2)
    )


def _result(index: int, **overrides: Any) -> dict[str, Any]:
    base = {
        "index": index,
        "passed": True,
        "timed_out": False,
        "exit_code": 0,
        "actual": "",
        "stderr": "",
    }
    return base | overrides


# --- normalisation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("3", "3\n"),
        ("3\n", "3"),
        ("3 \n", "3"),
        ("a\nb\n", "a\nb"),
        ("a \nb\t\n", "a\nb"),
        ("", "\n"),
    ],
)
def test_normalisation_ignores_trailing_whitespace(actual: str, expected: str) -> None:
    assert normalize_output(actual) == normalize_output(expected)


@pytest.mark.parametrize(("a", "b"), [("3", "4"), ("a\nb", "b\na"), (" 3", "3"), ("3", "3 3")])
def test_normalisation_keeps_real_differences(a: str, b: str) -> None:
    assert normalize_output(a) != normalize_output(b)


# --- unit: stage logic with a fake sandbox ---------------------------------------


def test_all_tests_pass(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([_result(0), _result(1)])
    res = s4_execute.run(_tool(), record, sandbox, tests=TESTS)
    assert res.passed
    assert res.stage == "s4_execute"
    assert res.data["total"] == 2
    assert res.data["passed_count"] == 2
    assert res.data["pass_rate"] == 1.0
    assert record.results == [res]


def test_payload_sent_to_sandbox_has_code_and_tests(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([_result(0), _result(1)])
    s4_execute.run(_tool(), record, sandbox, tests=TESTS)
    (script, stdin, timeout) = sandbox.calls[0]
    payload = json.loads(stdin)
    assert payload["code"] == ADD_ONE
    assert payload["tests"] == [{"input": "1", "output": "2"}, {"input": "5", "output": "6"}]
    assert payload["timeout_s"] > 0
    assert "normalize_output" in script
    assert timeout is not None and timeout >= payload["timeout_s"] * 2


def test_wrong_output_fails_with_pass_rate(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([_result(0), _result(1, passed=False, actual="99")])
    res = s4_execute.run(_tool(), record, sandbox, tests=TESTS)
    assert not res.passed
    assert res.category == "wrong_output"
    assert res.data["pass_rate"] == 0.5
    failures = res.data["failures"]
    assert isinstance(failures, list) and len(failures) == 1


def test_crash_beats_wrong_output(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning(
        [
            _result(0, passed=False, actual="99"),
            _result(1, passed=False, exit_code=1, stderr="boom"),
        ]
    )
    assert s4_execute.run(_tool(), record, sandbox, tests=TESTS).category == "crash"


def test_timeout_beats_crash(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning(
        [_result(0, passed=False, exit_code=1), _result(1, passed=False, timed_out=True)]
    )
    assert s4_execute.run(_tool(), record, sandbox, tests=TESTS).category == "timeout"


def test_no_tests_is_a_failure_without_running_anything(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([])
    res = s4_execute.run(_tool(), record, sandbox, tests=[])
    assert not res.passed
    assert res.category == "no_tests"
    assert sandbox.calls == []


def test_overall_timeout_is_reported(record: ValidationRecord) -> None:
    sandbox = FakeSandbox(
        ExecResult(stdout="", stderr="", exit_code=137, duration_s=9.0, timed_out=True)
    )
    res = s4_execute.run(_tool(), record, sandbox, tests=TESTS)
    assert not res.passed
    assert res.category == "timeout"


def test_broken_harness_output_raises(record: ValidationRecord) -> None:
    sandbox = FakeSandbox(ExecResult(stdout="not json", stderr="", exit_code=0, duration_s=0.1))
    with pytest.raises(HarnessError):
        s4_execute.run(_tool(), record, sandbox, tests=TESTS)


# --- real Docker -----------------------------------------------------------------


@pytest.fixture(scope="module")
def sandbox(docker_client: Any, sandbox_image: str) -> Iterator[DockerSandbox]:
    settings = SandboxSettings()
    with provision(docker_client, settings) as container:
        yield DockerSandbox(container, settings)


def _run(code: str, tests: list[IOExample], sandbox: DockerSandbox, **kw: Any) -> StageResult:
    record = ValidationRecord(request=_REQUEST)
    return s4_execute.run(ToolArtifact(tool_id="t", code=code), record, sandbox, tests=tests, **kw)


@pytest.mark.slow
def test_real_correct_program_passes(sandbox: DockerSandbox) -> None:
    res = _run(ADD_ONE, TESTS, sandbox)
    assert res.passed
    assert res.data["pass_rate"] == 1.0


@pytest.mark.slow
def test_real_trailing_newline_difference_still_passes(sandbox: DockerSandbox) -> None:
    # 5.3% of RunBugRun expected outputs have no trailing newline (docs/MEMORY.md).
    res = _run(ADD_ONE, [IOExample(input="1", output="2")], sandbox)
    assert res.passed


@pytest.mark.slow
def test_real_wrong_program_fails(sandbox: DockerSandbox) -> None:
    res = _run("print(int(input()) + 2)", TESTS, sandbox)
    assert not res.passed
    assert res.category == "wrong_output"
    assert res.data["pass_rate"] == 0.0


@pytest.mark.slow
def test_real_crashing_program_is_a_crash(sandbox: DockerSandbox) -> None:
    res = _run("raise ValueError('nope')", TESTS, sandbox)
    assert res.category == "crash"
    failures = res.data["failures"]
    assert isinstance(failures, list)
    assert "ValueError" in json.dumps(failures)


@pytest.mark.slow
def test_real_infinite_loop_times_out_per_test(sandbox: DockerSandbox) -> None:
    res = _run("while True: pass", TESTS, sandbox, timeout_s=1.0)
    assert res.category == "timeout"


@pytest.mark.slow
def test_real_many_tests_in_one_sandbox_call(sandbox: DockerSandbox) -> None:
    many = [IOExample(input=str(i), output=str(i + 1)) for i in range(50)]
    res = _run(ADD_ONE, many, sandbox)
    assert res.passed
    assert res.data["total"] == 50


# --- float-tolerant comparison ---------------------------------------------------


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("12.566370614359172", "12.5663706144"),  # real case: p02705, 2*pi*r
        ("8.5", "8.50"),
        ("0.1 0.2", "0.100000001 0.199999999"),
        ("ans 1.0000001", "ans 1.0"),
        ("1e-9", "0.0"),
        ("3", "3"),
        ("8", "8.0"),
    ],
)
def test_outputs_match_tolerates_float_formatting(actual: str, expected: str) -> None:
    assert outputs_match(actual, expected, rel_tol=1e-6, abs_tol=1e-6)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [("1326.0", "1326"), ("2.0 3.0", "2 3"), ("0.0", "0"), ("1e3", "1000")],
)
def test_integer_answers_are_compared_exactly(actual: str, expected: str) -> None:
    # Real case: entry 432249 prints 1326.0 (float division) where 1326 is expected.
    # Tolerating that hides the int/float bug class (RunBugRun: type_conversion).
    assert not outputs_match(actual, expected, rel_tol=1e-6, abs_tol=1e-6)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("12.6", "12.5663706144"),
        ("1.1", "1.0"),
        ("1 2", "1 2 3"),
        ("a", "b"),
        ("1\n2", "1"),
        ("nan", "1.0"),
    ],
)
def test_outputs_match_rejects_real_differences(actual: str, expected: str) -> None:
    assert not outputs_match(actual, expected, rel_tol=1e-6, abs_tol=1e-6)


def test_payload_carries_tolerances(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([_result(0), _result(1)])
    s4_execute.run(_tool(), record, sandbox, tests=TESTS, rel_tol=1e-3, abs_tol=1e-4)
    payload = json.loads(sandbox.calls[0][1])
    assert (payload["rel_tol"], payload["abs_tol"]) == (1e-3, 1e-4)


@pytest.mark.slow
def test_real_float_output_passes_with_tolerance(sandbox: DockerSandbox) -> None:
    # p02705-style: expected is rounded, Python prints full precision.
    tests = [IOExample(input="2", output="12.5663706144")]
    assert _run("import math; print(2 * math.pi * int(input()))", tests, sandbox).passed


@pytest.mark.slow
def test_real_float_beyond_tolerance_still_fails(sandbox: DockerSandbox) -> None:
    tests = [IOExample(input="2", output="12.5663706144")]
    assert not _run("print(12.6)", tests, sandbox).passed


# --- tests supplied by S3 --------------------------------------------------------


def _record_with_s3_tests(cases: list[dict[str, str]]) -> ValidationRecord:
    rec = ValidationRecord(request=_REQUEST)
    rec.add(StageResult(stage="s3_testgen", passed=True, data={"tests": cases}))
    return rec


def test_tests_default_to_the_ones_s3_accepted() -> None:
    rec = _record_with_s3_tests([{"input": "1", "output": "2"}])
    sandbox = _sandbox_returning([_result(0)])
    res = s4_execute.run(_tool(), rec, sandbox)
    assert res.passed
    assert json.loads(sandbox.calls[0][1])["tests"] == [{"input": "1", "output": "2"}]


def test_explicit_tests_win_over_the_record() -> None:
    rec = _record_with_s3_tests([{"input": "9", "output": "9"}])
    sandbox = _sandbox_returning([_result(0), _result(1)])
    s4_execute.run(_tool(), rec, sandbox, tests=TESTS)
    assert json.loads(sandbox.calls[0][1])["tests"][0]["input"] == "1"


def test_no_s3_result_and_no_tests_is_no_tests(record: ValidationRecord) -> None:
    sandbox = _sandbox_returning([])
    assert s4_execute.run(_tool(), record, sandbox).category == "no_tests"


def test_malformed_s3_test_entries_are_ignored() -> None:
    rec = ValidationRecord(request=_REQUEST)
    rec.add(StageResult(stage="s3_testgen", passed=True, data={"tests": "not a list"}))
    sandbox = _sandbox_returning([])
    assert s4_execute.run(_tool(), rec, sandbox).category == "no_tests"
