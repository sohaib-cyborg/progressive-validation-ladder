"""The rubber-duck prompts (S5b): explain the code, then compare that to the request.

The two calls are deliberately blind to each other's input. The explainer never sees
the description, so its account of the code cannot echo the specification; the
comparer never sees the code, so it can only judge what the explanation says.
Neither decides anything: S5b turns the comparison into a signal in plain Python.
"""

from toolvalidator.contracts import CapabilityRequest
from toolvalidator.prompts.spec import PromptSpec
from toolvalidator.prompts.testgen import describe_param

EXPLAIN_SYSTEM = """You read a Python program and explain, in plain language, what it actually does.

You are NOT told what the program is supposed to do. Describe its real behaviour only,
as a careful reviewer would after tracing the code: what input it reads and in what
format, what it computes, what it outputs and in what format, and what it does on edge
cases (empty input, zero, ties, very large values). Be exact about details that change
the result: comparison operators and loop bounds, integer versus float division,
rounding and output formatting, hard-coded constants. Do not guess the intent and do
not fix the code.

Answer with JSON only:
{"explanation": "<the program's behaviour, a few short sentences>"}"""

COMPARE_SYSTEM = """You check whether a program does what a task requires, without seeing it.

You are given a task description, which is the specification, and an explanation of
what the program actually does, written by someone who read its code. Break the
specification into its concrete requirements (input format, what must be computed,
output format, stated constraints and edge cases). For each requirement, decide from
the explanation alone:
- "met": the explanation shows the program does this;
- "violated": the explanation shows the program does something different;
- "unknown": the explanation does not say.

Answer with JSON only:
{"requirements": [{"requirement": "<one requirement, short>",
                   "status": "met" | "violated" | "unknown",
                   "evidence": "<the part of the explanation that decides it>"}]}

Say "violated" only when the explanation clearly contradicts the requirement. Do not
judge style or speed unless the specification asks for it. No prose outside the JSON."""


def render_explain(code: str) -> str:
    return "\n".join(
        [
            "Program source:",
            "```python",
            code.strip(),
            "```",
            "",
            "Explain what this program does. Answer with JSON.",
        ]
    )


def render_compare(request: CapabilityRequest, explanation: str) -> str:
    parts = [
        f"Task name: {request.name}",
        f"Capability: {request.capability}",
        "",
        "Task description (the specification):",
        request.description.strip(),
    ]
    if request.inputs:
        parts += ["", "Declared inputs:", *(f"- {describe_param(p)}" for p in request.inputs)]
    if request.outputs:
        parts += ["", "Declared outputs:", *(f"- {describe_param(p)}" for p in request.outputs)]
    parts += [
        "",
        "What the program actually does (explained from its code):",
        explanation.strip(),
        "",
        "Check each requirement of the specification. Answer with JSON.",
    ]
    return "\n".join(parts)


EXPLAIN_CODE_V1 = PromptSpec(
    id="explain_code",
    version="v1",
    role="generator",
    purpose="Explain what a tool's code actually does, without being told what it should do.",
    changelog="First version: code only, never the description, so it cannot echo the spec.",
    system=EXPLAIN_SYSTEM,
    renderer=render_explain,
)

COMPARE_EXPLANATION_V1 = PromptSpec(
    id="compare_explanation",
    version="v1",
    role="judge",
    purpose="Check each requirement of the request against the explanation of the code.",
    changelog="First version: per-requirement met/violated/unknown; never sees the code.",
    system=COMPARE_SYSTEM,
    renderer=render_compare,
)

# v2 (tuned on the RQ3 dev set, 2026-09-26): 15 of 92 v1 comparisons ran past the
# completion cap. Re-sent with v2, 6 of those 15 completed, and 8 of 8 comparisons that
# already worked kept the same "any violation" answer. Same input, same output schema.
COMPARE_SYSTEM_V2 = COMPARE_SYSTEM.replace(
    'Say "violated" only when the explanation clearly contradicts the requirement.',
    "List at most 6 requirements: the ones that decide whether the output is correct.\n"
    "Do NOT solve the task yourself, work through the samples, or re-derive the answer:\n"
    "decide each requirement by reading the explanation, in a sentence or two of thought.\n"
    'Say "violated" only when the explanation clearly contradicts the requirement.',
)

COMPARE_EXPLANATION_V2 = PromptSpec(
    id="compare_explanation",
    version="v2",
    role="judge",
    purpose="Check each requirement of the request against the explanation of the code.",
    changelog="v1 plus: at most 6 requirements, and do not solve the task (runaway reasoning).",
    system=COMPARE_SYSTEM_V2,
    renderer=render_compare,
)
