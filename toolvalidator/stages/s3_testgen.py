"""S3 test generation: generator proposes tests, independent judge filters them.

S3 never rejects a tool: failing to generate tests says something about the
validator, not about the code. It always passes and records what it produced;
S4 then runs the accepted tests. LLM/infrastructure failures raise (CLAUDE.md rule 7),
they do not become a verdict.
"""

from collections.abc import Sequence

from pydantic import JsonValue

from toolvalidator.contracts import IOExample, Sandbox, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import ScadsClient
from toolvalidator.testgen.generator import DEFAULT_TEST_COUNT, generate_tests
from toolvalidator.testgen.judge import judge_suite

STAGE = "s3_testgen"
MAX_REPORTED_REJECTIONS = 5


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    client: ScadsClient,
    n: int = DEFAULT_TEST_COUNT,
    show_code: bool = True,
    examples: Sequence[IOExample] = (),
) -> StageResult:
    """Generate ``n`` candidate tests and keep the ones the judge accepts.

    ``show_code=False`` hides the tool from the generator too (an RQ3 arm).
    ``examples`` are dataset sample I/O; upstream requests carry none, so the caller
    supplies them when the dataset has them.
    """
    suite = generate_tests(
        client,
        record.request,
        code=artifact.code if show_code else None,
        n=n,
        examples=examples,
    )
    verdicts = judge_suite(client, record.request, suite.tests)
    accepted = [test for test, verdict in verdicts if verdict.valid]
    rejected = [(test, verdict) for test, verdict in verdicts if not verdict.valid]
    data: dict[str, JsonValue] = {
        "requested": n,
        "generated": len(suite.tests),
        "accepted": len(accepted),
        "saw_code": show_code,
        "tests": [{"input": test.input, "output": test.output} for test in accepted],
        "rejected": [
            {"input": test.input, "output": test.output, "reason": verdict.reason}
            for test, verdict in rejected[:MAX_REPORTED_REJECTIONS]
        ],
    }
    detail = f"{len(accepted)} of {len(suite.tests)} generated tests accepted by the judge"
    return record.add(StageResult(stage=STAGE, passed=True, detail=detail, data=data))
