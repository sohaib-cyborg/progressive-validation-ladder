"""Tests for typed-output comparison (toolvalidator/stages/compare.py)."""

from typing import Any

import pytest

from toolvalidator.stages.compare import values_match

TOL: dict[str, float] = {"rel_tol": 1e-6, "abs_tol": 1e-6}


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ({"fahrenheit": 212}, {"fahrenheit": 212}),
        ({"a": 1, "b": "x"}, {"b": "x", "a": 1}),  # key order is irrelevant
        ({"t": 12.566370614359172}, {"t": 12.5663706144}),  # rounded expectation
        ({"n": 1326.0}, {"n": 1326}),  # typed int answer, float carrier
        ([1, 2, 3], [1, 2, 3]),
        ({"xs": [1.0000001, 2.0]}, {"xs": [1.0, 2.0]}),
        ("sunny", "sunny"),
        (None, None),
        ({"nested": {"deep": [{"k": 0.1}]}}, {"nested": {"deep": [{"k": 0.1000000001}]}}),
    ],
)
def test_matching_values(actual: Any, expected: Any) -> None:
    assert values_match(actual, expected, **TOL)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ({"fahrenheit": 212}, {"fahrenheit": 213}),
        ({"a": 1}, {"a": 1, "b": 2}),  # missing key
        ({"a": 1, "b": 2}, {"a": 1}),  # extra key
        ({"t": 12.6}, {"t": 12.5663706144}),
        ([1, 2], [1, 2, 3]),
        ("212", 212),  # a string is not a number
        (212, "212"),
        (True, 1),  # booleans are not numbers here
        ({"c": None}, {"c": 0}),
        ({"n": 1326.5}, {"n": 1326}),
    ],
)
def test_mismatching_values(actual: Any, expected: Any) -> None:
    assert not values_match(actual, expected, **TOL)
