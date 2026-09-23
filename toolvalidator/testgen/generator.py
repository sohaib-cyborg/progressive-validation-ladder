"""Generate black-box tests from a Capability Request (S3, first half).

The generator may see the tool's code as an *interface* reference (what the program
reads and prints), but the description is the truth: expected outputs must follow
from the task, never from what the code happens to do (docs/MEMORY.md).
"""

from collections.abc import Sequence

from toolvalidator.contracts import CapabilityRequest, IOExample, ParamSpec
from toolvalidator.llm.scads_client import ScadsClient, parse_json_object
from toolvalidator.testgen.schemas import GeneratedSuite

DEFAULT_TEST_COUNT = 8

SYSTEM_PROMPT = """You write black-box tests for command-line programs.

The program reads from standard input and writes to standard output.
You are given a task description, optional examples, and optionally the program's
source code. The DESCRIPTION is the specification. If the code contradicts it, the
code is wrong: derive every expected output from the description alone.

Answer with JSON only, in this exact shape:
{"tests": [{"input": "<exact stdin>", "output": "<exact expected stdout>",
            "rationale": "<why this case matters, one short sentence>"}]}

Rules:
- "input" and "output" are strings holding the exact bytes, newlines included.
- Cover normal cases and edge cases (smallest input, boundaries, ties).
- Only include a case whose expected output you are certain of.
- No prose outside the JSON."""


def build_user_prompt(
    request: CapabilityRequest,
    code: str | None,
    n: int = DEFAULT_TEST_COUNT,
    examples: Sequence[IOExample] = (),
) -> str:
    """Render the request (upstream schema) plus any dataset examples into a prompt.

    ``examples`` are passed in rather than read from the request: upstream Capability
    Requests carry no examples (docs/capability_request.md §2).
    """
    parts = [
        f"Tool name: {request.name}",
        f"Capability: {request.capability}",
        "",
        "What the tool must do:",
        request.description.strip(),
    ]
    if request.inputs:
        parts += ["", "Declared inputs:", *(f"- {_param(p)}" for p in request.inputs)]
    if request.outputs:
        parts += ["", "Declared outputs:", *(f"- {_param(p)}" for p in request.outputs)]
    if request.rationale:
        parts += ["", f"Why the tool is needed: {request.rationale.strip()}"]
    if examples:
        parts += ["", "Examples from the task statement:"]
        parts += [f"- input: {ex.input!r}\n  output: {ex.output!r}" for ex in examples]
    if code is not None:
        parts += [
            "",
            "Program source (interface reference only, may be wrong):",
            "```python",
            code.strip(),
            "```",
        ]
    parts += ["", f"Write {n} test cases as JSON."]
    return "\n".join(parts)


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
        "generator", system=SYSTEM_PROMPT, user=build_user_prompt(request, code, n, examples)
    )
    return GeneratedSuite.parse(parse_json_object(result.content))


def _param(spec: ParamSpec) -> str:
    optional = "" if spec.required else " (optional)"
    description = f" — {spec.description}" if spec.description else ""
    return f"{spec.name}: {spec.type}{optional}{description}"
