"""Types for generated tests and judge verdicts (S3).

LLM output is untrusted (CLAUDE.md §7): ``parse_*`` accept only well-formed
payloads and raise ``LLMOutputError`` otherwise. Numbers are coerced to strings
because RunBugRun tools read stdin and write stdout.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from toolvalidator.llm.scads_client import LLMOutputError


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")  # ignore: LLMs add extra keys


class GeneratedTest(_Frozen):
    """One stdin/stdout case proposed by the generator."""

    input: str
    output: str
    rationale: str = ""

    @field_validator("input", "output", "rationale", mode="before")
    @classmethod
    def _as_text(cls, value: JsonValue) -> JsonValue:
        return str(value) if isinstance(value, int | float) else value


class GeneratedSuite(_Frozen):
    tests: list[GeneratedTest] = Field(default_factory=list)

    @classmethod
    def parse(cls, payload: dict[str, JsonValue]) -> Self:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"unusable generated tests: {exc}") from exc


class JudgeVerdict(_Frozen):
    """The judge's opinion on one candidate test. It never sees the tool's code."""

    valid: bool
    reason: str = ""

    @classmethod
    def parse(cls, payload: dict[str, JsonValue]) -> Self:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"unusable judge verdict: {exc}") from exc


class IndexedVerdict(JudgeVerdict):
    index: int


class BatchVerdicts(_Frozen):
    """The batched judge's reply: exactly one verdict per numbered test."""

    verdicts: list[IndexedVerdict]

    @classmethod
    def parse(cls, payload: dict[str, JsonValue]) -> Self:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"unusable batch verdicts: {exc}") from exc

    def in_order(self, n: int) -> list[JudgeVerdict]:
        """Verdicts for tests 0..n-1. Missing, repeated or unknown indices are unusable."""
        indices = sorted(v.index for v in self.verdicts)
        if indices != list(range(n)):
            raise LLMOutputError(
                f"batch verdict index set {indices} does not cover 0..{n - 1} exactly once"
            )
        by_index = {v.index: v for v in self.verdicts}
        return [JudgeVerdict(valid=by_index[i].valid, reason=by_index[i].reason) for i in range(n)]
