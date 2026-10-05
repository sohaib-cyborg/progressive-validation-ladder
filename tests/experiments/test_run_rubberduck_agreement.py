"""Tests for the rubber-duck agreement runner (experiments/run_rubberduck_agreement.py).

Synthetic rows only; none of it is a result.
"""

import json
from pathlib import Path
from typing import Any

from data.loaders.runbugrun import RunBugRunEntry
from experiments.run_rubberduck_agreement import (
    AgreementRow,
    DuckRun,
    choose_entries,
    first_run_explanations,
    rerun_tool,
    summarize,
)
from experiments.run_testgen_strategies import StrategyOutcome
from toolvalidator.contracts import CapabilityRequest, IOExample
from toolvalidator.llm.scads_client import LLMResult
from toolvalidator.llm.trace import LLMCall
from toolvalidator.prompts.rubberduck import render_explain

REQUEST = CapabilityRequest(name="p1", capability="p1", description="Read n, print n+1.")


def _entry(entry_id: int = 7) -> RunBugRunEntry:
    return RunBugRunEntry(
        entry_id=entry_id, split="valid", problem_id="p1", request=REQUEST,
        buggy_code="print(int(input()) + 2)", fixed_code="print(int(input()) + 1)",
        tests=[IOExample(input="1", output="2")], examples=[], bug_labels=[],
    )  # fmt: skip


class _Client:
    """Explainer answers ``explanation``; comparer answers the given statuses (or junk)."""

    def __init__(self, explanation: str, statuses: list[str] | None) -> None:
        self.explanation = explanation
        self.statuses = statuses

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        if role == "generator":
            content = json.dumps({"explanation": self.explanation})
        elif self.statuses is None:
            content = "no json"
        else:
            checks = [{"requirement": f"r{i}", "status": s} for i, s in enumerate(self.statuses)]
            content = json.dumps({"requirements": checks})
        return LLMResult(model="m", content=content, reasoning=None, prompt_tokens=1,
                         completion_tokens=1, latency_s=0.0)  # fmt: skip


def _rq3(variant: str, violation: bool | None, score: float | None) -> StrategyOutcome:
    return StrategyOutcome.model_validate(
        {"entry_id": 7, "problem_id": "p1", "split": "valid", "variant": variant,
         "is_correct": variant == "fixed", "bug_labels": [], "gate_category": None,
         "suite_generated": 8, "suite_accepted": 8, "arms": {}, "semantics_score": score,
         "semantic_violation": violation, "signals": None,
         "semantic_error": None if violation is not None else "LLMOutputError: truncated"}
    )  # fmt: skip


def test_rerun_records_both_runs_and_whether_the_explanation_repeated() -> None:
    client: Any = _Client("Adds one.", ["met", "violated"])
    first = {render_explain("print(int(input()) + 1)"): "Adds one."}
    row = rerun_tool(_entry(), "fixed", _rq3("fixed", False, 1.0), client, first)
    assert row.first == DuckRun(violation=False, score=1.0, error=None)
    assert row.second == DuckRun(violation=True, score=0.5, error=None)
    assert row.explanation_same is True


def test_an_unusable_rerun_is_missing_not_a_verdict() -> None:
    client: Any = _Client("Adds two.", None)
    row = rerun_tool(_entry(), "buggy", _rq3("buggy", True, 0.0), client, {})
    assert row.second.violation is None and row.second.error is not None
    assert row.explanation_same is None  # first explanation not found in the trace


def _call(user: str, content: str, prompt: str = "explain_code", ok: bool = True) -> LLMCall:
    return LLMCall(
        tool_id="7", prompt_id=prompt, ts=0.0, role="generator", model_requested="m",
        model_returned="m", system_sha256="", user_sha256="", system="s", user=user,
        content=content, reasoning=None, prompt_tokens=1, completion_tokens=1, latency_s=0.0,
        ok=ok, error=None,
    )  # fmt: skip


def test_first_run_explanations_are_keyed_by_the_exact_prompt() -> None:
    calls = [
        _call("u1", json.dumps({"explanation": "A"})),
        _call("u2", "garbled"),
        _call("u3", json.dumps({"explanation": "C"}), prompt="compare_explanation"),
        _call("u4", json.dumps({"explanation": "D"}), ok=False),
    ]
    assert first_run_explanations(calls) == {"u1": "A"}


def test_entries_are_a_seeded_sample() -> None:
    ids = list(range(100))
    chosen = choose_entries(ids, 25, seed=1)
    assert len(chosen) == 25 and chosen == choose_entries(ids, 25, seed=1)
    assert chosen != choose_entries(ids, 25, seed=2)


def _row(variant: str, first: DuckRun, second: DuckRun, same: bool | None) -> AgreementRow:
    return AgreementRow(entry_id=7, problem_id="p1", variant=variant, first=first,
                        second=second, explanation_same=same)  # fmt: skip


def test_summary_counts_agreement_kappa_and_missing() -> None:
    yes, no = (
        DuckRun(violation=True, score=0.2, error=None),
        DuckRun(violation=False, score=1.0, error=None),
    )
    gone = DuckRun(violation=None, score=None, error="x")
    rows = [
        _row("buggy", yes, yes, True),
        _row("buggy", yes, no, False),
        _row("fixed", no, no, True),
        _row("fixed", no, gone, None),
    ]
    summary = summarize(rows)
    assert summary["n_tools"] == 4
    assert summary["both_present"] == 3
    assert summary["missing"] == {"first": 0, "second": 1}
    verdict = summary["verdict"]
    assert isinstance(verdict, dict)
    assert (verdict["both"], verdict["a_only"], verdict["b_only"], verdict["neither"]) == (
        1,
        1,
        0,
        1,
    )
    assert verdict["agreement"] == 2 / 3
    assert summary["explanation_same"] == {"same": 2, "different": 1, "unknown": 1}


def test_rows_round_trip(tmp_path: Path) -> None:
    row = _row("fixed", DuckRun(violation=False, score=1.0, error=None),
               DuckRun(violation=False, score=1.0, error=None), True)  # fmt: skip
    assert AgreementRow.model_validate_json(row.model_dump_json()) == row
