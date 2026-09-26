"""Every prompt in the project, versioned, in one registry.

Why a registry: the report quotes prompts and RQ3 compares them, so a prompt needs an
identity (``generate_tests@v1``) that travels with every result and every traced call.
A new version is a **new object**; a released version is never edited, or the
comparison would be a lie.

``docs/PROMPTS.md`` is generated from here (``python -m toolvalidator.cli prompts
--write``) and a test fails if the two drift, so the reviewed text is the text that runs.
"""

from toolvalidator.prompts.rubberduck import (
    COMPARE_EXPLANATION_V1,
    COMPARE_EXPLANATION_V2,
    EXPLAIN_CODE_V1,
)
from toolvalidator.prompts.spec import PromptSpec, register, render_catalogue
from toolvalidator.prompts.testgen import GENERATE_TESTS_V1, JUDGE_BATCH_V1, JUDGE_TEST_V1

__all__ = ["REGISTRY", "PromptSpec", "markdown_catalogue", "spec"]

REGISTRY = register(
    GENERATE_TESTS_V1,
    JUDGE_TEST_V1,
    JUDGE_BATCH_V1,
    EXPLAIN_CODE_V1,
    COMPARE_EXPLANATION_V1,
    COMPARE_EXPLANATION_V2,
)


def spec(prompt_id: str, version: str) -> PromptSpec:
    try:
        return REGISTRY[(prompt_id, version)]
    except KeyError:
        raise KeyError(f"no prompt {prompt_id}@{version} in the registry") from None


def markdown_catalogue() -> str:
    return render_catalogue(REGISTRY)
