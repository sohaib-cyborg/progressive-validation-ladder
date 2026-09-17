"""Judge generated tests against the Capability Request (S3, second half).

The judge is a different model family from the generator and is **blind to the tool's
code**: it only decides whether a candidate test follows from the description
(docs/MEMORY.md). It judges tests, never tools, and never decides a verdict.
"""

from collections.abc import Sequence

from toolvalidator.contracts import CapabilityRequest
from toolvalidator.llm.scads_client import ScadsClient, parse_json_object
from toolvalidator.testgen.schemas import GeneratedTest, JudgeVerdict

SYSTEM_PROMPT = """You review proposed tests for a command-line program.

You are given a task description and ONE candidate test: an exact stdin input and
the expected stdout the test author claims is correct. Decide whether that expected
output is what a correct program would print for that input, according to the
description alone. You never see the program's code.

Answer with JSON only:
{"valid": true|false, "reason": "<one short sentence>"}

Say false if the expected output is wrong, if the input is malformed for this task,
or if the description does not determine the answer."""


def build_user_prompt(request: CapabilityRequest, test: GeneratedTest) -> str:
    return "\n".join(
        [
            f"Task name: {request.name}",
            "",
            "Task description:",
            request.description.strip(),
            "",
            "Candidate test:",
            f"input: {test.input!r}",
            f"expected output: {test.output!r}",
            "",
            "Is the expected output correct? Answer with JSON.",
        ]
    )


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
