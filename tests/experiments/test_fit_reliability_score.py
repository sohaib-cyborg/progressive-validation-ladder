"""Tests for the RQ4 runner (experiments/fit_reliability_score.py).

The rows here are synthetic and only exercise the plumbing; none of it is a result.
"""

import json
import random
from pathlib import Path

import pytest

from experiments.fit_reliability_score import MUTATION_SETS, SIGNAL_SETS, fit_rows, main
from experiments.run_testgen_strategies import ArmOutcome, StrategyOutcome
from toolvalidator.scoring.model import ScoreModel
from toolvalidator.scoring.signals import Signals


def _row(problem: int, correct: bool, rng: random.Random, gated: bool = False) -> StrategyOutcome:
    rate = rng.uniform(0.8, 1.0) if correct else rng.uniform(0.0, 0.7)
    signals = Signals(
        bandit_findings=0,
        mypy_error_count=rng.randint(0, 2),
        test_pass_rate=rate,
        tests_run=8,
        semantics_score=rng.random(),
        semantic_violation=rng.random() < 0.5,
        mutation_score=None,
    )
    arm = ArmOutcome(n_tests=8, pass_rate=rate, category=None)
    return StrategyOutcome(
        entry_id=problem,
        problem_id=f"p{problem}",
        split="valid",
        variant="fixed" if correct else "buggy",
        is_correct=correct,
        bug_labels=[],
        gate_category="syntax_error" if gated else None,
        suite_generated=8,
        suite_accepted=8,
        arms={} if gated else {"examples": arm, "generated": arm, "judged": arm},
        semantics_score=None if gated else signals.semantics_score,
        semantic_violation=None if gated else signals.semantic_violation,
        signals=None if gated else signals,
    )


def _rows(n_problems: int = 30) -> list[StrategyOutcome]:
    rng = random.Random(3)
    return [_row(p, correct, rng) for p in range(n_problems) for correct in (True, False)]


def test_gated_tools_stay_outside_the_fit() -> None:
    rows = [*_rows(), _row(99, False, random.Random(1), gated=True)]
    report = fit_rows(rows, folds=5)
    assert report["n_gate_rejected_excluded"] == 1
    assert report["fit"]["n"] == 60  # type: ignore[index, call-overload]


def test_main_writes_a_report(tmp_path: Path) -> None:
    rows_path = tmp_path / "testgen_dev.jsonl"
    rows_path.write_text("".join(r.model_dump_json() + "\n" for r in _rows()), encoding="utf-8")
    out = tmp_path / "rq4.json"
    assert main(["--rows", str(rows_path), "--out", str(out), "--folds", "5"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["fit"]["auc"] > 0.9  # pass rate separates the synthetic classes
    assert "test_pass_rate" in report["fit"]["ablation"]
    assert report["rows"] == str(rows_path)


def test_main_writes_the_deployed_model_on_the_all_signal_set(tmp_path: Path) -> None:
    rows_path = tmp_path / "testgen_eval.jsonl"
    rows_path.write_text("".join(r.model_dump_json() + "\n" for r in _rows()), encoding="utf-8")
    model_path = tmp_path / "score_model.json"
    args = ["--rows", str(rows_path), "--out", str(tmp_path / "rq4.json")]
    assert main([*args, "--model-out", str(model_path)]) == 0
    model = ScoreModel.model_validate_json(model_path.read_text(encoding="utf-8"))
    assert set(model.signals) <= set(SIGNAL_SETS["all"])
    assert "mutation_score" not in model.signals
    assert "test_pass_rate" in model.features


def test_no_usable_rows_is_an_error(tmp_path: Path) -> None:
    rows_path = tmp_path / "empty.jsonl"
    rows_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        main(["--rows", str(rows_path), "--out", str(tmp_path / "x.json")])


def test_mutation_sets_are_fit_when_asked() -> None:
    rng = random.Random(5)
    rows = [
        r.model_copy(
            update={"signals": r.signals.model_copy(update={"mutation_score": rng.random()})}
        )
        for r in _rows()
        if r.signals is not None
    ]
    report = fit_rows(rows, folds=5, sets=SIGNAL_SETS | MUTATION_SETS)
    sets = report["signal_sets"]
    assert isinstance(sets, dict)
    assert {"all_plus_mutation", "tests_plus_mutation", "mutation_only"} <= set(sets)
    assert sets["mutation_only"]["signals"] == ["mutation_score"]  # type: ignore[index, call-overload]


def test_named_signal_sets_are_fit_separately() -> None:
    report = fit_rows(_rows(), folds=5)
    sets = report["signal_sets"]
    assert isinstance(sets, dict)
    assert set(sets) == {"all", "without_s5b", "tests_only", "s5b_only", "static_only"}
    for metrics in sets.values():
        assert isinstance(metrics, dict) and {"auc", "spearman", "brier"} <= set(metrics)
