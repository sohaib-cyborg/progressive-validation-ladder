"""RQ4: does a score fit from the validator's signals predict true correctness?

    python -m experiments.fit_reliability_score --rows results/rq3/testgen_eval.jsonl \
        --out results/rq4/score_eval.json

Reads the RQ3 rows. Label = the variant (fixed = correct); group = ``problem_id``; inputs
= the ``Signals`` of the judged record (never the dataset's own tests). Tools rejected by
a hard gate (S1 syntax, S2 dangerous call) stay outside the regression and are only
counted. Everything reported is out of fold (``scoring.model.evaluate``).
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import JsonValue

from experiments.run_testgen_strategies import StrategyOutcome
from toolvalidator.scoring.model import ScoreModel, evaluate, fit_model

STATIC = ("bandit_findings", "mypy_error_count")
TESTS = ("test_pass_rate", "tests_run")
S5B = ("semantics_score", "semantic_violation")
# Joint ablations: one-at-a-time ablation hides correlated signals (the two S5b ones).
SIGNAL_SETS: dict[str, tuple[str, ...]] = {
    "all": STATIC + TESTS + S5B,
    "without_s5b": STATIC + TESTS,
    "tests_only": TESTS,
    "s5b_only": S5B,
    "static_only": STATIC,
}
# Only when rows carry a mutation score (experiments/compare_strategies.py); RQ3 rows do not.
MUTATION = ("mutation_score",)
MUTATION_SETS: dict[str, tuple[str, ...]] = {
    "all_plus_mutation": STATIC + TESTS + S5B + MUTATION,
    "tests_plus_mutation": TESTS + MUTATION,
    "mutation_only": MUTATION,
}


def fit_rows(
    rows: Sequence[StrategyOutcome],
    *,
    folds: int = 5,
    sets: Mapping[str, tuple[str, ...]] = SIGNAL_SETS,
) -> dict[str, JsonValue]:
    usable = [r for r in rows if r.gate_category is None and r.signals is not None]
    if not usable:
        raise ValueError("no rows with signals to fit")
    signals = [r.signals for r in usable if r.signals is not None]
    labels = [r.is_correct for r in usable]
    groups = [r.problem_id for r in usable]
    report = evaluate(signals, labels, groups, folds=folds)
    fitted: dict[str, JsonValue] = {}
    for name, chosen in sets.items():
        fit = evaluate(signals, labels, groups, folds=folds, signals=chosen)
        fitted[name] = {
            "signals": list(chosen),
            "auc": fit.auc,
            "spearman": fit.spearman,
            "brier": fit.brier,
        }
    return {
        "n_rows": len(rows),
        "n_gate_rejected_excluded": sum(1 for r in rows if r.gate_category is not None),
        "n_semantic_missing": sum(1 for r in usable if r.semantic_error is not None),
        "fit": report.model_dump(mode="json"),
        "signal_sets": fitted,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fit_reliability_score")
    parser.add_argument("--rows", type=Path, required=True, help="RQ3 testgen_*.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--model-out", type=Path, help="also write the deployed S6 model here")
    args = parser.parse_args(argv)

    lines = args.rows.read_text(encoding="utf-8").splitlines()
    rows = [StrategyOutcome.model_validate_json(line) for line in lines if line.strip()]
    if not rows:
        raise ValueError(f"no rows in {args.rows}")
    report = {**fit_rows(rows, folds=args.folds), "rows": str(args.rows), "folds": args.folds}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.model_out is not None:
        model = deployed_model(rows)
        args.model_out.parent.mkdir(parents=True, exist_ok=True)
        args.model_out.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote the S6 model ({len(model.features)} features) to {args.model_out}")
    return 0


def deployed_model(rows: Sequence[StrategyOutcome]) -> ScoreModel:
    """The S6 model: the "all" signal set fit on every gate-passing row (no mutation:
    it added nothing to RQ4, STATUS §4.8). Its quality is the out-of-fold report above."""
    usable = [r for r in rows if r.gate_category is None and r.signals is not None]
    signals = [r.signals for r in usable if r.signals is not None]
    return fit_model(signals, [r.is_correct for r in usable], SIGNAL_SETS["all"])


if __name__ == "__main__":
    raise SystemExit(main())
