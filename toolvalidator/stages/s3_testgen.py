"""S3 test generation: generator proposes tests, independent judge filters them.

S3 never rejects a tool: failing to generate tests says something about the
validator, not about the code. It always passes and records what it produced;
S4 then runs the accepted tests. LLM/infrastructure failures raise (CLAUDE.md rule 7),
they do not become a verdict.

A suite can be built once and recorded for several tools (``build_suite`` then
``run(..., suite=...)``): RQ3 generates one blind suite per RunBugRun entry and runs it
on both the buggy and the fixed program (docs/DECISIONS.md 2026-09-26).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from toolvalidator.contracts import (
    CapabilityRequest,
    IOExample,
    Sandbox,
    StageResult,
    ToolArtifact,
    ValidationRecord,
)
from toolvalidator.llm.scads_client import ScadsClient
from toolvalidator.prompts.testgen import DEFAULT_TEST_COUNT
from toolvalidator.testgen.generator import generate_tests
from toolvalidator.testgen.judge import judge_batch, judge_suite
from toolvalidator.testgen.schemas import GeneratedTest, JudgeVerdict

STAGE = "s3_testgen"
MAX_REPORTED_REJECTIONS = 5


@dataclass(frozen=True)
class JudgedSuite:
    """Generated tests with the judge's verdict on each."""

    requested: int
    saw_code: bool
    judged: list[tuple[GeneratedTest, JudgeVerdict]]

    @property
    def accepted(self) -> list[GeneratedTest]:
        return [test for test, verdict in self.judged if verdict.valid]


def build_suite(
    client: ScadsClient,
    request: CapabilityRequest,
    *,
    code: str | None,
    n: int = DEFAULT_TEST_COUNT,
    examples: Sequence[IOExample] = (),
    batch_judge: bool = False,
) -> JudgedSuite:
    """Generate ``n`` tests (``code=None`` = blind) and judge them, one call or one each."""
    suite = generate_tests(client, request, code=code, n=n, examples=examples)
    judge = judge_batch if batch_judge else judge_suite
    return JudgedSuite(
        requested=n, saw_code=code is not None, judged=judge(client, request, suite.tests)
    )


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    client: ScadsClient | None = None,
    n: int = DEFAULT_TEST_COUNT,
    show_code: bool = True,
    examples: Sequence[IOExample] = (),
    batch_judge: bool = False,
    suite: JudgedSuite | None = None,
) -> StageResult:
    """Record a judged suite: the given one, or one generated now for this tool.

    ``show_code=False`` hides the tool from the generator too (an RQ3 arm).
    ``examples`` are dataset sample I/O; upstream requests carry none, so the caller
    supplies them when the dataset has them.
    """
    if suite is None:
        if client is None:
            raise ValueError("S3 needs a client or a suite")
        code = artifact.code if show_code else None
        suite = build_suite(
            client, record.request, code=code, n=n, examples=examples, batch_judge=batch_judge
        )
    accepted = suite.accepted
    rejected = [(test, verdict) for test, verdict in suite.judged if not verdict.valid]
    data: dict[str, JsonValue] = {
        "requested": suite.requested,
        "generated": len(suite.judged),
        "accepted": len(accepted),
        "saw_code": suite.saw_code,
        "tests": [{"input": test.input, "output": test.output} for test in accepted],
        "rejected": [
            {"input": test.input, "output": test.output, "reason": verdict.reason}
            for test, verdict in rejected[:MAX_REPORTED_REJECTIONS]
        ],
    }
    detail = f"{len(accepted)} of {len(suite.judged)} generated tests accepted by the judge"
    return record.add(StageResult(stage=STAGE, passed=True, detail=detail, data=data))
