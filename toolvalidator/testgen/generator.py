"""Generate black-box tests from a Capability Request (S3, first half).

The generator may see the tool's code as an *interface* reference (what the program
reads and prints), but the description is the truth: expected outputs must follow
from the task, never from what the code happens to do (docs/MEMORY.md).

The prompt itself lives in ``toolvalidator/prompts/testgen.py`` so it is versioned and
documented; the names below are kept for callers and tests.
"""

from collections.abc import Sequence

from toolvalidator.contracts import CapabilityRequest, IOExample
from toolvalidator.llm.scads_client import ScadsClient, parse_json_object
from toolvalidator.prompts.testgen import DEFAULT_TEST_COUNT, GENERATE_TESTS_V1
from toolvalidator.testgen.schemas import GeneratedSuite

SPEC = GENERATE_TESTS_V1
SYSTEM_PROMPT = SPEC.system


def build_user_prompt(
    request: CapabilityRequest,
    code: str | None,
    n: int = DEFAULT_TEST_COUNT,
    examples: Sequence[IOExample] = (),
) -> str:
    return SPEC.render(request=request, code=code, n=n, examples=examples)


def generate_tests(
    client: ScadsClient,
    request: CapabilityRequest,
    *,
    code: str | None = None,
    n: int = DEFAULT_TEST_COUNT,
    examples: Sequence[IOExample] = (),
) -> GeneratedSuite:
    """Ask the generator for tests. Raises LLMError/LLMOutputError; never guesses."""
    result = client.complete(
        "generator", system=SPEC.system, user=build_user_prompt(request, code, n, examples)
    )
    return GeneratedSuite.parse(parse_json_object(result.content))
