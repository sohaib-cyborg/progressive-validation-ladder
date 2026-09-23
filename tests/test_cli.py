"""Tests for the thin CLI entry point (toolvalidator/cli.py)."""

import json
from pathlib import Path

import pytest

from toolvalidator.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REQUEST = EXAMPLES / "celsius.json"


def _validate(tool: Path, request: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:  # type: ignore[type-arg]
    code = main(["validate", "--tool", str(tool), "--request", str(request)])
    return code, json.loads(capsys.readouterr().out)


def test_correct_example_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    code, record = _validate(EXAMPLES / "celsius.py", REQUEST, capsys)
    assert code == 0
    assert record["verdict"] == "ACCEPT"
    assert [r["stage"] for r in record["results"]] == ["s1_parse", "s2_static"]
    assert record["request"]["name"] == "celsius_to_fahrenheit"


def test_logic_bug_passes_static_only_checks(capsys: pytest.CaptureFixture[str]) -> None:
    # Expected: S1+S2 cannot see a wrong formula. This is the gap RQ2 measures.
    code, record = _validate(EXAMPLES / "broken_celsius.py", REQUEST, capsys)
    assert code == 0
    assert record["verdict"] == "ACCEPT"


def test_syntax_error_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tool = tmp_path / "bad.py"
    tool.write_text("def celsius_to_fahrenheit(c:\n    return c\n")
    code, record = _validate(tool, REQUEST, capsys)
    assert code == 1
    assert record["verdict"] == "REJECT"
    assert record["failures"][0]["category"] == "syntax_error"


def test_missing_tool_file_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["validate", "--tool", str(tmp_path / "nope.py"), "--request", str(REQUEST)])
    assert exc.value.code == 2


def test_invalid_request_json_is_a_usage_error(tmp_path: Path) -> None:
    bad = tmp_path / "req.json"
    bad.write_text('{"name": "x"}')  # missing description
    with pytest.raises(SystemExit) as exc:
        main(["validate", "--tool", str(EXAMPLES / "celsius.py"), "--request", str(bad)])
    assert exc.value.code == 2


def test_prompts_command_prints_the_catalogue(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompts"]) == 0
    printed = capsys.readouterr().out
    assert "generate_tests@v1" in printed
    assert "judge_test@v1" in printed
