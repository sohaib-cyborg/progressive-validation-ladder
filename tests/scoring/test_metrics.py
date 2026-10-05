"""Tests for score metrics (toolvalidator/scoring/metrics.py)."""

import pytest

from toolvalidator.scoring.metrics import bootstrap_mean_diff_ci, holm, mcnemar_exact, spearman


def test_spearman_handles_ties() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # scipy.stats.spearmanr([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) = 0.4472135955
    assert spearman([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.4472135955)


def test_mcnemar_counts_discordant_pairs_and_gives_the_exact_binomial_p() -> None:
    # 10 entries only A catches, 2 only B catches, 5 both, 3 neither.
    a = [True] * 10 + [False] * 2 + [True] * 5 + [False] * 3
    b = [False] * 10 + [True] * 2 + [True] * 5 + [False] * 3
    result = mcnemar_exact(a, b)
    assert (result.only_a, result.only_b) == (10, 2)
    # two-sided exact: 2 * (C(12,0) + C(12,1) + C(12,2)) / 2**12 = 2 * 79 / 4096
    # (scipy.stats.binomtest(2, 12).pvalue = 0.0385742)
    assert result.p_value == pytest.approx(2 * 79 / 4096)


def test_mcnemar_without_discordant_pairs_has_p_one() -> None:
    assert mcnemar_exact([True, False], [True, False]).p_value == 1.0


def test_mcnemar_p_never_exceeds_one() -> None:
    assert mcnemar_exact([True, False], [False, True]).p_value == 1.0


def test_mcnemar_rejects_unpaired_input() -> None:
    with pytest.raises(ValueError, match="paired"):
        mcnemar_exact([True], [True, False])


def test_bootstrap_ci_is_seeded_and_brackets_the_mean_difference() -> None:
    a = [0.9, 0.8, 0.95, 0.7, 0.85, 0.9, 0.6, 0.75]
    b = [0.7, 0.8, 0.80, 0.5, 0.85, 0.6, 0.6, 0.70]
    first = bootstrap_mean_diff_ci(a, b, resamples=2000, seed=7)
    again = bootstrap_mean_diff_ci(a, b, resamples=2000, seed=7)
    assert first == again
    assert first.mean_diff == pytest.approx(sum(a) / 8 - sum(b) / 8)
    assert first.lower <= first.mean_diff <= first.upper
    assert first.lower > 0  # A is never below B, so the whole interval is positive
    assert (first.n, first.resamples) == (8, 2000)


def test_bootstrap_ci_of_identical_inputs_is_zero_width() -> None:
    result = bootstrap_mean_diff_ci([0.5, 0.7], [0.5, 0.7], resamples=100, seed=1)
    assert (result.mean_diff, result.lower, result.upper) == (0.0, 0.0, 0.0)


def test_bootstrap_ci_rejects_empty_or_unpaired_input() -> None:
    with pytest.raises(ValueError, match="paired"):
        bootstrap_mean_diff_ci([0.1], [0.1, 0.2])
    with pytest.raises(ValueError, match="empty"):
        bootstrap_mean_diff_ci([], [])


def test_holm_adjusts_in_step_down_order_and_keeps_input_order() -> None:
    # sorted 0.01, 0.03, 0.04 -> 3*0.01=0.03, 2*0.03=0.06, max(0.06, 1*0.04)=0.06
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_caps_at_one_and_handles_no_tests() -> None:
    assert holm([0.6, 0.9]) == [1.0, 1.0]
    assert holm([]) == []
