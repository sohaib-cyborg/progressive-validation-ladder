"""S4 execute: run the tool against tests inside the sandbox.

All tests for one tool run in a single sandbox call: a harness script (our code)
runs each case as a subprocess, compares the output there, and reports only
verdicts and short previews, so output stays small no matter how many tests there are.

Comparison ignores trailing whitespace: 5.3% of RunBugRun expected outputs have no
trailing newline (docs/MEMORY.md), so an exact match would fail correct programs.
# TODO(scope): no float tolerance yet; problems with float answers may be judged wrong.
"""

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from toolvalidator.contracts import IOExample, Sandbox, StageResult, ToolArtifact, ValidationRecord

STAGE = "s4_execute"
DEFAULT_TEST_TIMEOUT_S = 5.0
HARNESS_OVERHEAD_S = 10.0
MAX_TEST_OUTPUT_BYTES = 1024 * 1024
PREVIEW_CHARS = 200
MAX_REPORTED_FAILURES = 5


class HarnessError(RuntimeError):
    """The in-sandbox harness failed: our bug, not a verdict on the tool."""


def normalize_output(text: str) -> str:
    """Trailing whitespace is not significant; everything else is."""
    return "\n".join(line.rstrip() for line in text.rstrip().splitlines())


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


_HARNESS = """
import json, resource, subprocess, sys


def normalize_output(text):
    return "\\n".join(line.rstrip() for line in text.rstrip().splitlines())


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
    matches = normalize_output(actual) == normalize_output(case["output"])
    passed = not timed_out and code == 0 and matches
    results.append({
        "index": index, "passed": passed, "timed_out": timed_out, "exit_code": code,
        "actual": "" if passed else actual[:preview], "stderr": "" if passed else stderr[:preview],
    })
print(json.dumps({"results": results}))
"""


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    tests: Sequence[IOExample],
    timeout_s: float | None = None,
) -> StageResult:
    if not tests:
        return record.add(
            StageResult(stage=STAGE, passed=False, category="no_tests", detail="no tests to run")
        )
    per_test = timeout_s if timeout_s is not None else DEFAULT_TEST_TIMEOUT_S
    payload = json.dumps(
        {
            "code": artifact.code,
            "tests": [{"input": _as_text(t.input), "output": _as_text(t.output)} for t in tests],
            "timeout_s": per_test,
            "max_output_bytes": MAX_TEST_OUTPUT_BYTES,
            "preview_chars": PREVIEW_CHARS,
        }
    )
    overall = per_test * len(tests) + HARNESS_OVERHEAD_S
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
    return record.add(_stage_result(report, len(tests), exec_result.duration_s))


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
