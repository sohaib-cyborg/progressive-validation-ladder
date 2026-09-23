"""Shared pipeline types, the spine of the validator (CLAUDE.md §4).

Depends on nothing internal. Change shapes deliberately and ask first.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class _Frozen(BaseModel):
    """Immutable model that rejects unknown fields (catches typos in JSON inputs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class IOExample(_Frozen):
    """One test case for a tool: an input and the output a correct tool produces.

    Values are arbitrary JSON so the same type covers stdin/stdout tools
    (``input="100\\n"``) and typed tools (``input={"celsius": 100}``). Test cases
    are *not* part of the Capability Request: upstream requests carry no examples.
    """

    input: JsonValue
    output: JsonValue


class ParamSpec(_Frozen):
    """One input or output field of a requested tool."""

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    description: str = ""
    required: bool = True


class CapabilityRequest(_Frozen):
    """A structured spec for a missing tool that would close a capability gap.

    This is the upstream (Project B) schema, documented in
    ``docs/capability_request.md`` §2, and it loads that JSON unchanged. Keeping it
    identical is the point: we validate the tools synthesized from these requests.
    """

    name: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    description: str
    inputs: list[ParamSpec] = Field(default_factory=list)
    outputs: list[ParamSpec] = Field(default_factory=list)
    rationale: str | None = None


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


class ExecResult(_Frozen):
    """Outcome of running one script in the sandbox."""

    stdout: str
    stderr: str
    exit_code: int
    duration_s: float = Field(ge=0)
    timed_out: bool = False


@runtime_checkable
class Sandbox(Protocol):
    """The only way stages may execute code. Implemented by ``sandbox/exec.py``.

    ``timeout_s=None`` means the sandbox's configured default.
    """

    def run(
        self, script: str, *, stdin: str = "", timeout_s: float | None = None
    ) -> ExecResult: ...


type Stage = Callable[[ToolArtifact, ValidationRecord, Sandbox], StageResult]
"""Every stage has this shape (CLAUDE.md rule 6)."""
