"""S5 mutation: how strong are the tests? Measured by the mutants they kill.

The mutants come from the caller (``mutation/arm_a_mutmut.py`` or ``arm_b_llm.py``), so
this stage is the same for both arms. It runs the tool and every mutant against the
tests in the sandbox (``mutation/kill.py``) and records

    mutation_score = mutants killed / mutants      # None with no tests or no mutants

S5 never rejects a tool: it measures the tests, not the tool. Tests default to what S3
accepted, as in S4; ``from_s3`` records whether they did, because a score measured on
the dataset's own tests would leak the label into the reliability score
(``scoring/signals.py`` ignores it).
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import JsonValue

from toolvalidator.contracts import IOExample, Sandbox, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.mutation import MutantSet
from toolvalidator.mutation.kill import run_matrix, suite_score
from toolvalidator.stages.s4_execute import tests_from_record

STAGE = "s5_mutation"

type Arm = Literal["A", "B"]


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    mutants: MutantSet,
    arm: Arm,
    tests: Sequence[IOExample] | None = None,
    timeout_s: float | None = None,
) -> StageResult:
    cases = list(tests) if tests is not None else tests_from_record(record)
    data: dict[str, JsonValue] = {
        "arm": arm,
        "from_s3": tests is None,
        "tests": len(cases),
        "candidates": mutants.candidates,
        "dropped": mutants.dropped,
    }
    if not cases or not mutants.mutants:
        category = "no_tests" if not cases else "no_mutants"
        data |= {"mutation_score": None, "killed": 0, "total": len(mutants.mutants)}
        data |= {"usable_tests": 0, "seconds": 0.0}
        return record.add(
            StageResult(stage=STAGE, passed=True, category=category, detail=category, data=data)
        )
    matrix = run_matrix(
        artifact.code, mutants.mutants, record.request, cases, sandbox, timeout_s=timeout_s
    )
    score = suite_score(matrix, range(len(cases)))
    data |= {
        "mutation_score": score.score,
        "killed": score.killed,
        "total": score.total,
        "usable_tests": score.usable_tests,
        "seconds": matrix.seconds,
    }
    detail = f"arm {arm}: {score.killed} of {score.total} mutants killed by {len(cases)} tests"
    return record.add(StageResult(stage=STAGE, passed=True, detail=detail, data=data))
