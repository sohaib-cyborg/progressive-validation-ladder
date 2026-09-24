"""The reliability score: a logistic regression fit from data (PLAN.md §5.3, RQ4).

Signals → P(tool is correct). Everything reported is **out of fold**: folds are grouped
by ``problem_id`` so a problem's buggy and fixed tools never sit on both sides of a
split, and no number here is measured on data the model was fit on. The coefficients
come from a final fit on all rows and are reported as the learned weights only.

Missing values: a signal that is sometimes missing becomes ``value or 0`` plus a
``<name>_missing`` indicator column; a signal that is never observed carries no
information and is dropped *and reported*. Both rules are fixed in advance, not learned,
so they cannot leak across folds.

Hard safety gates (S1 parse, S2 dangerous calls) stay outside the regression: the caller
fits only on tools that passed them (MEMORY.md, locked decision 5).
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from toolvalidator.scoring.signals import Signals

SIGNALS: tuple[str, ...] = tuple(Signals.model_fields)
MISSING = "_missing"

type Matrix = list[list[float]]
type Folds = list[tuple[list[int], list[int]]]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CalibrationBin(_Frozen):
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    fraction_correct: float | None


class FitReport(_Frozen):
    n: int
    n_positive: int
    n_groups: int
    folds: int
    features: list[str]
    dropped: list[str]
    auc: float
    spearman: float
    brier: float
    calibration: list[CalibrationBin]
    coefficients: dict[str, float]
    intercept: float
    ablation: dict[str, float]
    """Out-of-fold AUC with that signal (and its missing indicator) removed."""


def evaluate(
    rows: Sequence[Signals],
    labels: Sequence[bool],
    groups: Sequence[str],
    *,
    folds: int = 5,
    bins: int = 10,
    signals: Sequence[str] = SIGNALS,
) -> FitReport:
    if not len(rows) == len(labels) == len(groups):
        raise ValueError("rows, labels and groups differ in length")
    if len(set(labels)) < 2:
        raise ValueError("labels need both correct and incorrect tools")
    matrix, columns, dropped = feature_matrix(rows, signals)
    if not columns:
        raise ValueError("no signal was observed; nothing to fit")
    split = group_folds(groups, folds)
    scores = out_of_fold(matrix, labels, split)
    final = _model().fit(np.asarray(matrix, dtype=float), np.asarray(labels, dtype=int))
    regression: LogisticRegression = final[-1]
    kept = [name for name in signals if name not in dropped]
    return FitReport(
        n=len(rows),
        n_positive=sum(labels),
        n_groups=len(set(groups)),
        folds=folds,
        features=columns,
        dropped=dropped,
        auc=_auc(labels, scores),
        spearman=spearman([float(v) for v in labels], scores.tolist()),
        brier=float(brier_score_loss(labels, scores)),
        calibration=calibration(labels, scores, bins),
        coefficients={c: float(w) for c, w in zip(columns, regression.coef_[0], strict=True)},
        intercept=float(regression.intercept_[0]),
        ablation={
            name: _auc(labels, _without(name, matrix, columns, labels, split)) for name in kept
        },
    )


def feature_matrix(
    rows: Sequence[Signals], signals: Sequence[str] = SIGNALS
) -> tuple[Matrix, list[str], list[str]]:
    """A rows-by-columns float matrix, the column names, and the never-observed signals."""
    columns: list[str] = []
    values_by_column: list[list[float]] = []
    dropped: list[str] = []
    for name in signals:
        values = [getattr(row, name) for row in rows]
        observed = sum(v is not None for v in values)
        if observed == 0:
            dropped.append(name)
            continue
        columns.append(name)
        values_by_column.append([0.0 if v is None else float(v) for v in values])
        if observed < len(values):
            columns.append(name + MISSING)
            values_by_column.append([1.0 if v is None else 0.0 for v in values])
    matrix = [list(row) for row in zip(*values_by_column, strict=True)]
    return (matrix or [[] for _ in rows]), columns, dropped


def group_folds(groups: Sequence[str], folds: int) -> Folds:
    """(train, test) index lists; a group never appears on both sides."""
    n_groups = len(set(groups))
    if n_groups < folds:
        raise ValueError(f"{n_groups} problems cannot fill {folds} folds")
    placeholder = np.zeros((len(groups), 1))
    return [
        (train.tolist(), test.tolist())
        for train, test in GroupKFold(n_splits=folds).split(placeholder, groups=list(groups))
    ]


def out_of_fold(matrix: Matrix, labels: Sequence[bool], folds: Folds) -> NDArray[np.float64]:
    """Each row's P(correct) from a model that never saw that row's problem."""
    x = np.asarray(matrix, dtype=float)
    y = np.asarray(labels, dtype=int)
    scores = np.full(len(y), float(y.mean()))  # no columns → every row gets the base rate
    if x.shape[1] == 0:
        return scores
    for train, test in folds:
        if len(set(y[train].tolist())) < 2:
            raise ValueError("a training fold does not contain both classes")
        scores[test] = _model().fit(x[train], y[train]).predict_proba(x[test])[:, 1]
    return scores


def calibration(
    labels: Sequence[bool], scores: NDArray[np.float64], bins: int
) -> list[CalibrationBin]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    y = np.asarray(labels, dtype=float)
    result: list[CalibrationBin] = []
    for k in range(bins):
        lower, upper = float(edges[k]), float(edges[k + 1])
        inside = (scores >= lower) & ((scores < upper) if k < bins - 1 else (scores <= upper))
        count = int(inside.sum())
        result.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_predicted=float(scores[inside].mean()) if count else None,
                fraction_correct=float(y[inside].mean()) if count else None,
            )
        )
    return result


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman's rho with average ranks for ties (matches scipy.stats.spearmanr)."""
    ranks_a, ranks_b = _ranks(a), _ranks(b)
    if ranks_a.std() == 0 or ranks_b.std() == 0:
        raise ValueError("spearman is undefined for a constant input")
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


def _ranks(values: Sequence[float]) -> NDArray[np.float64]:
    data = np.asarray(values, dtype=float)
    order = np.argsort(data, kind="mergesort")
    ranks = np.empty(len(data))
    start = 0
    while start < len(data):
        end = start
        while end + 1 < len(data) and data[order[end + 1]] == data[order[start]]:
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def _without(
    name: str, matrix: Matrix, columns: list[str], labels: Sequence[bool], folds: Folds
) -> NDArray[np.float64]:
    keep = [i for i, c in enumerate(columns) if c not in (name, name + MISSING)]
    reduced = [[row[i] for i in keep] for row in matrix]
    return out_of_fold(reduced, labels, folds)


def _auc(labels: Sequence[bool], scores: NDArray[np.float64]) -> float:
    return float(roc_auc_score(labels, scores))


def _model() -> Pipeline:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
