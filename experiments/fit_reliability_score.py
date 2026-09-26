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
from collections.abc import Sequence
from pathlib import Path

from pydantic import JsonValue

from experiments.run_testgen_strategies import StrategyOutcome
from toolvalidator.scoring.model import evaluate

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


def fit_rows(rows: Sequence[StrategyOutcome], *, folds: int = 5) -> dict[str, JsonValue]:
    usable = [r for r in rows if r.gate_category is None and r.signals is not None]
    if not usable:
        raise ValueError("no rows with signals to fit")
    signals = [r.signals for r in usable if r.signals is not None]
    labels = [r.is_correct for r in usable]
    groups = [r.problem_id for r in usable]
    report = evaluate(signals, labels, groups, folds=folds)
    sets: dict[str, JsonValue] = {}
    for name, chosen in SIGNAL_SETS.items():
        fit = evaluate(signals, labels, groups, folds=folds, signals=chosen)
        sets[name] = {
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
        "signal_sets": sets,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fit_reliability_score")
    parser.add_argument("--rows", type=Path, required=True, help="RQ3 testgen_*.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args(argv)

    lines = args.rows.read_text(encoding="utf-8").splitlines()
    rows = [StrategyOutcome.model_validate_json(line) for line in lines if line.strip()]
    if not rows:
        raise ValueError(f"no rows in {args.rows}")
    report = {**fit_rows(rows, folds=args.folds), "rows": str(args.rows), "folds": args.folds}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
