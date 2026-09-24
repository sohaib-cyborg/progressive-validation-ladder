"""Collect the reliability-score inputs (PLAN.md §5.2) from a validation record.

A signal is ``None`` when the stage that produces it did not run or produced nothing:
missing is missing, never a guessed 0 or 1 (CLAUDE.md rule 7). How a missing value
enters the regression is the model's decision (``scoring/model.py``), not ours.

Leakage guard: ``test_pass_rate`` is taken from S4 only when S3 ran before it, i.e.
when S4 executed *generated* tests. S4 on the dataset's own tests is the ground truth
the score is judged against (PLAN.md §5.1), so it must never become an input.

No synthesis metadata: RunBugRun tools carry none (no confidence, no retry count).
"""

from pydantic import BaseModel, ConfigDict, JsonValue

from toolvalidator.contracts import StageResult, ValidationRecord

S2, S3, S4, S5B = "s2_static", "s3_testgen", "s4_execute", "s5b_rubberduck"


class Signals(BaseModel):
    """One tool's score inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bandit_findings: int | None
    mypy_error_count: int | None
    test_pass_rate: float | None
    tests_run: int
    semantics_score: float | None
    semantic_violation: bool | None
    mutation_score: float | None  # TODO(scope): filled once S5 exists


def collect_signals(record: ValidationRecord) -> Signals:
    static = _last(record, S2)
    execute = _last(record, S4)
    generated = execute is not None and 0 <= _index(record, S3) < _index(record, S4)
    pass_rate = _number(execute.data.get("pass_rate")) if generated and execute else None
    duck = _last(record, S5B)
    return Signals(
        bandit_findings=_count(static.data.get("bandit")) if static else None,
        mypy_error_count=_integer(static.data.get("mypy_error_count")) if static else None,
        test_pass_rate=pass_rate,
        tests_run=(_integer(execute.data.get("total")) or 0) if generated and execute else 0,
        semantics_score=_number(duck.data.get("semantics_score")) if duck else None,
        semantic_violation=_violated(duck) if duck else None,
        mutation_score=None,
    )


def _last(record: ValidationRecord, stage: str) -> StageResult | None:
    return next((r for r in reversed(record.results) if r.stage == stage), None)


def _index(record: ValidationRecord, stage: str) -> int:
    """Position of the stage's last result; -1 if it never ran."""
    positions = [i for i, r in enumerate(record.results) if r.stage == stage]
    return positions[-1] if positions else -1


def _violated(result: StageResult) -> bool | None:
    count = _integer(result.data.get("violated"))
    return None if count is None else count > 0


def _count(value: JsonValue) -> int | None:
    return len(value) if isinstance(value, list) else None


def _integer(value: JsonValue) -> int | None:
    # bool is an int subclass; a count must be a real int.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
