"""The pipeline state machine: run stages in order, short-circuit on failure.

Deterministic: the verdict depends only on the stage results (CLAUDE.md rule 5).
"""

from collections.abc import Sequence
from functools import partial

from toolvalidator.config import Settings
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
) -> ValidationRecord:
    """Run ``stages`` in order. The first failed stage → REJECT + FailureReport.

    If every stage passes the verdict is ACCEPT.
    """
    # TODO(scope): once S6 exists, the score decides ACCEPT vs. NEEDS_REVIEW.
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
    record.verdict = Verdict.ACCEPT
    return record


def static_stages(settings: Settings) -> list[Stage]:
    """The static-only configuration (RQ2 baseline): S1 parse → S2 static."""
    return [
        s1_parse.run,
        partial(s2_static.run, reject_severity=settings.static.bandit_reject_severity),
    ]
