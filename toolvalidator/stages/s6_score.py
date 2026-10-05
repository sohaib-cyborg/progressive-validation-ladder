"""S6 score: P(tool is correct) from the validator's own signals, by the fitted model.

Collects the signals from the record (``scoring/signals.py``, leakage-guarded) and applies
the deployed model (``scoring/model.py``, fit in RQ4). The stage always passes: it records
the score, and ``pipeline.run_pipeline`` maps an all-pass record to ACCEPT (score at or above
the threshold) or NEEDS_REVIEW (below it, or no score). Hard gates stay outside: a failed
stage has already rejected the tool before S6 runs.
"""

from pydantic import JsonValue

from toolvalidator.contracts import Sandbox, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.scoring.model import ScoreModel, predict
from toolvalidator.scoring.signals import collect_signals

STAGE = "s6_score"


def run(
    artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox, *, model: ScoreModel
) -> StageResult:
    signals = collect_signals(record)
    score = predict(model, signals)
    data: dict[str, JsonValue] = {
        "score": score,
        "signals": signals.model_dump(mode="json"),
        "features": list(model.features),
    }
    if score is None:
        detail = "a signal the model needs is missing, so there is no score"
        return record.add(
            StageResult(stage=STAGE, passed=True, category="unscorable", detail=detail, data=data)
        )
    return record.add(
        StageResult(stage=STAGE, passed=True, detail=f"P(correct) = {score:.3f}", data=data)
    )
