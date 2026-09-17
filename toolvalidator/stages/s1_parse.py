"""S1 parse: does the tool's code parse as Python?

Only parses, never executes, so it runs on the host (CLAUDE.md §7).
"""

import ast

from pydantic import JsonValue

from toolvalidator.contracts import Sandbox, StageResult, ToolArtifact, ValidationRecord

STAGE = "s1_parse"


def run(artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox) -> StageResult:
    try:
        ast.parse(artifact.code)
    except SyntaxError as exc:  # includes IndentationError and null bytes
        return record.add(_failure("syntax_error", exc.msg, exc, exc.lineno))
    except (MemoryError, RecursionError) as exc:
        # CPython's parser overflows on pathologically nested code.
        return record.add(_failure("too_complex", str(exc), exc, None))
    return record.add(StageResult(stage=STAGE, passed=True))


def _failure(category: str, detail: str, exc: BaseException, line: int | None) -> StageResult:
    data: dict[str, JsonValue] = {"error_type": type(exc).__name__}
    if line is not None:
        data["line"] = line
    return StageResult(stage=STAGE, passed=False, category=category, detail=detail, data=data)
