"""S2 static: bandit (dangerous calls, hard gate) + mypy (type errors, soft signal).

Deliberately minimal: this is the cheap baseline for RQ2 (DECISIONS.md). Both
analyzers read the source without executing it, so they run on the host
(CLAUDE.md §7). Every bandit finding is recorded at every severity, so experiments
can re-threshold offline.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from mypy import api as mypy_api
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from toolvalidator.config import Severity
from toolvalidator.contracts import Sandbox, StageResult, ToolArtifact, ValidationRecord

STAGE = "s2_static"
_ANALYZER_TIMEOUT_S = 120
_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
# --config-file= stops the repo's own strict [tool.mypy] config applying to tools.
# --no-site-packages keeps results independent of what our dev venv has installed.
_MYPY_FLAGS = [
    "--config-file=",
    "--no-error-summary",
    "--show-error-codes",
    "--check-untyped-defs",
    "--ignore-missing-imports",
    "--no-site-packages",
    "--cache-dir",
    str(Path(tempfile.gettempdir()) / "toolvalidator-mypy-cache"),
]
_MYPY_ERROR = re.compile(r"^.+?:(?P<line>\d+): error: (?P<msg>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?$")


class StaticAnalysisError(RuntimeError):
    """An analyzer itself failed: an infrastructure problem, not a verdict on the tool."""


class BanditFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    test_id: str
    severity: str
    confidence: str
    line: int
    text: str


class MypyError(BaseModel):
    model_config = ConfigDict(frozen=True)

    line: int
    code: str | None
    message: str


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    reject_severity: Severity = "HIGH",
) -> StageResult:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tool.py"
        path.write_text(artifact.code, encoding="utf-8", newline="")
        findings = run_bandit(path)
        type_errors = run_mypy(path)

    data: dict[str, JsonValue] = {
        "bandit": [f.model_dump(mode="json") for f in findings],
        "mypy": [e.model_dump(mode="json") for e in type_errors],
        "mypy_error_count": len(type_errors),
    }
    threshold = _SEVERITY_RANK[reject_severity]
    blocking = [f for f in findings if _SEVERITY_RANK.get(f.severity, 0) >= threshold]
    if not blocking:
        return record.add(StageResult(stage=STAGE, passed=True, data=data))
    first = min(blocking, key=lambda f: f.line)
    data["line"] = first.line
    detail = f"{first.test_id}: {first.text}"
    return record.add(
        StageResult(stage=STAGE, passed=False, category="dangerous_call", detail=detail, data=data)
    )


def run_bandit(path: Path) -> list[BanditFinding]:
    cmd = [sys.executable, "-m", "bandit", "-f", "json", "-q", path.name]
    try:
        proc = subprocess.run(
            cmd, cwd=path.parent, capture_output=True, text=True, timeout=_ANALYZER_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as exc:
        raise StaticAnalysisError("bandit timed out") from exc
    if proc.returncode not in (0, 1):  # 1 = issues found
        raise StaticAnalysisError(f"bandit exited {proc.returncode}: {proc.stderr[-500:]}")
    return parse_bandit_json(proc.stdout)


def parse_bandit_json(raw: str) -> list[BanditFinding]:
    try:
        report = json.loads(raw)
        if report.get("errors"):
            raise StaticAnalysisError(f"bandit reported errors: {report['errors']}")
        return [
            BanditFinding(
                test_id=r["test_id"],
                severity=r["issue_severity"],
                confidence=r["issue_confidence"],
                line=r["line_number"],
                text=r["issue_text"],
            )
            for r in report["results"]
        ]
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValidationError) as exc:
        raise StaticAnalysisError(f"unreadable bandit output: {raw[:200]!r}") from exc


def run_mypy(path: Path) -> list[MypyError]:
    stdout, stderr, exit_code = mypy_api.run([*_MYPY_FLAGS, str(path)])
    if exit_code not in (0, 1):  # 1 = type errors found
        raise StaticAnalysisError(f"mypy exited {exit_code}: {stderr[-500:]}")
    return parse_mypy_output(stdout)


def parse_mypy_output(stdout: str) -> list[MypyError]:
    errors = []
    for line in stdout.splitlines():
        if match := _MYPY_ERROR.match(line):
            errors.append(
                MypyError(line=int(match["line"]), code=match["code"], message=match["msg"])
            )
    return errors
