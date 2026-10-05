"""How well a score predicts correctness: AUC, Spearman's rho, calibration bins.

Pure functions of labels and scores; the model that produces the scores is in
``scoring/model.py``.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict
from sklearn.metrics import roc_auc_score


class CalibrationBin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    fraction_correct: float | None


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


def auc(labels: Sequence[bool], scores: NDArray[np.float64]) -> float:
    return float(roc_auc_score(labels, scores))


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
