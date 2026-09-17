"""Shared pipeline types, the spine of the validator (CLAUDE.md §4).

Depends on nothing internal. Change shapes deliberately and ask first.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class _Frozen(BaseModel):
    """Immutable model that rejects unknown fields (catches typos in JSON inputs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class IOExample(_Frozen):
    """One example from the Capability Request.

    Values are arbitrary JSON so the same type covers function-call style
    (e.g. ``input=100``) and stdin/stdout style (e.g. ``input="100\\n"``).
    """

    input: JsonValue
    output: JsonValue


class CapabilityRequest(_Frozen):
    """The task a tool must fulfil: what it is called, what it does, examples."""

    name: str = Field(min_length=1)
    description: str
    examples: list[IOExample] = Field(default_factory=list)


class ToolArtifact(_Frozen):
    """The code under test plus synthesis metadata (e.g. confidence, retries)."""

    tool_id: str = Field(min_length=1)
    code: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class StageResult(_Frozen):
    """What every stage returns. ``category`` names the failure kind, if any."""

    stage: str = Field(min_length=1)
    passed: bool
    category: str | None = None
    detail: str = ""
    data: dict[str, JsonValue] = Field(default_factory=dict)


class FailureReport(_Frozen):
    """A repair signal: where the tool failed and why."""

    stage: str = Field(min_length=1)
    category: str = Field(min_length=1)
    message: str
    line: int | None = Field(default=None, ge=1)


class ValidationRecord(BaseModel):
    """Mutable accumulator for one validation run. All pipeline state lives here."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    request: CapabilityRequest
    results: list[StageResult] = Field(default_factory=list)
    failures: list[FailureReport] = Field(default_factory=list)
    verdict: Verdict | None = None

    def add(self, result: StageResult) -> StageResult:
        """Append a stage result and return it (the stage contract, CLAUDE.md rule 6)."""
        self.results.append(result)
        return result
