"""Arm B: LLM-invented mutants, plausible buggy variants of a tool's code.

One generator call (``invent_mutants@v1``) per tool; the model sees the code only. Its
reply is untrusted: a candidate is dropped, and counted, when it is not an object with a
``code`` string, does not parse, has the same syntax tree as the original (a comment or
formatting change) or as an earlier candidate, or comes after ``n`` mutants were kept.
A reply with no usable JSON raises ``LLMOutputError``: that is an infrastructure failure,
not "no mutants". This module never executes code.
"""

import ast

from pydantic import JsonValue

from toolvalidator.llm.scads_client import LLMOutputError, ScadsClient, parse_json_object
from toolvalidator.llm.trace import trace_context
from toolvalidator.mutation import Mutant, MutantSet
from toolvalidator.prompts.mutation import INVENT_MUTANTS_V1

__all__ = ["DEFAULT_N", "PROMPT", "invent"]

DEFAULT_N = 5
PROMPT = INVENT_MUTANTS_V1


def invent(client: ScadsClient, code: str, *, n: int = DEFAULT_N) -> MutantSet:
    """Up to ``n`` LLM-invented mutants of ``code``. Raises on unparsable code or reply."""
    seen = {ast.dump(ast.parse(code))}
    candidates = _ask(client, code, n)
    kept: list[Mutant] = []
    for candidate in candidates:
        if len(kept) == n:
            break
        mutant = _usable(candidate, code, seen)
        if mutant is not None:
            kept.append(mutant)
    return MutantSet(mutants=kept, candidates=len(candidates), dropped=len(candidates) - len(kept))


def _ask(client: ScadsClient, code: str, n: int) -> list[JsonValue]:
    with trace_context(prompt_id=PROMPT.id, prompt_version=PROMPT.version):
        result = client.complete(
            PROMPT.role, system=PROMPT.system, user=PROMPT.render(code=code, n=n)
        )
    candidates = parse_json_object(result.content).get("mutants")
    if not isinstance(candidates, list):
        raise LLMOutputError(f"no 'mutants' list in LLM output: {result.content[:200]!r}")
    return candidates


def _usable(candidate: JsonValue, original: str, seen: set[str]) -> Mutant | None:
    """The candidate as a Mutant, or None; adds its tree to ``seen`` when kept."""
    if not isinstance(candidate, dict) or not isinstance(candidate.get("code"), str):
        return None
    mutated = str(candidate["code"])
    try:
        dump = ast.dump(ast.parse(mutated))
    except (SyntaxError, ValueError, RecursionError):
        return None
    if dump in seen:
        return None
    seen.add(dump)
    description = candidate.get("description")
    return Mutant(
        operator="llm",
        line=_first_changed_line(original, mutated),
        description=description if isinstance(description, str) else "",
        code=mutated,
    )


def _first_changed_line(original: str, mutated: str) -> int | None:
    """1-based number of the first line that differs (trailing spaces ignored)."""
    before = [line.rstrip() for line in original.splitlines()]
    after = [line.rstrip() for line in mutated.splitlines()]
    for number, (old, new) in enumerate(zip(before, after, strict=False), start=1):
        if old != new:
            return number
    return min(len(before), len(after)) + 1 if len(before) != len(after) else None
