"""Repair signals: turn a failed stage result into a FailureReport.

Minimal for now (one failed result → one report). Richer signals, e.g. from
rubber-duck mismatches, are added in Sprint 4 (docs/reports/SPRINTS.md).
"""

from pydantic import JsonValue

from toolvalidator.contracts import FailureReport, StageResult


def failure_report(result: StageResult) -> FailureReport:
    if result.passed:
        raise ValueError(f"stage {result.stage!r} passed; no failure to report")
    return FailureReport(
        stage=result.stage,
        category=result.category or "unspecified",
        message=result.detail,
        line=_line(result.data.get("line")),
    )


def _line(value: JsonValue) -> int | None:
    # bool is an int subclass; a line number must be a real positive int.
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None
