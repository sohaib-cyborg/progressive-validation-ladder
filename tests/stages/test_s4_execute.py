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
from toolvalidator.stages.s4_execute import HarnessError, normalize_output

_REQUEST = CapabilityRequest(name="add_one", description="Read n, print n+1.")
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
