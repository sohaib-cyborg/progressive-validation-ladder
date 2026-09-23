"""Judge generated tests against the Capability Request (S3, second half).

The judge is a different model family from the generator and is **blind to the tool's
code**: it only decides whether a candidate test follows from the description
(docs/MEMORY.md). It judges tests, never tools, and never decides a verdict.

The prompt lives in ``toolvalidator/prompts/testgen.py``; the names below are kept for
callers and tests.
"""

from collections.abc import Sequence

from toolvalidator.contracts import CapabilityRequest
from toolvalidator.llm.scads_client import ScadsClient, parse_json_object
from toolvalidator.prompts.testgen import JUDGE_TEST_V1
from toolvalidator.testgen.schemas import GeneratedTest, JudgeVerdict

SPEC = JUDGE_TEST_V1
SYSTEM_PROMPT = SPEC.system


def build_user_prompt(request: CapabilityRequest, test: GeneratedTest) -> str:
    return SPEC.render(request=request, test=test)


def judge_test(
    client: ScadsClient, request: CapabilityRequest, test: GeneratedTest
) -> JudgeVerdict:
    result = client.complete("judge", system=SYSTEM_PROMPT, user=build_user_prompt(request, test))
    return JudgeVerdict.parse(parse_json_object(result.content))


def judge_suite(
    client: ScadsClient, request: CapabilityRequest, tests: Sequence[GeneratedTest]
) -> list[tuple[GeneratedTest, JudgeVerdict]]:
    """Judge every candidate. Callers keep the valid ones."""
    return [(test, judge_test(client, request, test)) for test in tests]
