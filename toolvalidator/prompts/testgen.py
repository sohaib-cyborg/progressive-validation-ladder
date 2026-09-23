"""The test-generation prompts: propose test cases, then judge one.

Moved here verbatim from ``testgen/generator.py`` and ``testgen/judge.py`` so every
prompt carries a version and appears in ``docs/PROMPTS.md``. Those modules now
delegate to these specs.
"""

from collections.abc import Sequence

from toolvalidator.contracts import CapabilityRequest, IOExample, ParamSpec
from toolvalidator.prompts.spec import PromptSpec
from toolvalidator.testgen.schemas import GeneratedTest

DEFAULT_TEST_COUNT = 8

GENERATE_SYSTEM = """You write black-box tests for command-line programs.

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

JUDGE_SYSTEM = """You review proposed tests for a command-line program.

You are given a task description and ONE candidate test: an exact stdin input and
the expected stdout the test author claims is correct. Decide whether that expected
output is what a correct program would print for that input, according to the
description alone. You never see the program's code.

Answer with JSON only:
{"valid": true|false, "reason": "<one short sentence>"}

Say false if the expected output is wrong, if the input is malformed for this task,
or if the description does not determine the answer."""


def render_generate(
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


def _param(spec: ParamSpec) -> str:
    optional = "" if spec.required else " (optional)"
    description = f" — {spec.description}" if spec.description else ""
    return f"{spec.name}: {spec.type}{optional}{description}"


def render_judge(request: CapabilityRequest, test: GeneratedTest) -> str:
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


GENERATE_TESTS_V1 = PromptSpec(
    id="generate_tests",
    version="v1",
    role="generator",
    purpose="Propose black-box test cases for a requested tool, from the request alone.",
    changelog="First version: the description is the specification; code is an interface hint.",
    system=GENERATE_SYSTEM,
    renderer=render_generate,
)

JUDGE_TEST_V1 = PromptSpec(
    id="judge_test",
    version="v1",
    role="judge",
    purpose="Decide whether one candidate test's expected output follows from the request.",
    changelog="First version: one test per call; the judge never sees the tool's code.",
    system=JUDGE_SYSTEM,
    renderer=render_judge,
)
