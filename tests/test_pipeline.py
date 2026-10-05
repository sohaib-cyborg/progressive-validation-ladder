"""Tests for the pipeline state machine (toolvalidator/pipeline.py)."""

import pytest

from tests.conftest import FakeSandbox
from toolvalidator.config import Settings, StaticSettings
from toolvalidator.contracts import (
    CapabilityRequest,
    FailureReport,
    Sandbox,
    Stage,
    StageResult,
    ToolArtifact,
    ValidationRecord,
    Verdict,
)
from toolvalidator.pipeline import run_pipeline, static_stages

REQUEST = CapabilityRequest(name="t", capability="t", description="d")
TOOL = ToolArtifact(tool_id="t1", code="x = 1\n")


def _stage(name: str, passed: bool, log: list[str]) -> Stage:
    def stage(artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox) -> StageResult:
        log.append(name)
        return record.add(
            StageResult(
                stage=name,
                passed=passed,
                category=None if passed else "boom",
                detail="" if passed else f"{name} failed",
                data={} if passed else {"line": 2},
            )
        )

    return stage


def test_all_stages_pass_gives_accept(fake_sandbox: FakeSandbox) -> None:
    log: list[str] = []
    stages = [_stage("a", True, log), _stage("b", True, log)]
    rec = run_pipeline(TOOL, REQUEST, stages, fake_sandbox)
    assert rec.verdict is Verdict.ACCEPT
    assert log == ["a", "b"]
    assert [r.stage for r in rec.results] == ["a", "b"]
    assert rec.failures == []
    assert rec.request == REQUEST


def test_failure_short_circuits_to_reject(fake_sandbox: FakeSandbox) -> None:
    log: list[str] = []
    stages = [_stage("a", True, log), _stage("b", False, log), _stage("c", True, log)]
    rec = run_pipeline(TOOL, REQUEST, stages, fake_sandbox)
    assert rec.verdict is Verdict.REJECT
    assert log == ["a", "b"]  # c never ran
    assert [r.stage for r in rec.results] == ["a", "b"]
    assert rec.failures == [FailureReport(stage="b", category="boom", message="b failed", line=2)]


def test_stages_receive_the_artifact_and_sandbox(fake_sandbox: FakeSandbox) -> None:
    seen: list[tuple[ToolArtifact, Sandbox]] = []

    def stage(artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox) -> StageResult:
        seen.append((artifact, sandbox))
        return record.add(StageResult(stage="a", passed=True))

    run_pipeline(TOOL, REQUEST, [stage], fake_sandbox)
    assert seen == [(TOOL, fake_sandbox)]


def test_no_stages_is_an_error(fake_sandbox: FakeSandbox) -> None:
    # Accepting a tool that was never checked must be impossible.
    with pytest.raises(ValueError, match="stage"):
        run_pipeline(TOOL, REQUEST, [], fake_sandbox)


def test_stage_that_does_not_record_its_result_is_an_error(fake_sandbox: FakeSandbox) -> None:
    def rogue(artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox) -> StageResult:
        return StageResult(stage="rogue", passed=True)

    with pytest.raises(RuntimeError, match="rogue"):
        run_pipeline(TOOL, REQUEST, [rogue], fake_sandbox)


# --- static configuration (real S1 + S2) ----------------------------------------


def test_static_stages_reject_syntax_error_at_s1(fake_sandbox: FakeSandbox) -> None:
    tool = ToolArtifact(tool_id="t1", code="def f(:\n")
    rec = run_pipeline(tool, REQUEST, static_stages(Settings()), fake_sandbox)
    assert rec.verdict is Verdict.REJECT
    assert [r.stage for r in rec.results] == ["s1_parse"]
    assert rec.failures[0].category == "syntax_error"


def test_static_stages_accept_clean_code(fake_sandbox: FakeSandbox) -> None:
    rec = run_pipeline(TOOL, REQUEST, static_stages(Settings()), fake_sandbox)
    assert rec.verdict is Verdict.ACCEPT
    assert [r.stage for r in rec.results] == ["s1_parse", "s2_static"]
    assert fake_sandbox.calls == []


def test_static_stages_use_configured_bandit_severity(fake_sandbox: FakeSandbox) -> None:
    tool = ToolArtifact(tool_id="t1", code="x = eval(input())\n")
    default = run_pipeline(tool, REQUEST, static_stages(Settings()), fake_sandbox)
    strict_settings = Settings(static=StaticSettings(bandit_reject_severity="MEDIUM"))
    strict = run_pipeline(tool, REQUEST, static_stages(strict_settings), fake_sandbox)
    assert default.verdict is Verdict.ACCEPT
    assert strict.verdict is Verdict.REJECT
    assert strict.failures[0].category == "dangerous_call"


# --- S6: the score maps an all-pass record to ACCEPT or NEEDS_REVIEW ------------------------


def _score_stage(score: float | None) -> Stage:
    def stage(artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox) -> StageResult:
        return record.add(StageResult(stage="s6_score", passed=True, data={"score": score}))

    return stage


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(0.9, Verdict.ACCEPT), (0.5, Verdict.ACCEPT), (0.49, Verdict.NEEDS_REVIEW),
     (None, Verdict.NEEDS_REVIEW)],
)  # fmt: skip
def test_score_decides_accept_or_needs_review(
    fake_sandbox: FakeSandbox, score: float | None, verdict: Verdict
) -> None:
    stages = [_stage("a", True, []), _score_stage(score)]
    rec = run_pipeline(TOOL, REQUEST, stages, fake_sandbox, accept_threshold=0.5)
    assert rec.verdict is verdict
    assert rec.failures == []


def test_a_failed_stage_still_rejects_before_any_score(fake_sandbox: FakeSandbox) -> None:
    stages = [_stage("a", False, []), _score_stage(0.99)]
    assert run_pipeline(TOOL, REQUEST, stages, fake_sandbox).verdict is Verdict.REJECT
