"""Compare typed tool outputs (S4 function-call mode).

Upstream Capability Requests declare typed inputs and outputs
(docs/capability_request.md §2), so a tool built from one returns a value, not text.
This compares those values structurally, with the same float tolerance the text
comparison uses.

Text comparison for stdin/stdout tools lives in ``stages/harness.py``.
# TODO(scope): the two comparison rules could share one module once both are settled.
"""

import math
from typing import Any


def values_match(actual: Any, expected: Any, *, rel_tol: float, abs_tol: float) -> bool:
    """Structural equality, with numbers compared to a tolerance.

    Booleans are not numbers (``True != 1``), and a string never equals a number:
    the declared type is part of the contract. Unlike the text rule, an integer
    expectation accepts an integral float, because here the value is compared, not
    its printed form.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if expected is None or actual is None:
        return actual is expected
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return False
        return all(
            values_match(actual[key], value, rel_tol=rel_tol, abs_tol=abs_tol)
            for key, value in expected.items()
        )
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        return all(
            values_match(got, want, rel_tol=rel_tol, abs_tol=abs_tol)
            for got, want in zip(actual, expected, strict=True)
        )
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        if math.isnan(actual) or math.isnan(expected):
            return False
        return math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)
    if isinstance(expected, str) and isinstance(actual, str):
        return actual == expected
    return False
