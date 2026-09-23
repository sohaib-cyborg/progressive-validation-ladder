"""S4 execute: run the tool against tests inside the sandbox.

All tests for one tool run in a single sandbox call: a harness script (our code)
runs each case as a subprocess, compares the output there, and reports only
verdicts and short previews, so output stays small no matter how many tests there are.

Comparison ignores trailing whitespace (5.3% of RunBugRun expected outputs have no
trailing newline) and compares numbers with a tolerance, because expected outputs are
rounded while Python prints full precision. Both were measured causes of wrongly
rejecting correct programs (docs/reports/sprint-02.md).

Tests come from the caller, or from what S3 accepted when none are given.

The comparison rules and the harness text live in ``stages/harness.py``;
``normalize_output`` and ``outputs_match`` are re-exported here for callers and tests.
"""

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from toolvalidator.contracts import (
    CapabilityRequest,
    IOExample,
    Sandbox,
    StageResult,
    ToolArtifact,
    ValidationRecord,
)
from toolvalidator.stages.harness import (
    FUNCTION_DRIVER,
    FUNCTION_HARNESS,
    STDIN_HARNESS,
    normalize_output,
    outputs_match,
)

__all__ = [
    "ExecutionMode",
    "HarnessError",
    "execution_mode",
    "normalize_output",
    "outputs_match",
    "run",
    "tests_from_record",
]

type ExecutionMode = Literal["stdin", "function"]

STAGE = "s4_execute"
# 10s, not 5s: 4 of 9 pilot false rejections were slow-but-correct programs
# (docs/reports/sprint-02.md).
DEFAULT_TEST_TIMEOUT_S = 10.0
DEFAULT_REL_TOL = 1e-6
DEFAULT_ABS_TOL = 1e-6
HARNESS_OVERHEAD_S = 10.0
MAX_TEST_OUTPUT_BYTES = 1024 * 1024
PREVIEW_CHARS = 200
MAX_REPORTED_FAILURES = 5
NO_ENTRYPOINT_MARKER = "TV_NO_ENTRYPOINT"


class HarnessError(RuntimeError):
    """The in-sandbox harness failed: our bug, not a verdict on the tool."""


class _TestOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    passed: bool
    timed_out: bool
    exit_code: int
    actual: str = ""
    stderr: str = ""


class _HarnessReport(BaseModel):
    results: list[_TestOutcome]


def execution_mode(request: CapabilityRequest) -> ExecutionMode:
    """How the tool is invoked, from the request's declared inputs.

    A request whose only input is ``stdin`` (or which declares none) describes a
    stdin/stdout program, as the RunBugRun mapping does. Anything else declares typed
    parameters, so the tool is a function to call (docs/capability_request.md §2).
    """
    names = {param.name for param in request.inputs}
    return "stdin" if not names or names == {"stdin"} else "function"


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    tests: Sequence[IOExample] | None = None,
    timeout_s: float | None = None,
    rel_tol: float = DEFAULT_REL_TOL,
    abs_tol: float = DEFAULT_ABS_TOL,
    mode: ExecutionMode | None = None,
) -> StageResult:
    cases = list(tests) if tests is not None else tests_from_record(record)
    if not cases:
        return record.add(
            StageResult(stage=STAGE, passed=False, category="no_tests", detail="no tests to run")
        )
    per_test = timeout_s if timeout_s is not None else DEFAULT_TEST_TIMEOUT_S
    resolved = mode if mode is not None else execution_mode(record.request)
    common: dict[str, JsonValue] = {
        "mode": resolved,
        "code": artifact.code,
        "timeout_s": per_test,
        "rel_tol": rel_tol,
        "abs_tol": abs_tol,
        "max_output_bytes": MAX_TEST_OUTPUT_BYTES,
        "preview_chars": PREVIEW_CHARS,
    }
    if resolved == "function":
        script = FUNCTION_HARNESS
        common["entrypoint"] = record.request.name
        common["driver"] = FUNCTION_DRIVER
        common["tests"] = [{"input": t.input, "output": t.output} for t in cases]
    else:
        script = STDIN_HARNESS
        common["tests"] = [
            {"input": _as_text(t.input), "output": _as_text(t.output)} for t in cases
        ]
    payload = json.dumps(common)
    overall = per_test * len(cases) + HARNESS_OVERHEAD_S
    exec_result = sandbox.run(script, stdin=payload, timeout_s=overall)
    if exec_result.timed_out:
        detail = f"harness exceeded the overall timeout of {overall:.0f}s"
        return record.add(StageResult(stage=STAGE, passed=False, category="timeout", detail=detail))
    if exec_result.exit_code != 0:
        raise HarnessError(f"harness exited {exec_result.exit_code}: {exec_result.stderr[-500:]}")
    try:
        report = _HarnessReport.model_validate_json(exec_result.stdout)
    except ValidationError as exc:
        raise HarnessError(f"unreadable harness output: {exec_result.stdout[:200]!r}") from exc
    return record.add(_stage_result(report, len(cases), exec_result.duration_s))


def tests_from_record(record: ValidationRecord) -> list[IOExample]:
    """The tests S3 accepted, if S3 ran. Empty when there are none."""
    stage_result = next((r for r in reversed(record.results) if r.stage == "s3_testgen"), None)
    if stage_result is None:
        return []
    cases = stage_result.data.get("tests")
    if not isinstance(cases, list):
        return []
    return [
        IOExample(input=case["input"], output=case["output"])
        for case in cases
        if isinstance(case, dict) and "input" in case and "output" in case
    ]


def _stage_result(report: _HarnessReport, total: int, duration_s: float) -> StageResult:
    failures = [outcome for outcome in report.results if not outcome.passed]
    passed_count = total - len(failures)
    data: dict[str, JsonValue] = {
        "total": total,
        "passed_count": passed_count,
        "pass_rate": passed_count / total,
        "duration_s": duration_s,
        "failures": [f.model_dump(mode="json") for f in failures[:MAX_REPORTED_FAILURES]],
    }
    if not failures:
        return StageResult(stage=STAGE, passed=True, data=data)
    category = _category(failures)
    detail = (
        f"{len(failures)} of {total} tests failed ({category}, first: test {failures[0].index})"
    )
    return StageResult(stage=STAGE, passed=False, category=category, detail=detail, data=data)


def _category(failures: Sequence[_TestOutcome]) -> str:
    if all(NO_ENTRYPOINT_MARKER in f.stderr for f in failures):
        return "no_entrypoint"  # the tool never defined the requested function
    if any(f.timed_out for f in failures):
        return "timeout"
    if any(f.exit_code != 0 for f in failures):
        return "crash"
    return "wrong_output"


def _as_text(value: JsonValue) -> str:
    """Tests are fed on stdin, so non-string example values are rendered as JSON."""
    return value if isinstance(value, str) else json.dumps(value)
