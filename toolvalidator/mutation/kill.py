"""Kill counting: run a tool and its mutants against one suite, then score sub-suites.

The tool and every mutant run once against the whole suite, one sandbox call per program
(``s4_execute.run_cases``), giving a pass/fail matrix. A test **kills** a mutant when the
tool passes it and the mutant fails it; a mutant is killed by a suite when any of the
suite's tests kills it. So one run of the union suite scores every strategy's sub-suite:

    score = mutants killed / mutants      # None when there are no mutants or no tests

A program whose whole call times out counts as failing every test. The score is raw: it
is not adjusted for mutants that behave exactly like the tool (equivalent mutants), which
every strategy faces equally.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from toolvalidator.contracts import CapabilityRequest, IOExample, Sandbox
from toolvalidator.mutation import Mutant
from toolvalidator.stages.s4_execute import (
    DEFAULT_ABS_TOL,
    DEFAULT_REL_TOL,
    CasesRun,
    HarnessError,
    run_cases,
)

__all__ = ["KillMatrix", "SuiteScore", "run_matrix", "suite_score"]


class KillMatrix(BaseModel):
    """Per-test pass/fail for the tool and for each mutant, in suite order."""

    model_config = ConfigDict(frozen=True)

    tool: list[bool]
    mutants: list[list[bool]]
    seconds: float  # sandbox time for all programs


class SuiteScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    killed: int
    total: int  # mutants
    usable_tests: int  # tests of this suite that the tool passes (only these can kill)
    score: float | None


def run_matrix(
    code: str,
    mutants: Sequence[Mutant],
    request: CapabilityRequest,
    tests: Sequence[IOExample],
    sandbox: Sandbox,
    *,
    timeout_s: float | None = None,
    rel_tol: float = DEFAULT_REL_TOL,
    abs_tol: float = DEFAULT_ABS_TOL,
) -> KillMatrix:
    """Run the tool and each mutant against ``tests`` in the sandbox (S4's comparison rules)."""
    if not tests:
        return KillMatrix(tool=[], mutants=[[] for _ in mutants], seconds=0.0)
    seconds = 0.0
    rows: list[list[bool]] = []
    for program in [code, *(m.code for m in mutants)]:
        run = run_cases(
            program, request, tests, sandbox, timeout_s=timeout_s, rel_tol=rel_tol, abs_tol=abs_tol
        )
        passes, spent = _passes(run, len(tests))
        rows.append(passes)
        seconds += spent
    return KillMatrix(tool=rows[0], mutants=rows[1:], seconds=seconds)


def suite_score(matrix: KillMatrix, indices: Sequence[int]) -> SuiteScore:
    """How many mutants the tests at ``indices`` kill."""
    usable = [i for i in indices if matrix.tool[i]]
    killed = sum(1 for row in matrix.mutants if any(not row[i] for i in usable))
    total = len(matrix.mutants)
    score = killed / total if total and indices else None
    return SuiteScore(killed=killed, total=total, usable_tests=len(usable), score=score)


def _passes(run: CasesRun, n_tests: int) -> tuple[list[bool], float]:
    if run.timed_out:
        return [False] * n_tests, run.duration_s
    by_index = {outcome.index: outcome.passed for outcome in run.outcomes}
    if sorted(by_index) != list(range(n_tests)):
        raise HarnessError(f"harness reported {len(by_index)} outcomes for {n_tests} tests")
    return [by_index[i] for i in range(n_tests)], run.duration_s
