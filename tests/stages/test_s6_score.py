"""Tests for S6 score (toolvalidator/stages/s6_score.py)."""

from tests.conftest import FakeSandbox
from toolvalidator.contracts import StageResult, ToolArtifact, ValidationRecord
from toolvalidator.scoring.model import ScoreModel
from toolvalidator.stages import s6_score

TOOL = ToolArtifact(tool_id="t1", code="print(1)")
# P(correct) = sigmoid(intercept + 1.0 * (pass_rate - 0.5) / 0.25)
MODEL = ScoreModel(
    signals=["test_pass_rate"],
    features=["test_pass_rate"],
    means=[0.5],
    scales=[0.25],
    coefficients=[1.0],
    intercept=0.0,
)


def _with_generated_tests(record: ValidationRecord, pass_rate: float) -> ValidationRecord:
    record.add(StageResult(stage="s3_testgen", passed=True, data={"accepted": 4}))
    record.add(
        StageResult(stage="s4_execute", passed=True, data={"total": 4, "pass_rate": pass_rate})
    )
    return record


def test_score_is_recorded_and_the_stage_always_passes(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    result = s6_score.run(TOOL, _with_generated_tests(record, 0.5), fake_sandbox, model=MODEL)
    assert result.stage == "s6_score"
    assert result.passed
    assert result.data["score"] == 0.5
    assert result.data["signals"]["test_pass_rate"] == 0.5  # type: ignore[index, call-overload]
    assert record.results[-1] == result
    assert fake_sandbox.calls == []


def test_unscorable_signals_give_a_missing_score(
    record: ValidationRecord, fake_sandbox: FakeSandbox
) -> None:
    result = s6_score.run(TOOL, record, fake_sandbox, model=MODEL)  # no generated tests
    assert result.passed
    assert result.data["score"] is None
    assert result.category == "unscorable"
