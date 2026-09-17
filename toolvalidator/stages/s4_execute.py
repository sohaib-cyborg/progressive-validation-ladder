"""S4 execute: run the tool against tests inside the sandbox.

All tests for one tool run in a single sandbox call: a harness script (our code)
runs each case as a subprocess, compares the output there, and reports only
verdicts and short previews, so output stays small no matter how many tests there are.

Comparison ignores trailing whitespace (5.3% of RunBugRun expected outputs have no
trailing newline) and compares numbers with a tolerance, because expected outputs are
rounded while Python prints full precision. Both were measured causes of wrongly
rejecting correct programs (docs/reports/sprint-02.md).

Tests come from the caller, or from what S3 accepted when none are given.
"""

import inspect
import json
import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from toolvalidator.contracts import IOExample, Sandbox, StageResult, ToolArtifact, ValidationRecord

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


class HarnessError(RuntimeError):
    """The in-sandbox harness failed: our bug, not a verdict on the tool."""


def normalize_output(text: str) -> str:
    """Trailing whitespace is not significant; everything else is."""
    return "\n".join(line.rstrip() for line in text.rstrip().splitlines())


def outputs_match(actual: str, expected: str, *, rel_tol: float, abs_tol: float) -> bool:
    """Equal after normalisation, or equal token by token with float tolerance.

    Competitive-programming expected outputs are rounded (``12.5663706144``) while
    Python prints full precision (``12.566370614359172``). Comparing text alone
    rejects correct programs, which measured 3 of 9 false rejections in the pilot.
    """
    actual, expected = normalize_output(actual), normalize_output(expected)
    if actual == expected:
        return True
    actual_lines, expected_lines = actual.splitlines(), expected.splitlines()
    if len(actual_lines) != len(expected_lines):
        return False
    for actual_line, expected_line in zip(actual_lines, expected_lines, strict=True):
        actual_tokens, expected_tokens = actual_line.split(), expected_line.split()
        if len(actual_tokens) != len(expected_tokens):
            return False
        for got, want in zip(actual_tokens, expected_tokens, strict=True):
            if got != want and not _close(got, want, rel_tol, abs_tol):
                return False
    return True


def _close(got: str, want: str, rel_tol: float, abs_tol: float) -> bool:
    # Only when the EXPECTED answer is fractional. If the task expects 1326, then
    # 1326.0 is wrong: that is exactly the int/float bug class RunBugRun labels
    # type_conversion, and tolerating it hid 4 real bugs in the pilot.
    if not any(char in want for char in ".eE"):
        return False
    try:
        got_value, want_value = float(got), float(want)
    except ValueError:
        return False
    if math.isnan(got_value) or math.isnan(want_value):
        return False  # NaN never equals a real expected answer
    return math.isclose(got_value, want_value, rel_tol=rel_tol, abs_tol=abs_tol)


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


_HARNESS_MAIN = """
payload = json.load(sys.stdin)
cap = payload["max_output_bytes"]
preview = payload["preview_chars"]
with open("tool.py", "w", encoding="utf-8") as handle:
    handle.write(payload["code"])


def limit_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


results = []
for index, case in enumerate(payload["tests"]):
    with open("out", "wb") as out, open("err", "wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "tool.py"], stdin=subprocess.PIPE, stdout=out, stderr=err,
            preexec_fn=limit_output,
        )
        timed_out = False
        try:
            proc.communicate(case["input"].encode("utf-8"), timeout=payload["timeout_s"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            timed_out = True
    with open("out", "rb") as handle:
        actual = handle.read(cap).decode("utf-8", "replace")
    with open("err", "rb") as handle:
        stderr = handle.read(cap).decode("utf-8", "replace")
    returned = proc.returncode
    code = returned if returned is None or returned >= 0 else 128 - returned
    matches = outputs_match(
        actual, case["output"], rel_tol=payload["rel_tol"], abs_tol=payload["abs_tol"]
    )
    passed = not timed_out and code == 0 and matches
    results.append({
        "index": index, "passed": passed, "timed_out": timed_out, "exit_code": code,
        "actual": "" if passed else actual[:preview], "stderr": "" if passed else stderr[:preview],
    })
print(json.dumps({"results": results}))
"""

# The harness compares outputs with the very functions tested on the host.
_HARNESS = "\n".join(
    [
        "import json, math, resource, subprocess, sys",
        inspect.getsource(normalize_output),
        inspect.getsource(outputs_match),
        inspect.getsource(_close),
        _HARNESS_MAIN,
    ]
)


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    tests: Sequence[IOExample] | None = None,
    timeout_s: float | None = None,
    rel_tol: float = DEFAULT_REL_TOL,
    abs_tol: float = DEFAULT_ABS_TOL,
) -> StageResult:
    cases = list(tests) if tests is not None else tests_from_record(record)
    if not cases:
        return record.add(
            StageResult(stage=STAGE, passed=False, category="no_tests", detail="no tests to run")
        )
    per_test = timeout_s if timeout_s is not None else DEFAULT_TEST_TIMEOUT_S
    payload = json.dumps(
        {
            "code": artifact.code,
            "tests": [{"input": _as_text(t.input), "output": _as_text(t.output)} for t in cases],
            "timeout_s": per_test,
            "rel_tol": rel_tol,
            "abs_tol": abs_tol,
            "max_output_bytes": MAX_TEST_OUTPUT_BYTES,
            "preview_chars": PREVIEW_CHARS,
        }
    )
    overall = per_test * len(cases) + HARNESS_OVERHEAD_S
    exec_result = sandbox.run(_HARNESS, stdin=payload, timeout_s=overall)
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
    if any(f.timed_out for f in failures):
        return "timeout"
    if any(f.exit_code != 0 for f in failures):
        return "crash"
    return "wrong_output"


def _as_text(value: JsonValue) -> str:
    """Tests are fed on stdin, so non-string example values are rendered as JSON."""
    return value if isinstance(value, str) else json.dumps(value)
