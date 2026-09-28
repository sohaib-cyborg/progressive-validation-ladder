"""Tests for S5 mutation (toolvalidator/stages/s5_mutation.py)."""

from tests.conftest import ByCodeSandbox
from toolvalidator.contracts import IOExample, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.mutation import Mutant, MutantSet
from toolvalidator.stages import s5_mutation

TOOL = ToolArtifact(tool_id="t1", code="print(int(input()) + 1)")
TESTS = [IOExample(input="1", output="2"), IOExample(input="5", output="6")]


def _set(*codes: str, candidates: int | None = None, dropped: int = 0) -> MutantSet:
    mutants = [Mutant(operator="arithmetic", line=1, description=c, code=c) for c in codes]
    total = len(codes) + dropped if candidates is None else candidates
    return MutantSet(mutants=mutants, candidates=total, dropped=dropped)


def _with_s3_tests(record: ValidationRecord) -> ValidationRecord:
    cases = [{"input": t.input, "output": t.output} for t in TESTS]
    record.add(StageResult(stage="s3_testgen", passed=True, data={"tests": cases}))
    return record


def test_records_the_score_and_always_passes(record: ValidationRecord) -> None:
    sandbox = ByCodeSandbox(
        {TOOL.code: [True, True], "m1": [False, True], "m2": [True, True], "m3": [True, True]}
    )
    result = s5_mutation.run(
        TOOL, _with_s3_tests(record), sandbox, mutants=_set("m1", "m2", "m3", dropped=2), arm="A"
    )
    assert result.stage == "s5_mutation"
    assert result.passed  # measures the tests, never rejects the tool
    assert result.data["arm"] == "A"
    assert result.data["mutation_score"] == 1 / 3
    assert (result.data["killed"], result.data["total"], result.data["usable_tests"]) == (1, 3, 2)
    assert (result.data["candidates"], result.data["dropped"]) == (5, 2)
    assert result.data["tests"] == 2
    assert result.data["from_s3"] is True
    assert record.results[-1] == result


def test_explicit_tests_are_used_and_marked_as_not_from_s3(record: ValidationRecord) -> None:
    sandbox = ByCodeSandbox({TOOL.code: [True, True], "m1": [False, False]})
    result = s5_mutation.run(TOOL, record, sandbox, mutants=_set("m1"), arm="B", tests=TESTS)
    assert result.data["from_s3"] is False
    assert result.data["arm"] == "B"
    assert result.data["mutation_score"] == 1.0


def test_no_tests_passes_with_a_missing_score_and_runs_nothing(record: ValidationRecord) -> None:
    sandbox = ByCodeSandbox({})
    result = s5_mutation.run(TOOL, record, sandbox, mutants=_set("m1"), arm="A")
    assert result.passed
    assert result.data["mutation_score"] is None
    assert result.category == "no_tests"
    assert sandbox.codes == []


def test_no_mutants_passes_with_a_missing_score(record: ValidationRecord) -> None:
    sandbox = ByCodeSandbox({TOOL.code: [True, True]})
    result = s5_mutation.run(TOOL, _with_s3_tests(record), sandbox, mutants=_set(), arm="A")
    assert result.passed
    assert result.data["mutation_score"] is None
    assert result.category == "no_mutants"
