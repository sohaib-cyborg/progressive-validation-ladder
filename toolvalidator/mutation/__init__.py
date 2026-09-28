"""Mutation testing (S5): mutants from two arms, and kill counting.

Arm A (``arm_a_mutmut``) applies mutmut's operator classes; Arm B (``arm_b_llm``) asks an
LLM for plausible buggy variants. Both produce a ``MutantSet``, so ``kill`` treats them alike.
Making mutants never executes code; running them happens only in the sandbox.
"""

from pydantic import BaseModel, ConfigDict

__all__ = ["Mutant", "MutantSet"]


class Mutant(BaseModel):
    """One changed copy of a tool's code."""

    model_config = ConfigDict(frozen=True)

    operator: str  # the rule that made it (Arm A) or the LLM's label (Arm B)
    line: int | None  # where the change is, when known
    description: str
    code: str


class MutantSet(BaseModel):
    """The mutants kept for one tool, and how many candidates were dropped."""

    model_config = ConfigDict(frozen=True)

    mutants: list[Mutant]
    candidates: int  # places a rule applied (Arm A) or variants the LLM returned (Arm B)
    dropped: int  # unparsable, identical to the original, or a duplicate
