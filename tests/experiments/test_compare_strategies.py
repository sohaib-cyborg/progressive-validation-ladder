"""Tests for the strategy comparison (experiments/compare_strategies.py).

All rows here are synthetic and only exercise the arithmetic; none of it is a result.
"""

import json
import random
from pathlib import Path
from typing import Any

import pytest

from experiments.compare_strategies import (
    STRATEGIES,
    agreement,
    detection,
    llm_cost,
    main,
    mutation_means,
    refit,
    render_markdown,
)
from experiments.run_mutation_arms import ArmResult, MutationRow
from experiments.run_testgen_strategies import ArmOutcome, StrategyOutcome
from toolvalidator.llm.trace import LLMCall
from toolvalidator.mutation import Mutant
from toolvalidator.mutation.kill import SuiteScore
from toolvalidator.scoring.signals import Signals


def _rq3(
    entry: int,
    variant: str,
    failed: dict[str, bool],
    violation: bool | None,
    rate: float = 1.0,
    problem: str | None = None,
    mypy: int = 0,
) -> StrategyOutcome:
    arms = {
        arm: ArmOutcome(n_tests=3, pass_rate=0.5, category="wrong_output" if bad else None)
        for arm, bad in failed.items()
    }
    signals = Signals(
        bandit_findings=0,
        mypy_error_count=mypy,
        test_pass_rate=rate,
        tests_run=8,
        semantics_score=None,
        semantic_violation=violation,
        mutation_score=None,
    )
    return StrategyOutcome(
        entry_id=entry,
        problem_id=problem or f"p{entry}",
        split="valid",
        variant="fixed" if variant == "fixed" else "buggy",
        is_correct=variant == "fixed",
        bug_labels=[],
        gate_category=None,
        suite_generated=8,
        suite_accepted=8,
        arms=arms,
        semantics_score=None,
        semantic_violation=violation,
        signals=signals,
    )


def _score(killed: int, total: int, score: float | None) -> SuiteScore:
    return SuiteScore(killed=killed, total=total, usable_tests=1, score=score)


def _arm(passes: list[list[bool]], scores: dict[str, float | None], seconds: float) -> ArmResult:
    mutants = [
        Mutant(operator="x", line=1, description="d", code=f"m{i}") for i in range(len(passes))
    ]
    return ArmResult(
        mutants=mutants,
        candidates=len(passes),
        dropped=0,
        mutant_passes=passes,
        scores={
            s: _score(0, len(passes), v)
            for s, v in ({"examples": None, "generated": None, "judged": None} | scores).items()
        },
        sandbox_seconds=seconds,
    )


def _mut(
    entry: int,
    variant: str,
    tool: list[bool],
    a: ArmResult,
    b: ArmResult,
    problem: str | None = None,
) -> MutationRow:
    return MutationRow(
        entry_id=entry,
        problem_id=problem or f"p{entry}",
        variant="fixed" if variant == "fixed" else "buggy",
        is_correct=variant == "fixed",
        bug_labels=[],
        suites={"examples": [0], "generated": [1, 2], "judged": [1]},
        tool_passes=tool,
        tool_stable=True,
        rq3_mismatches=[],
        arms={"A": a, "B": b},
        seconds=1.0,
    )


# --- detection ------------------------------------------------------------------------


def test_detection_counts_every_strategy_on_the_same_tools() -> None:
    no = {"examples": False, "generated": False, "judged": False}
    rows = [
        _rq3(1, "buggy", {"examples": False, "generated": True, "judged": True}, violation=None),
        _rq3(2, "buggy", no, violation=True),
        _rq3(1, "fixed", {"examples": False, "generated": True, "judged": False}, violation=False),
        _rq3(2, "fixed", no, violation=None),
    ]
    table = detection(rows)
    assert set(table) == set(STRATEGIES)
    assert table["examples"] == {"bugs_caught": 0, "buggy": 2, "correct_rejected": 0, "fixed": 2}
    assert table["generated"]["bugs_caught"] == 1 and table["generated"]["correct_rejected"] == 1
    assert table["judged"]["correct_rejected"] == 0
    assert table["rubber_duck"]["bugs_caught"] == 1
    assert table["rubber_duck"]["missing_buggy"] == 1 and table["rubber_duck"]["missing_fixed"] == 1
    assert table["judged_or_rubber_duck"]["bugs_caught"] == 2


# --- mutation score per strategy --------------------------------------------------------


def test_mutation_means_per_strategy_with_rubber_duck_not_applicable() -> None:
    full = {"examples": 0.5, "generated": 1.0, "judged": 0.75}
    rows = [
        _mut(1, "fixed", [True] * 3, _arm([], full, 1.0), _arm([], full, 1.0)),
        _mut(2, "fixed", [True] * 3, _arm([], full | {"examples": None}, 1.0), _arm([], full, 1.0)),
    ]
    means = mutation_means(rows)
    assert means["examples"]["A"]["fixed"] == {"mean": 0.5, "n": 1, "missing": 1}
    assert means["judged"]["B"]["fixed"]["mean"] == 0.75
    assert means["rubber_duck"]["A"] is None
    assert means["judged_or_rubber_duck"] == means["judged"]  # rubber-duck adds no tests


# --- cost ----------------------------------------------------------------------------------


def _call(entry: int, prompt: str, tokens: tuple[int, int], latency: float) -> LLMCall:
    return LLMCall(
        tool_id=str(entry), prompt_id=prompt, ts=0.0, role="generator", model_requested="m",
        model_returned="m", system_sha256="", user_sha256="", system="s", user="u",
        content="c", reasoning=None, prompt_tokens=tokens[0], completion_tokens=tokens[1],
        latency_s=latency, ok=True, error=None,
    )  # fmt: skip


def test_llm_cost_is_the_mean_per_entry_of_the_strategy_s_prompts() -> None:
    calls = [
        _call(1, "generate_tests", (100, 50), 2.0),
        _call(1, "judge_batch", (10, 10), 1.0),
        _call(1, "explain_code", (5, 5), 1.0),
        _call(1, "compare_explanation", (5, 5), 1.0),
        _call(2, "generate_tests", (100, 50), 4.0),
        _call(9, "generate_tests", (999, 999), 99.0),  # not a chosen entry
        _call(1, "invent_mutants", (7, 3), 0.5),
    ]
    cost = llm_cost(calls, [1, 2])
    assert cost["examples"] == {"tokens": 0.0, "seconds": 0.0}
    assert cost["generated"] == {"tokens": 150.0, "seconds": 3.0}
    assert cost["judged"] == {"tokens": 160.0, "seconds": 3.5}
    assert cost["rubber_duck"] == {"tokens": 10.0, "seconds": 1.0}
    assert cost["judged_or_rubber_duck"] == {"tokens": 170.0, "seconds": 4.5}
    assert cost["arm_b"] == {"tokens": 5.0, "seconds": 0.25}


# --- Arm A vs Arm B -------------------------------------------------------------------------


def test_per_test_agreement_counts_and_kappa() -> None:
    # tool passes tests 0 and 1, fails 2 (so test 2 can kill nothing)
    a = _arm([[False, True, False], [True, True, True]], {}, 1.0)  # A killed by test 0 only
    b = _arm([[False, False, True]], {}, 1.0)  # B killed by tests 0 and 1
    report = agreement([_mut(1, "fixed", [True, True, False], a, b)])
    tests = report["per_test"]
    assert (tests["both"], tests["a_only"], tests["b_only"], tests["neither"]) == (1, 0, 1, 0)
    assert tests["agreement"] == 0.5
    assert tests["kappa"] == 0.0


def test_score_correlation_per_variant() -> None:
    rows = [
        _mut(
            i, "fixed", [True] * 3, _arm([], {"generated": s}, 1.0), _arm([], {"generated": s}, 1.0)
        )
        for i, s in enumerate([0.1, 0.5, 0.9])
    ]
    report = agreement(rows)
    assert report["spearman_generated"]["fixed"] == pytest.approx(1.0)
    assert report["spearman_generated"]["buggy"] is None  # no buggy tools: undefined, not 0


# --- RQ4 refit --------------------------------------------------------------------------------


def _refit_rows(n: int = 30) -> tuple[list[StrategyOutcome], list[MutationRow]]:
    rng = random.Random(4)
    rq3, mut = [], []
    for entry in range(n):
        for variant in ("fixed", "buggy"):
            good = variant == "fixed"
            rate = rng.uniform(0.6, 1.0) if good else rng.uniform(0.0, 0.8)
            no = {"examples": False, "generated": False, "judged": False}
            violation = rng.random() < 0.3
            rq3.append(_rq3(entry, variant, no, violation, rate=rate, mypy=rng.randint(0, 2)))
            score = rng.uniform(0.5, 1.0) if good else rng.uniform(0.0, 0.6)
            arm = _arm([], {"judged": score}, 1.0)
            mut.append(_mut(entry, variant, [True], arm, arm))
    return rq3, mut


def test_refit_puts_the_arm_s_judged_score_into_the_signals() -> None:
    rq3, mut = _refit_rows()
    report = refit(rq3, mut, arm="A")
    sets = report["signal_sets"]
    assert isinstance(sets, dict)
    assert {"all", "all_plus_mutation", "mutation_only"} <= set(sets)
    assert report["n_tools"] == 60


# --- output -----------------------------------------------------------------------------------


def test_markdown_has_one_row_per_strategy() -> None:
    rq3, mut = _refit_rows(10)
    report: dict[str, Any] = {
        "n_entries": 10,
        "detection": detection(rq3),
        "mutation": mutation_means(mut),
        "cost": llm_cost([], [r.entry_id for r in rq3]),
        "arm_cost": {"A": {"sandbox_seconds": 1.0}, "B": {"sandbox_seconds": 2.0}},
    }
    text = render_markdown(report)
    for label in ("statement samples", "generated", "judged", "rubber-duck alone",
                  "judged + rubber-duck"):  # fmt: skip
        assert f"| {label} |" in text
    assert "n/a" in text


def test_main_writes_json_and_markdown(tmp_path: Path) -> None:
    rq3, mut = _refit_rows(30)
    (tmp_path / "rq3").mkdir()
    (tmp_path / "rq3" / "testgen_eval.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in rq3), encoding="utf-8"
    )
    (tmp_path / "mutation").mkdir()
    (tmp_path / "mutation" / "mutation_eval.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in mut), encoding="utf-8"
    )
    out = tmp_path / "comparison"
    args = ["--rq3", str(tmp_path / "rq3"), "--mutation", str(tmp_path / "mutation")]
    assert main([*args, "--out", str(out)]) == 0
    report = json.loads((out / "strategies.json").read_text(encoding="utf-8"))
    assert report["n_entries"] == 30
    assert "| statement samples |" in (out / "strategies.md").read_text(encoding="utf-8")
