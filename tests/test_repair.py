"""Tests for repair signals (toolvalidator/repair.py)."""

import pytest

from toolvalidator.contracts import FailureReport, StageResult
from toolvalidator.repair import failure_report


def test_failure_report_copies_stage_category_detail_and_line() -> None:
    res = StageResult(
        stage="s1_parse",
        passed=False,
        category="syntax_error",
        detail="invalid syntax",
        data={"line": 4, "error_type": "SyntaxError"},
    )
    assert failure_report(res) == FailureReport(
        stage="s1_parse", category="syntax_error", message="invalid syntax", line=4
    )


def test_missing_or_invalid_line_becomes_none() -> None:
    for data in ({}, {"line": 0}, {"line": "3"}, {"line": True}, {"line": None}):
        res = StageResult(stage="s2_static", passed=False, category="dangerous_call", data=data)
        assert failure_report(res).line is None


def test_failed_result_without_category_is_unspecified() -> None:
    res = StageResult(stage="s9", passed=False)
    assert failure_report(res).category == "unspecified"


def test_passed_result_has_no_failure_report() -> None:
    with pytest.raises(ValueError, match="passed"):
        failure_report(StageResult(stage="s1_parse", passed=True))
