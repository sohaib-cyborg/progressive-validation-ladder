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

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from toolvalidator.scoring.metrics import CalibrationBin, auc, calibration, spearman
from toolvalidator.scoring.signals import Signals

SIGNALS: tuple[str, ...] = tuple(Signals.model_fields)
MISSING = "_missing"

type Matrix = list[list[float]]
type Folds = list[tuple[list[int], list[int]]]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
        auc=auc(labels, scores),
        spearman=spearman([float(v) for v in labels], scores.tolist()),
        brier=float(brier_score_loss(labels, scores)),
        calibration=calibration(labels, scores, bins),
        coefficients={c: float(w) for c, w in zip(columns, regression.coef_[0], strict=True)},
        intercept=float(regression.intercept_[0]),
        ablation={
            name: auc(labels, _without(name, matrix, columns, labels, split)) for name in kept
        },
    )


class ScoreModel(_Frozen):
    """The deployed score (S6): standardise each feature, then a logistic regression.

    Stored as plain numbers so the pipeline can score a tool without scikit-learn state.
    """

    signals: list[str]
    features: list[str]  # columns, including ``<signal>_missing`` indicators
    means: list[float]
    scales: list[float]
    coefficients: list[float]
    intercept: float


def fit_model(
    rows: Sequence[Signals], labels: Sequence[bool], signals: Sequence[str] = SIGNALS
) -> ScoreModel:
    """The final fit on all rows, as the deployed model (metrics come from ``evaluate``)."""
    matrix, columns, _ = feature_matrix(rows, signals)
    if not columns:
        raise ValueError("no signal was observed; nothing to fit")
    fitted = _model().fit(np.asarray(matrix, dtype=float), np.asarray(labels, dtype=int))
    scaler: StandardScaler = fitted[0]
    regression: LogisticRegression = fitted[-1]
    return ScoreModel(
        signals=[name for name in signals if name in columns],
        features=columns,
        means=[float(v) for v in scaler.mean_],
        scales=[float(v) for v in scaler.scale_],
        coefficients=[float(v) for v in regression.coef_[0]],
        intercept=float(regression.intercept_[0]),
    )


def predict(model: ScoreModel, row: Signals) -> float | None:
    """P(correct) for one tool; None if a signal is missing that was never missing in fitting."""
    z = model.intercept
    for feature, mean, scale, weight in zip(
        model.features, model.means, model.scales, model.coefficients, strict=True
    ):
        if feature.endswith(MISSING):
            value = 1.0 if getattr(row, feature.removesuffix(MISSING)) is None else 0.0
        else:
            raw = getattr(row, feature)
            if raw is None and feature + MISSING not in model.features:
                return None  # the model has no way to represent this gap
            value = 0.0 if raw is None else float(raw)
        z += weight * (value - mean) / scale
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


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


def _without(
    name: str, matrix: Matrix, columns: list[str], labels: Sequence[bool], folds: Folds
) -> NDArray[np.float64]:
    keep = [i for i, c in enumerate(columns) if c not in (name, name + MISSING)]
    reduced = [[row[i] for i in keep] for row in matrix]
    return out_of_fold(reduced, labels, folds)


def _model() -> Pipeline:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
