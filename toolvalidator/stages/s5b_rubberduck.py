"""S5b rubber-duck: an LLM explains the code, a second LLM compares that to the request.

Execution checks outputs; this checks meaning. The explainer (generator model) sees the
code but not the description; the comparer (judge model, a different family) sees the
description and the explanation but not the code, and returns a per-requirement
checklist. This stage turns that checklist into a signal in plain Python:

    semantics_score = met / (met + violated)      # None when nothing was decided

S5b never rejects a tool (CLAUDE.md rule 5: an LLM never decides a verdict). Violated
requirements are recorded as the repair signal; S6 decides what the score is worth.
Unusable LLM output raises LLMOutputError, which is an infrastructure failure, not a
verdict.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from toolvalidator.contracts import (
    CapabilityRequest,
    Sandbox,
    StageResult,
    ToolArtifact,
    ValidationRecord,
)
from toolvalidator.llm.scads_client import LLMOutputError, ScadsClient, parse_json_object
from toolvalidator.llm.trace import trace_context
from toolvalidator.prompts.rubberduck import COMPARE_EXPLANATION_V1, EXPLAIN_CODE_V1
from toolvalidator.prompts.spec import PromptSpec

STAGE = "s5b_rubberduck"

type Status = Literal["met", "violated", "unknown"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")  # ignore: LLMs add extra keys

    @classmethod
    def parse(cls, payload: dict[str, JsonValue]) -> Self:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"unusable {cls.__name__}: {exc}") from exc


class Explanation(_Frozen):
    explanation: str = Field(min_length=1)


class RequirementCheck(_Frozen):
    requirement: str = Field(min_length=1)
    status: Status
    evidence: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _normalise(cls, value: JsonValue) -> JsonValue:
        return value.strip().lower() if isinstance(value, str) else value


class Comparison(_Frozen):
    requirements: list[RequirementCheck] = Field(min_length=1)

    def count(self, status: Status) -> int:
        return sum(1 for check in self.requirements if check.status == status)


def explain_code(client: ScadsClient, code: str) -> Explanation:
    content = _ask(client, EXPLAIN_CODE_V1, code=code)
    return Explanation.parse(parse_json_object(content))


def compare_explanation(
    client: ScadsClient, request: CapabilityRequest, explanation: str
) -> Comparison:
    content = _ask(client, COMPARE_EXPLANATION_V1, request=request, explanation=explanation)
    return Comparison.parse(parse_json_object(content))


def semantics_score(comparison: Comparison) -> float | None:
    """Share of decided requirements that are met; None if none were decided."""
    met, violated = comparison.count("met"), comparison.count("violated")
    return met / (met + violated) if met + violated else None


def run(
    artifact: ToolArtifact,
    record: ValidationRecord,
    sandbox: Sandbox,
    *,
    client: ScadsClient,
) -> StageResult:
    """Explain, compare, record the signal. Executes nothing and always passes."""
    explanation = explain_code(client, artifact.code).explanation
    comparison = compare_explanation(client, record.request, explanation)
    met, violated, unknown = (comparison.count(s) for s in ("met", "violated", "unknown"))
    data: dict[str, JsonValue] = {
        "semantics_score": semantics_score(comparison),
        "met": met,
        "violated": violated,
        "unknown": unknown,
        "explanation": explanation,
        "violations": [
            {"requirement": check.requirement, "evidence": check.evidence}
            for check in comparison.requirements
            if check.status == "violated"
        ],
        "prompts": [_label(EXPLAIN_CODE_V1), _label(COMPARE_EXPLANATION_V1)],
    }
    detail = f"{met} met, {violated} violated, {unknown} unknown of {len(comparison.requirements)}"
    return record.add(StageResult(stage=STAGE, passed=True, detail=detail, data=data))


def _ask(client: ScadsClient, prompt: PromptSpec, **params: object) -> str:
    with trace_context(prompt_id=prompt.id, prompt_version=prompt.version):
        result = client.complete(prompt.role, system=prompt.system, user=prompt.render(**params))
    return result.content


def _label(prompt: PromptSpec) -> str:
    return f"{prompt.id}@{prompt.version}"
