"""Tests for signal collection (toolvalidator/scoring/signals.py)."""

from pydantic import JsonValue

from toolvalidator.contracts import StageResult, ValidationRecord
from toolvalidator.scoring.signals import Signals, collect_signals


def _add(record: ValidationRecord, stage: str, passed: bool = True, **data: JsonValue) -> None:
    record.add(StageResult(stage=stage, passed=passed, data=data))


def _static(record: ValidationRecord, *, bandit: int = 0, mypy: int = 0) -> None:
    findings: list[JsonValue] = [{"line": 1}] * bandit
    _add(record, "s1_parse")
    _add(record, "s2_static", bandit=findings, mypy=[], mypy_error_count=mypy)


def test_full_record_yields_every_signal(record: ValidationRecord) -> None:
    _static(record, bandit=2, mypy=3)
    _add(record, "s3_testgen", accepted=4)
    _add(record, "s4_execute", passed=False, total=4, pass_rate=0.75)
    _add(record, "s5b_rubberduck", semantics_score=0.5, violated=1)
    assert collect_signals(record) == Signals(
        bandit_findings=2,
        mypy_error_count=3,
        test_pass_rate=0.75,
        tests_run=4,
        semantics_score=0.5,
        semantic_violation=True,
        mutation_score=None,
    )


def test_stages_that_did_not_run_give_missing_signals(record: ValidationRecord) -> None:
    _static(record)
    signals = collect_signals(record)
    assert signals.test_pass_rate is None
    assert signals.tests_run == 0
    assert signals.semantics_score is None
    assert signals.semantic_violation is None
    assert signals.mutation_score is None


def test_pass_rate_on_tests_s3_did_not_generate_is_ignored(record: ValidationRecord) -> None:
    # S4 on the dataset's own tests is the ground truth; using it would leak the label.
    _static(record)
    _add(record, "s4_execute", total=100, pass_rate=1.0)
    signals = collect_signals(record)
    assert signals.test_pass_rate is None
    assert signals.tests_run == 0


def test_s4_with_no_generated_tests_has_no_pass_rate(record: ValidationRecord) -> None:
    _static(record)
    _add(record, "s3_testgen", accepted=0)
    _add(record, "s4_execute", passed=False)  # category no_tests, no data
    assert collect_signals(record).test_pass_rate is None


def test_undecided_rubberduck_keeps_violation_flag_but_no_score(record: ValidationRecord) -> None:
    _static(record)
    _add(record, "s5b_rubberduck", semantics_score=None, violated=0)
    signals = collect_signals(record)
    assert signals.semantics_score is None
    assert signals.semantic_violation is False


def _mutation(record: ValidationRecord, arm: str, score: float | None, from_s3: bool) -> None:
    _add(record, "s5_mutation", arm=arm, mutation_score=score, from_s3=from_s3)


def test_mutation_score_comes_from_arm_a_by_default(record: ValidationRecord) -> None:
    _static(record)
    _mutation(record, "A", 0.6, from_s3=True)
    _mutation(record, "B", 0.8, from_s3=True)
    assert collect_signals(record).mutation_score == 0.6
    assert collect_signals(record, mutation_arm="B").mutation_score == 0.8


def test_mutation_on_tests_s3_did_not_generate_is_ignored(record: ValidationRecord) -> None:
    # Like the pass rate: mutation measured on the dataset's own tests would leak the label.
    _static(record)
    _mutation(record, "A", 0.9, from_s3=False)
    assert collect_signals(record).mutation_score is None


def test_missing_mutation_score_stays_missing(record: ValidationRecord) -> None:
    _static(record)
    _mutation(record, "A", None, from_s3=True)
    assert collect_signals(record).mutation_score is None


def test_signals_require_the_static_stage(record: ValidationRecord) -> None:
    _add(record, "s1_parse")
    signals = collect_signals(record)
    assert signals.bandit_findings is None
    assert signals.mypy_error_count is None
