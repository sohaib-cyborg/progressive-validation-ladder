"""Every test strategy side by side, on the same tools (RQ3 + mutation, 100 eval entries).

    python -m experiments.compare_strategies --out results/comparison

Joins the RQ3 rows and the mutation rows (``run_mutation_arms.py``) on the entries the
mutation run covered, and writes ``strategies.json`` + ``strategies.md``: one row per
strategy with the same columns — bugs caught, correct tools rejected, mutation score per
arm, LLM tokens and seconds per entry — plus Arm A vs Arm B agreement and the RQ4 refit
with the mutation score as a signal. Missing values stay missing and are counted.
Test-execution time per strategy was not recorded by RQ3, so only LLM time is reported.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from experiments.fit_reliability_score import MUTATION_SETS, SIGNAL_SETS, fit_rows
from experiments.run_mutation_arms import MutationRow
from experiments.run_testgen_strategies import StrategyOutcome
from toolvalidator.llm.trace import LLMCall, merge_traces
from toolvalidator.scoring.metrics import spearman

STRATEGIES = ("examples", "generated", "judged", "rubber_duck", "judged_or_rubber_duck")
LABELS = {
    "examples": "statement samples",
    "generated": "generated",
    "judged": "judged",
    "rubber_duck": "rubber-duck alone",
    "judged_or_rubber_duck": "judged + rubber-duck",
}
PROMPTS: dict[str, tuple[str, ...]] = {
    "examples": (),
    "generated": ("generate_tests",),
    "judged": ("generate_tests", "judge_batch"),
    "rubber_duck": ("explain_code", "compare_explanation"),
    "judged_or_rubber_duck": (
        "generate_tests",
        "judge_batch",
        "explain_code",
        "compare_explanation",
    ),
    "arm_b": ("invent_mutants",),
}
TEST_SUITE = {"examples": "examples", "generated": "generated", "judged": "judged",
              "judged_or_rubber_duck": "judged"}  # fmt: skip


def detection(rows: Sequence[StrategyOutcome]) -> dict[str, dict[str, int]]:
    """Per strategy: buggy tools flagged and fixed tools flagged, on the same tools."""
    buggy = [r for r in rows if not r.is_correct and r.gate_category is None]
    fixed = [r for r in rows if r.is_correct and r.gate_category is None]
    table: dict[str, dict[str, int]] = {}
    for strategy in STRATEGIES:
        table[strategy] = {
            "bugs_caught": sum(_flagged(r, strategy) for r in buggy),
            "buggy": len(buggy),
            "correct_rejected": sum(_flagged(r, strategy) for r in fixed),
            "fixed": len(fixed),
        }
    table["rubber_duck"] |= {
        "missing_buggy": sum(1 for r in buggy if r.semantic_violation is None),
        "missing_fixed": sum(1 for r in fixed if r.semantic_violation is None),
    }
    return table


def _flagged(row: StrategyOutcome, strategy: str) -> bool:
    duck = row.semantic_violation is True  # a missing verdict flags nothing
    if strategy == "rubber_duck":
        return duck
    if strategy == "judged_or_rubber_duck":
        return row.arms["judged"].failed or duck
    return row.arms[strategy].failed


def mutation_means(rows: Sequence[MutationRow]) -> dict[str, Any]:
    """Mean mutation score per strategy, arm and variant; rubber-duck has no tests (None)."""
    means: dict[str, Any] = {}
    for strategy in STRATEGIES:
        suite = TEST_SUITE.get(strategy)
        means[strategy] = {
            arm: None if suite is None else {
                variant: _mean([r.arms[arm].scores[suite].score for r in rows
                                if r.variant == variant])
                for variant in ("fixed", "buggy")
            }
            for arm in ("A", "B")
        }  # fmt: skip
    return means


def _mean(values: Sequence[float | None]) -> dict[str, JsonValue]:
    present = [v for v in values if v is not None]
    mean = sum(present) / len(present) if present else None
    return {"mean": mean, "n": len(present), "missing": len(values) - len(present)}


def llm_cost(calls: Sequence[LLMCall], entry_ids: Sequence[int]) -> dict[str, dict[str, float]]:
    """Mean LLM tokens (prompt + completion) and seconds per entry, per strategy."""
    chosen = {str(e) for e in entry_ids}
    mine = [c for c in calls if c.tool_id in chosen]
    cost: dict[str, dict[str, float]] = {}
    for strategy, prompts in PROMPTS.items():
        used = [c for c in mine if c.prompt_id in prompts]
        tokens = sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in used)
        seconds = sum(c.latency_s for c in used)
        cost[strategy] = {"tokens": tokens / len(chosen), "seconds": seconds / len(chosen)}
    return cost


def agreement(rows: Sequence[MutationRow]) -> dict[str, Any]:
    """Do the two arms rank tools alike, and do they call the same tests useful?"""
    rho: dict[str, float | None] = {}
    for variant in ("fixed", "buggy"):
        pairs = [(r.arms["A"].scores["generated"].score, r.arms["B"].scores["generated"].score)
                 for r in rows if r.variant == variant]  # fmt: skip
        both = [(a, b) for a, b in pairs if a is not None and b is not None]
        rho[variant] = _spearman([a for a, _ in both], [b for _, b in both])
    counts = {"both": 0, "a_only": 0, "b_only": 0, "neither": 0}
    for row in rows:
        for test, passed in enumerate(row.tool_passes):
            if not passed:
                continue  # a test the tool fails can kill nothing
            kills_a = any(not m[test] for m in row.arms["A"].mutant_passes)
            kills_b = any(not m[test] for m in row.arms["B"].mutant_passes)
            key = (
                "both"
                if kills_a and kills_b
                else "a_only"
                if kills_a
                else "b_only"
                if kills_b
                else "neither"
            )
            counts[key] += 1
    return {"spearman_generated": rho, "per_test": counts | kappa(counts)}


def _spearman(a: list[float], b: list[float]) -> float | None:
    try:
        return spearman(a, b) if len(a) > 1 else None
    except ValueError:  # constant input: undefined, not 0
        return None


def kappa(counts: dict[str, int]) -> dict[str, float | None]:
    """Raw agreement and Cohen's kappa of two yes/no raters from both/a_only/b_only/neither."""
    n = sum(counts.values())
    if not n:
        return {"agreement": None, "kappa": None}
    observed = (counts["both"] + counts["neither"]) / n
    p_a = (counts["both"] + counts["a_only"]) / n
    p_b = (counts["both"] + counts["b_only"]) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    beyond_chance = (observed - expected) / (1 - expected) if expected < 1 else None
    return {"agreement": observed, "kappa": beyond_chance}


def refit(
    rq3: Sequence[StrategyOutcome], mutation: Sequence[MutationRow], *, arm: str
) -> dict[str, JsonValue]:
    """RQ4 on these tools, with ``mutation_score`` = the arm's score on the judged tests."""
    scores = {(r.entry_id, r.variant): r.arms[arm].scores["judged"].score for r in mutation}
    rows = [
        r.model_copy(update={"signals": r.signals.model_copy(
            update={"mutation_score": scores[(r.entry_id, r.variant)]})})
        for r in rq3
        if r.signals is not None and (r.entry_id, r.variant) in scores
    ]  # fmt: skip
    report = fit_rows(rows, sets=SIGNAL_SETS | MUTATION_SETS)
    missing = sum(1 for r in rows if r.signals is not None and r.signals.mutation_score is None)
    return {"arm": arm, "n_tools": len(rows), "n_mutation_missing": missing,
            "signal_sets": report["signal_sets"]}  # fmt: skip


def render_markdown(report: dict[str, Any]) -> str:
    n = report["n_entries"]
    lines = [
        f"# Every strategy side by side ({n} RQ3 eval entries, {2 * n} tools)",
        "",
        "Mutation score = mean share of mutants killed, on the fixed (correct) tools; buggy "
        "tools in brackets. LLM cost per entry from the traces; test-execution time per "
        "strategy was not recorded.",
        "",
        "| Strategy | Bugs caught | Correct tools rejected | Mut. score A | Mut. score B "
        "| LLM tokens / entry | LLM seconds / entry |",
        "|---|---|---|---|---|---|---|",
    ]
    for strategy in STRATEGIES:
        d, m, c = (
            report["detection"][strategy],
            report["mutation"][strategy],
            report["cost"][strategy],
        )
        cells = [
            LABELS[strategy],
            _ratio(d["bugs_caught"], d["buggy"]),
            _ratio(d["correct_rejected"], d["fixed"]),
            _mut_cell(m["A"]),
            _mut_cell(m["B"]),
            f"{c['tokens']:,.0f}",
            f"{c['seconds']:.1f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    duck = report["detection"]["rubber_duck"]
    lines += [
        "",
        f"Rubber-duck verdict missing for {duck['missing_buggy']} buggy and "
        f"{duck['missing_fixed']} fixed tools (counted as not flagged).",
        "",
        "Mutation arms' own cost per entry: Arm A sandbox "
        f"{report['arm_cost']['A']['sandbox_seconds']:.1f} s; Arm B sandbox "
        f"{report['arm_cost']['B']['sandbox_seconds']:.1f} s + "
        f"{report['cost']['arm_b']['tokens']:,.0f} tokens / "
        f"{report['cost']['arm_b']['seconds']:.1f} s LLM.",
    ]
    if "agreement" in report:
        lines += [
            "",
            "## Arm A vs Arm B",
            "",
            "```json",
            json.dumps(report["agreement"], indent=2),
            "```",
        ]
    if "refit" in report:
        header = ["| Arm | Signal set | AUC | Spearman | Brier |", "|---|---|---|---|---|"]
        lines += ["", "## RQ4 refit on these tools (out of fold)", "", *header]
        for arm, fit in report["refit"].items():
            for name, s in fit["signal_sets"].items():
                lines.append(
                    f"| {arm} | {name} | {s['auc']:.3f} | {s['spearman']:.3f} | {s['brier']:.3f} |"
                )
    return "\n".join(lines) + "\n"


def _ratio(k: int, n: int) -> str:
    return f"{k} / {n} = {k / n:.1%}" if n else "n/a"


def _mut_cell(cell: dict[str, Any] | None) -> str:
    if cell is None:
        return "n/a"
    fixed, buggy = cell["fixed"]["mean"], cell["buggy"]["mean"]
    if fixed is None:
        return "missing"
    return f"{fixed:.3f} ({'missing' if buggy is None else f'{buggy:.3f}'})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare_strategies")
    parser.add_argument("--rq3", type=Path, default=Path("results/rq3"))
    parser.add_argument("--mutation", type=Path, default=Path("results/mutation"))
    parser.add_argument("--out", type=Path, default=Path("results/comparison"))
    args = parser.parse_args(argv)

    mutation = [MutationRow.model_validate_json(line) for line in
                (args.mutation / "mutation_eval.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]  # fmt: skip
    entry_ids = sorted({r.entry_id for r in mutation})
    rq3 = [StrategyOutcome.model_validate_json(line) for line in
           (args.rq3 / "testgen_eval.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()]  # fmt: skip
    rq3 = [r for r in rq3 if r.entry_id in set(entry_ids)]
    calls = merge_traces(args.rq3 / "rq3-eval") + merge_traces(args.mutation / "mutation-eval")
    report: dict[str, Any] = {
        "n_entries": len(entry_ids),
        "detection": detection(rq3),
        "mutation": mutation_means(mutation),
        "cost": llm_cost(calls, entry_ids),
        "arm_cost": {
            arm: {
                "sandbox_seconds": sum(r.arms[arm].sandbox_seconds for r in mutation)
                / len(entry_ids)
            }
            for arm in ("A", "B")
        },
        "agreement": agreement(mutation),
        "refit": {arm: refit(rq3, mutation, arm=arm) for arm in ("A", "B")},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "strategies.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    text = render_markdown(report)
    (args.out / "strategies.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
