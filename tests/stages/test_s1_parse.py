"""Tests for S1 parse (toolvalidator/stages/s1_parse.py)."""

from tests.conftest import FakeSandbox
from toolvalidator.contracts import ToolArtifact, ValidationRecord
from toolvalidator.stages import s1_parse


def _tool(code: str) -> ToolArtifact:
    return ToolArtifact(tool_id="t1", code=code)


def test_valid_code_passes_and_is_recorded(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    res = s1_parse.run(_tool("def f(x: int) -> int:\n    return x + 1\n"), record, fake_sandbox)
    assert res.passed
    assert res.stage == "s1_parse"
    assert res.category is None
    assert record.results == [res]


def test_parse_never_uses_the_sandbox(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    s1_parse.run(_tool("x = 1\n"), record, fake_sandbox)
    assert fake_sandbox.calls == []


def test_code_is_parsed_not_executed(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    # If this were executed, the test process would exit.
    res = s1_parse.run(_tool("import os\nos._exit(1)\n"), record, fake_sandbox)
    assert res.passed


def test_syntax_error_fails_with_line(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    res = s1_parse.run(_tool("x = 1\ndef f(:\n    pass\n"), record, fake_sandbox)
    assert not res.passed
    assert res.category == "syntax_error"
    assert res.detail == "invalid syntax"
    assert res.data["line"] == 2
    assert res.data["error_type"] == "SyntaxError"
    assert record.results == [res]


def test_indentation_error_is_a_syntax_error(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    res = s1_parse.run(_tool("def f():\nreturn 1\n"), record, fake_sandbox)
    assert not res.passed
    assert res.category == "syntax_error"
    assert res.data["error_type"] == "IndentationError"
    assert res.data["line"] == 2


def test_null_byte_fails_without_line(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    res = s1_parse.run(_tool("x = 1\x00"), record, fake_sandbox)
    assert not res.passed
    assert res.category == "syntax_error"
    assert "line" not in res.data


def test_parser_overflow_fails_instead_of_raising(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    # CPython raises MemoryError ("Parser stack overflowed") here, not SyntaxError.
    res = s1_parse.run(_tool("-" * 200_000 + "1"), record, fake_sandbox)
    assert not res.passed
    assert res.category == "too_complex"
    assert res.data["error_type"] == "MemoryError"


def test_empty_code_parses(record: ValidationRecord, fake_sandbox: FakeSandbox) -> None:
    # S1 only checks syntax; an empty tool is caught by later (dynamic) stages.
    assert s1_parse.run(_tool(""), record, fake_sandbox).passed
