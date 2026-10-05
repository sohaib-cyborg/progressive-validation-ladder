"""The pipeline state machine: run stages in order, short-circuit on failure.

Deterministic: the verdict depends only on the stage results (CLAUDE.md rule 5). The S6
score is a number computed in Python; comparing it to a fixed threshold is deterministic.
"""

from collections.abc import Sequence
from functools import partial

from toolvalidator.config import ScoreSettings, Settings
from toolvalidator.contracts import (
    CapabilityRequest,
    Sandbox,
    Stage,
    ToolArtifact,
    ValidationRecord,
    Verdict,
)
from toolvalidator.repair import failure_report
from toolvalidator.stages import s1_parse, s2_static


def run_pipeline(
    artifact: ToolArtifact,
    request: CapabilityRequest,
    stages: Sequence[Stage],
    sandbox: Sandbox,
    *,
    accept_threshold: float = ScoreSettings().accept_threshold,
) -> ValidationRecord:
    """Run ``stages`` in order. The first failed stage → REJECT + FailureReport.

    If every stage passes: with no S6 result the verdict is ACCEPT; with one, a score at or
    above ``accept_threshold`` is ACCEPT and anything else (lower, or no score) NEEDS_REVIEW.
    """
    if not stages:
        raise ValueError("pipeline needs at least one stage")
    record = ValidationRecord(request=request)
    for stage in stages:
        result = stage(artifact, record, sandbox)
        if not record.results or record.results[-1] is not result:
            raise RuntimeError(f"stage {result.stage!r} did not add its result to the record")
        if not result.passed:
            record.failures.append(failure_report(result))
            record.verdict = Verdict.REJECT
            return record
    record.verdict = _all_pass_verdict(record, accept_threshold)
    return record


def _all_pass_verdict(record: ValidationRecord, threshold: float) -> Verdict:
    score_result = next((r for r in reversed(record.results) if r.stage == "s6_score"), None)
    if score_result is None:
        return Verdict.ACCEPT
    score = score_result.data.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        return Verdict.NEEDS_REVIEW  # no score: the validator cannot vouch for the tool
    return Verdict.ACCEPT if score >= threshold else Verdict.NEEDS_REVIEW


def static_stages(settings: Settings) -> list[Stage]:
    """The static-only configuration (RQ2 baseline): S1 parse → S2 static."""
    return [
        s1_parse.run,
        partial(s2_static.run, reject_severity=settings.static.bandit_reject_severity),
    ]
