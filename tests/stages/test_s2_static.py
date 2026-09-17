"""Tests for S2 static (toolvalidator/stages/s2_static.py).

These call the real bandit and mypy. Neither executes the tool's code.
"""

import pytest

from tests.conftest import FakeSandbox
from toolvalidator.contracts import StageResult, ToolArtifact, ValidationRecord
from toolvalidator.stages import s2_static
from toolvalidator.stages.s2_static import (
    StaticAnalysisError,
    parse_bandit_json,
    parse_mypy_output,
)


def _run(code: str, record: ValidationRecord, sandbox: FakeSandbox, **kw: str) -> StageResult:
    art = ToolArtifact(tool_id="t1", code=code)
    return s2_static.run(art, record, sandbox, **kw)  # type: ignore[arg-type]


# --- end-to-end on real analyzers ----------------------------------------------


def test_clean_code_passes(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    res = _run("def f(x: int) -> int:\n    return x + 1\n", record, fake_sandbox)
    assert res.passed
    assert res.stage == "s2_static"
    assert res.data["bandit"] == []
    assert res.data["mypy"] == []
    assert res.data["mypy_error_count"] == 0
    assert record.results == [res]
    assert fake_sandbox.calls == []


def test_high_severity_bandit_finding_rejects(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    code = "import os\ncmd = input()\nos.system(cmd)\n"
    res = _run(code, record, fake_sandbox)
    assert not res.passed
    assert res.category == "dangerous_call"
    assert res.data["line"] == 3
    assert res.detail.startswith("B605:")


def test_medium_finding_is_recorded_but_passes_by_default(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    res = _run("x = eval(input())\n", record, fake_sandbox)
    assert res.passed
    findings = res.data["bandit"]
    assert isinstance(findings, list)
    assert {"test_id": "B307", "severity": "MEDIUM", "confidence": "HIGH", "line": 1}.items() <= (
        findings[0].items()  # type: ignore[union-attr]
    )


def test_medium_finding_rejects_when_threshold_lowered(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    res = _run("x = eval(input())\n", record, fake_sandbox, reject_severity="MEDIUM")
    assert not res.passed
    assert res.category == "dangerous_call"


def test_type_error_is_a_soft_signal(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    res = _run("n = int(input())\nprint(n + 'x')\n", record, fake_sandbox)
    assert res.passed
    assert res.data["mypy_error_count"] == 1
    assert res.data["mypy"] == [
        {
            "line": 2,
            "code": "operator",
            "message": 'Unsupported operand types for + ("int" and "str")',
        }
    ]


def test_errors_inside_untyped_functions_are_checked(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    res = _run("def f(x):\n    return 'a' + 1\n", record, fake_sandbox)
    assert res.data["mypy_error_count"] == 1


def test_repo_strict_mypy_config_does_not_leak(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    # Under the repo's strict config this would be "missing a type annotation".
    res = _run("def f(x):\n    return x\n", record, fake_sandbox)
    assert res.data["mypy_error_count"] == 0


def test_code_is_analysed_not_executed(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    # If this were executed, the test process would exit.
    assert _run("import os\nos._exit(1)\n", record, fake_sandbox).passed


# --- parsers + analyzer failures -----------------------------------------------


def test_parse_mypy_output_handles_windows_paths_and_missing_code() -> None:
    out = (
        "C:\\Temp\\x\\tool.py:5: error: Incompatible return value type  [return-value]\n"
        "C:\\Temp\\x\\tool.py:6: note: See docs\n"
        "/tmp/tool.py:7: error: Something without a code\n"
    )
    errors = parse_mypy_output(out)
    assert [(e.line, e.code) for e in errors] == [(5, "return-value"), (7, None)]
    assert errors[0].message == "Incompatible return value type"


def test_parse_bandit_json_rejects_non_json() -> None:
    with pytest.raises(StaticAnalysisError):
        parse_bandit_json("Traceback (most recent call last): ...")


def test_parse_bandit_json_rejects_reported_errors() -> None:
    with pytest.raises(StaticAnalysisError):
        parse_bandit_json(
            '{"errors": [{"filename": "tool.py", "reason": "syntax error"}], "results": []}'
        )


def test_mypy_crash_raises_instead_of_judging_the_tool(
    record: ValidationRecord, fake_sandbox: FakeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(s2_static.mypy_api, "run", lambda args: ("", "internal error", 2))
    with pytest.raises(StaticAnalysisError, match="mypy"):
        _run("x = 1\n", record, fake_sandbox)
