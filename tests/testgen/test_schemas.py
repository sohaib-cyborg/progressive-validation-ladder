"""Tests for generated-test types (toolvalidator/testgen/schemas.py)."""

import pytest
from pydantic import ValidationError

from toolvalidator.llm.scads_client import LLMOutputError
from toolvalidator.testgen.schemas import GeneratedSuite, GeneratedTest, JudgeVerdict


def test_suite_parses_well_formed_payload() -> None:
    suite = GeneratedSuite.parse(
        {
            "tests": [
                {"input": "2 3", "output": "5", "rationale": "adds"},
                {"input": "0 0", "output": "0"},
            ]
        }
    )
    assert [t.input for t in suite.tests] == ["2 3", "0 0"]
    assert suite.tests[0].rationale == "adds"
    assert suite.tests[1].rationale == ""


def test_numbers_are_coerced_to_text() -> None:
    # Models often answer with numbers; tools read stdin, so tests are text.
    suite = GeneratedSuite.parse({"tests": [{"input": 7, "output": 8}]})
    assert (suite.tests[0].input, suite.tests[0].output) == ("7", "8")


def test_extra_keys_are_ignored() -> None:
    suite = GeneratedSuite.parse(
        {"tests": [{"input": "1", "output": "2", "note": "x"}], "extra": 1}
    )
    assert len(suite.tests) == 1


def test_missing_tests_key_gives_empty_suite() -> None:
    assert GeneratedSuite.parse({}).tests == []


@pytest.mark.parametrize(
    "payload",
    [
        {"tests": "not a list"},
        {"tests": [{"input": "1"}]},
        {"tests": [{"input": [1], "output": "2"}]},
    ],
)
def test_malformed_suites_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(LLMOutputError):
        GeneratedSuite.parse(payload)  # type: ignore[arg-type]


def test_generated_test_is_frozen() -> None:
    test = GeneratedTest(input="1", output="2")
    with pytest.raises(ValidationError):
        test.input = "3"  # type: ignore[misc]


def test_judge_verdict_parses_and_rejects_malformed() -> None:
    assert JudgeVerdict.parse({"valid": True, "reason": "matches the description"}).valid is True
    assert JudgeVerdict.parse({"valid": False}).reason == ""
    with pytest.raises(LLMOutputError):
        JudgeVerdict.parse({"reason": "no verdict field"})
