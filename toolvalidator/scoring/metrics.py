"""How well a score predicts correctness, and how two test strategies compare.

AUC, Spearman's rho and calibration bins judge a score; the model that produces the
scores is in ``scoring/model.py``. Exact McNemar, a paired bootstrap interval and Holm's
correction compare two strategies measured on the same entries (paired by entry).
Pure functions; nothing here reads results.
"""

import math
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


class McNemar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    only_a: int
    only_b: int
    p_value: float
    """Two-sided exact binomial test on the discordant pairs."""


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> McNemar:
    """Paired yes/no outcomes of two strategies on the same entries (e.g. bug caught)."""
    if len(a) != len(b):
        raise ValueError("mcnemar needs paired outcomes of equal length")
    only_a = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    only_b = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    n = only_a + only_b
    tail = sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1))
    return McNemar(only_a=only_a, only_b=only_b, p_value=min(1.0, 2 * tail / 2**n))


class BootstrapCI(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mean_diff: float
    lower: float
    upper: float
    n: int
    resamples: int


def bootstrap_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    resamples: int = 10_000,
    seed: int = 20260917,
    level: float = 0.95,
) -> BootstrapCI:
    """Percentile interval for mean(a - b), resampling entries (the pairs) with replacement."""
    if len(a) != len(b):
        raise ValueError("bootstrap needs paired values of equal length")
    if not a:
        raise ValueError("bootstrap of an empty sample")
    diffs = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    picks = np.random.default_rng(seed).integers(0, len(diffs), size=(resamples, len(diffs)))
    means = diffs[picks].mean(axis=1)
    tail = (1 - level) / 2 * 100
    lower, upper = np.percentile(means, [tail, 100 - tail])
    return BootstrapCI(
        mean_diff=float(diffs.mean()),
        lower=float(lower),
        upper=float(upper),
        n=len(diffs),
        resamples=resamples,
    )


def holm(p_values: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order."""
    m = len(p_values)
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(sorted(range(m), key=lambda i: p_values[i])):
        running = max(running, min(1.0, (m - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


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
