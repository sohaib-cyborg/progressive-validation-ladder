"""The mutation prompt (S5 arm B): invent plausible buggy variants of a program.

The generator sees the code only, never the description, like ``explain_code``: the
mutants should be mistakes a programmer could make in *this* code, not a second attempt
at the task. Nothing here decides anything; ``mutation/arm_b_llm.py`` parses the reply
and drops unusable variants, and kill counting happens in the sandbox.
"""

from toolvalidator.prompts.spec import PromptSpec

INVENT_SYSTEM = """You write plausible buggy variants of a Python program, for mutation testing.

Each variant must be the WHOLE program with exactly one small, realistic mistake of the
kind a programmer really makes: an off-by-one loop bound or index, a wrong comparison
(< instead of <=), a wrong operator, the wrong variable, integer versus float division,
a missed edge case, a wrong constant, or a wrong output format. Each variant must:
- still be valid Python that reads its input the same way;
- behave differently from the original on at least some input;
- differ from every other variant;
- carry no comment that points at the mistake.
Do not fix, improve or reformat anything else.

Answer with JSON only:
{"mutants": [{"description": "<the mistake, one short line>",
              "code": "<the whole program with that mistake>"}]}"""


def render_invent(code: str, n: int) -> str:
    return "\n".join(
        [
            "Program source:",
            "```python",
            code.strip(),
            "```",
            "",
            f"Write {n} buggy variants of this program. Answer with JSON.",
        ]
    )


INVENT_MUTANTS_V1 = PromptSpec(
    id="invent_mutants",
    version="v1",
    role="generator",
    purpose="Invent plausible buggy variants of a tool's code (mutation arm B).",
    changelog="First version: code only, never the description; whole-program variants.",
    system=INVENT_SYSTEM,
    renderer=render_invent,
)
