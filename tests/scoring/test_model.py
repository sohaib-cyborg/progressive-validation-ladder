"""Tests for the reliability-score model (toolvalidator/scoring/model.py).

The data here is synthetic and exists only to exercise the fitting code; none of it is
a result.
"""

import random

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from toolvalidator.scoring.model import (
    ScoreModel,
    evaluate,
    feature_matrix,
    fit_model,
    group_folds,
    predict,
)
from toolvalidator.scoring.signals import Signals


def _signals(
    pass_rate: float | None, semantics: float | None = None, mypy: int | None = 0
) -> Signals:
    return Signals(
        bandit_findings=0,
        mypy_error_count=mypy,
        test_pass_rate=pass_rate,
        tests_run=0 if pass_rate is None else 8,
        semantics_score=semantics,
        semantic_violation=None if semantics is None else semantics < 1.0,
        mutation_score=None,
    )


def _synthetic(n_problems: int = 40, seed: int = 7) -> tuple[list[Signals], list[bool], list[str]]:
    """Two tools per problem: a correct one with a high pass rate, a buggy one lower."""
    rng = random.Random(seed)
    rows: list[Signals] = []
    labels: list[bool] = []
    groups: list[str] = []
    for p in range(n_problems):
        for correct in (True, False):
            rate = rng.uniform(0.8, 1.0) if correct else rng.uniform(0.0, 0.7)
            rows.append(_signals(rate, semantics=rng.random(), mypy=rng.randint(0, 3)))
            labels.append(correct)
            groups.append(f"p{p}")
    return rows, labels, groups


def test_missing_values_get_an_indicator_and_all_missing_signals_are_dropped() -> None:
    rows = [_signals(0.5, mypy=None), _signals(None, mypy=1)]
    matrix, columns, dropped = feature_matrix(rows)
    assert "test_pass_rate" in columns and "test_pass_rate_missing" in columns
    assert "mutation_score" in dropped  # never observed: no information, reported
    rate = columns.index("test_pass_rate")
    missing = columns.index("test_pass_rate_missing")
    assert [row[rate] for row in matrix] == [0.5, 0.0]
    assert [row[missing] for row in matrix] == [0.0, 1.0]


def test_booleans_become_zero_or_one() -> None:
    matrix, columns, _ = feature_matrix([_signals(1.0, semantics=0.5), _signals(1.0, 1.0)])
    violation = columns.index("semantic_violation")
    assert [row[violation] for row in matrix] == [1.0, 0.0]


def test_group_folds_never_split_a_problem() -> None:
    groups = [f"p{i // 2}" for i in range(20)]
    folds = group_folds(groups, 5)
    assert len(folds) == 5
    seen_in_test: list[int] = []
    for train, test in folds:
        assert {groups[i] for i in train}.isdisjoint({groups[i] for i in test})
        seen_in_test += test
    assert sorted(seen_in_test) == list(range(20))


def test_too_few_problems_for_the_folds_raises() -> None:
    with pytest.raises(ValueError, match="problems"):
        group_folds(["a", "a", "b", "b"], 5)


def test_evaluate_reports_held_out_metrics_and_ablation() -> None:
    rows, labels, groups = _synthetic()
    report = evaluate(rows, labels, groups, folds=5)
    assert report.n == 80 and report.n_positive == 40 and report.n_groups == 40
    assert report.auc > 0.95  # pass rate separates the synthetic classes by construction
    assert report.spearman > 0.7
    assert 0.0 <= report.brier < 0.1
    assert sum(b.count for b in report.calibration) == 80
    assert "mutation_score" in report.dropped
    assert report.coefficients["test_pass_rate"] > 0
    # Dropping the informative signal costs AUC; dropping noise barely matters.
    assert report.ablation["test_pass_rate"] < report.auc - 0.2
    assert report.ablation["mypy_error_count"] > report.auc - 0.05


def test_evaluate_needs_both_classes() -> None:
    rows, _, groups = _synthetic(n_problems=10)
    with pytest.raises(ValueError, match="both"):
        evaluate(rows, [True] * len(rows), groups, folds=5)


# --- the deployed model (S6) --------------------------------------------------------------


def test_fitted_model_predicts_like_sklearn_and_survives_json() -> None:
    rows, labels, _ = _synthetic()
    model = fit_model(rows, labels)
    again = ScoreModel.model_validate_json(model.model_dump_json())
    assert again == model
    matrix, _, _ = feature_matrix(rows)
    x = np.asarray(matrix, dtype=float)
    reference = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(x, labels)
    expected = reference.predict_proba(x)[:, 1].tolist()
    for row, p in zip(rows, expected, strict=True):
        assert predict(again, row) == pytest.approx(p, abs=1e-9)


def test_missing_signal_with_an_indicator_is_scored() -> None:
    rows, labels, _ = _synthetic()
    rows[0] = _signals(None, semantics=None)  # pass rate and semantics missing at least once
    model = fit_model(rows, labels)
    assert "test_pass_rate_missing" in model.features
    score = predict(model, _signals(None))
    assert score is not None and 0.0 < score < 1.0


def test_missing_signal_never_missing_in_training_cannot_be_scored() -> None:
    rows, labels, _ = _synthetic()  # pass rate always present while fitting
    model = fit_model(rows, labels)
    assert predict(model, _signals(None)) is None
