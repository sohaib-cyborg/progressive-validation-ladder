"""Tests for score metrics (toolvalidator/scoring/metrics.py)."""

import pytest

from toolvalidator.scoring.metrics import spearman


def test_spearman_handles_ties() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # scipy.stats.spearmanr([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) = 0.4472135955
    assert spearman([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.4472135955)
