"""Tests for Arm A operator mutants (toolvalidator/mutation/arm_a_mutmut.py)."""

import ast

import pytest

from toolvalidator.mutation.arm_a_mutmut import DEFAULT_CAP, mutate


def _codes(source: str) -> set[str]:
    return {m.code.strip() for m in mutate(source, cap=100).mutants}


def _same(a: str, b: str) -> bool:
    return ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))


# --- one rule at a time ------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = a < b", "x = a <= b"),
        ("x = a <= b", "x = a < b"),
        ("x = a > b", "x = a >= b"),
        ("x = a >= b", "x = a > b"),
        ("x = a == b", "x = a != b"),
        ("x = a != b", "x = a == b"),
        ("x = a in b", "x = a not in b"),
        ("x = a is b", "x = a is not b"),
    ],
)
def test_comparison_swaps(source: str, expected: str) -> None:
    assert expected in _codes(source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = a + b", "x = a - b"),
        ("x = a - b", "x = a + b"),
        ("x = a * b", "x = a / b"),
        ("x = a / b", "x = a * b"),
        ("x = a // b", "x = a / b"),
        ("x = a % b", "x = a / b"),
        ("x = a ** b", "x = a * b"),
        ("x += a", "x -= a"),
    ],
)
def test_arithmetic_swaps(source: str, expected: str) -> None:
    assert expected in _codes(source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = 5", "x = 6"),
        ("x = 0.5", "x = 1.5"),
        ("x = True", "x = False"),
        ("x = False", "x = True"),
        ("x = a and b", "x = a or b"),
        ("x = a or b", "x = a and b"),
        ("x = not a", "x = a"),
        ("x = -a", "x = a"),
        ("x = 'yes'", "x = 'XXyesXX'"),
    ],
)
def test_literal_and_logic_rules(source: str, expected: str) -> None:
    assert expected in _codes(source)


def test_break_and_continue_swap() -> None:
    codes = _codes("for i in a:\n    break")
    assert any(_same(c, "for i in a:\n    continue") for c in codes)
    codes = _codes("for i in a:\n    continue")
    assert any(_same(c, "for i in a:\n    break") for c in codes)


def test_each_comparison_in_a_chain_is_its_own_mutant() -> None:
    codes = _codes("x = a < b < c")
    assert "x = a <= b < c" in codes
    assert "x = a < b <= c" in codes


# --- what is left alone ------------------------------------------------------------


def test_docstrings_and_fstring_text_are_not_mutated() -> None:
    source = '"""Doc."""\nprint(f"total: {n}")'
    assert mutate(source, cap=100).mutants == []


def test_code_without_any_site_gives_no_mutants() -> None:
    result = mutate("print(x)")
    assert result.mutants == []
    assert result.candidates == 0


def test_unparsable_code_raises() -> None:
    with pytest.raises(SyntaxError):
        mutate("def (:")


# --- properties over a realistic program -------------------------------------------

PROGRAM = """\
n, k = map(int, input().split())
a = list(map(int, input().split()))
total = 0
for i in range(n):
    if a[i] % 2 == 0 and a[i] > k:
        total += a[i] * 2
    elif a[i] < 0:
        continue
    else:
        total -= 1
if n > 100 or k == 1:
    total = total * 3 + 7
print("Yes" if total >= 10 else "No")
"""


def test_every_mutant_parses_and_differs_from_the_original() -> None:
    result = mutate(PROGRAM, cap=100)
    assert result.mutants
    for m in result.mutants:
        assert not _same(m.code, PROGRAM)
    assert len({ast.dump(ast.parse(m.code)) for m in result.mutants}) == len(result.mutants)


def test_cap_limits_the_number_of_mutants() -> None:
    result = mutate(PROGRAM)
    assert result.candidates > DEFAULT_CAP
    assert len(result.mutants) == DEFAULT_CAP
    assert len(mutate(PROGRAM, cap=3).mutants) == 3


def test_same_seed_same_mutants_other_seed_other_sample() -> None:
    first = mutate(PROGRAM, cap=5, seed=1)
    assert first == mutate(PROGRAM, cap=5, seed=1)
    assert first.mutants != mutate(PROGRAM, cap=5, seed=2).mutants


def test_mutants_record_rule_line_and_description() -> None:
    [m] = [m for m in mutate("x = 1\ny = a < b", cap=100).mutants if m.operator == "comparison"]
    assert m.line == 2
    assert m.description == "line 2: < -> <="
