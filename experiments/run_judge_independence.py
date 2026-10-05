"""(Optional, PLAN §6.5) Does a different-family judge catch more bad tests than the same model?

    python -m experiments.run_judge_independence --out results/judge_independence

On the 100 mutation-run entries, each RQ3 suite is replayed from the RQ3 trace. The
**different-family** verdicts are RQ3's own (`GLM-5.3-Flash`, `judge_batch@v1`). The
**same-family** verdicts come from sending the identical `judge_batch@v1` prompt to the
generator's own model (`Qwen/Qwen3.8-27B`, the only Qwen on SCADS), through ``AsGenerator``:
the config forbids judge == generator on purpose, so the rule is not touched; the call runs
under the generator's completion cap.

Ground truth per generated test: **invalid iff the fixed tool fails it**, from the mutation
run's per-test results (real container runs). Entries whose fixed tool fails its own dataset
tests in Tier 1 are excluded and counted (their "fixed" is not a reliable reference).
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import ToolOutcome
from experiments.compare_strategies import kappa
from experiments.run_mutation_arms import MutationRow, rebuild_suite
from experiments.run_testgen_strategies import DEFAULT_N_TESTS, tier2_entries
from toolvalidator.config import load_settings
from toolvalidator.llm.scads_client import LLMError, LLMResult, Role, ScadsClient
from toolvalidator.llm.trace import (
    LLMCall,
    TracingClient,
    merge_traces,
    trace_context,
    writer_for_run,
)
from toolvalidator.testgen.judge import judge_batch

RUN_ID = "judge-independence"
JUDGES = ("different", "same")


class AsGenerator:
    """Sends every call to the generator role: the generator's model judges its own tests."""

    def __init__(self, inner: ScadsClient) -> None:
        self.inner = inner

    def complete(self, role: Role, *, system: str, user: str) -> LLMResult:
        return self.inner.complete("generator", system=system, user=user)


class TestJudgement(BaseModel):
    model_config = ConfigDict(frozen=True)
    __test__ = False  # not a pytest class

    fixed_passes: bool  # False = the test is invalid (ground truth)
    buggy_passes: bool
    different: bool  # RQ3 judge: test valid?
    same: bool | None  # same-model judge: test valid? None = no usable reply


class JudgeRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: int
    problem_id: str
    fixed_reliable: bool  # the fixed tool passes its own dataset tests (Tier 1)
    same_error: str | None
    tests: list[TestJudgement]


def evaluate_entry(
    entry: RunBugRunEntry,
    mutation: dict[str, MutationRow],
    calls: Sequence[LLMCall],
    same_judge: ScadsClient,
    fixed_reliable: bool,
    *,
    n_tests: int = DEFAULT_N_TESTS,
) -> JudgeRow:
    suite = rebuild_suite(calls, entry, n_tests=n_tests)
    indices = mutation["fixed"].suites["generated"]
    if len(indices) != len(suite.judged):
        raise ValueError(
            f"entry {entry.entry_id}: {len(suite.judged)} generated tests in the suite, "
            f"{len(indices)} in the mutation row"
        )
    same: list[bool | None] = [None] * len(indices)
    error: str | None = None
    try:
        with trace_context(tool_id=str(entry.entry_id)):
            judged = judge_batch(same_judge, entry.request, [t for t, _ in suite.judged])
        same = [verdict.valid for _, verdict in judged]
    except LLMError as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
    tests = [
        TestJudgement(
            fixed_passes=mutation["fixed"].tool_passes[i],
            buggy_passes=mutation["buggy"].tool_passes[i],
            different=verdict.valid,
            same=same[k],
        )
        for k, (i, (_, verdict)) in enumerate(zip(indices, suite.judged, strict=True))
    ]
    return JudgeRow(entry_id=entry.entry_id, problem_id=entry.problem_id,
                    fixed_reliable=fixed_reliable, same_error=error, tests=tests)  # fmt: skip


def summarize(rows: Sequence[JudgeRow]) -> dict[str, JsonValue]:
    """Both judges on the same tests: rows with a reliable fixed tool and both verdicts."""
    paired = [r for r in rows if r.fixed_reliable and r.same_error is None]
    tests = [t for r in paired for t in r.tests]
    judges: dict[str, JsonValue] = {name: _judge_metrics(tests, name) for name in JUDGES}
    counts = {"both": 0, "a_only": 0, "b_only": 0, "neither": 0}  # "rejected" by each judge
    for t in tests:
        a, b = not t.different, t.same is False
        counts["both" if a and b else "a_only" if a else "b_only" if b else "neither"] += 1
    return {
        "entries": {
            "total": len(rows),
            "excluded_unreliable_fixed": sum(1 for r in rows if not r.fixed_reliable),
            "same_errors": sum(1 for r in rows if r.same_error is not None),
            "paired": len(paired),
        },
        "tests": len(tests),
        "invalid_tests": sum(1 for t in tests if not t.fixed_passes),
        "judges": judges,
        "judge_agreement_on_rejection": {**counts, **kappa(counts)},
        "tools": {name: _tool_effect(paired, name) for name in ("no_judge", *JUDGES)},
    }


def _keeps(test: TestJudgement, judge: str) -> bool:
    return judge == "no_judge" or (test.different if judge == "different" else test.same is True)


def _judge_metrics(tests: Sequence[TestJudgement], judge: str) -> dict[str, JsonValue]:
    rejected = [t for t in tests if not _keeps(t, judge)]
    invalid = [t for t in tests if not t.fixed_passes]
    caught = sum(1 for t in rejected if not t.fixed_passes)
    return {
        "rejected": len(rejected),
        "invalid_caught": caught,
        "valid_rejected": len(rejected) - caught,
        "precision": caught / len(rejected) if rejected else None,
        "recall": caught / len(invalid) if invalid else None,
    }


def _tool_effect(rows: Sequence[JudgeRow], judge: str) -> dict[str, JsonValue]:
    """If only the judge's accepted tests ran: bugs caught and correct tools rejected."""
    kept = [[t for t in r.tests if _keeps(t, judge)] for r in rows]
    return {
        "bugs_caught": sum(1 for ts in kept if any(not t.buggy_passes for t in ts)),
        "correct_rejected": sum(1 for ts in kept if any(not t.fixed_passes for t in ts)),
        "tools_per_variant": len(rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_judge_independence")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/runbugrun_py/raw"))
    parser.add_argument("--rq3", type=Path, default=Path("results/rq3"))
    parser.add_argument("--mutation", type=Path, default=Path("results/mutation"))
    parser.add_argument("--tier1", type=Path, default=Path("results/tier1"))
    parser.add_argument("--out", type=Path, default=Path("results/judge_independence"))
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--limit", type=int, default=0, help="entries this run, 0 = all")
    args = parser.parse_args(argv)

    settings = load_settings()
    mutation: dict[int, dict[str, MutationRow]] = {}
    for line in (args.mutation / "mutation_eval.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            mutated = MutationRow.model_validate_json(line)
            mutation.setdefault(mutated.entry_id, {})[mutated.variant] = mutated
    reliable = _fixed_reliable(args.tier1 / "static_vs_dynamic.jsonl")
    entries = [
        e for e in tier2_entries(args.raw_dir, "eval", seed=args.seed) if e.entry_id in mutation
    ]
    rows_path = args.out / "judges.jsonl"
    done = _done(rows_path)
    todo = [e for e in entries if e.entry_id not in done]
    todo = todo[: args.limit] if args.limit else todo
    print(f"{len(entries)} entries, {len(done)} done, {len(todo)} to run", flush=True)

    calls = merge_traces(args.rq3 / "rq3-eval")
    traced = TracingClient(ScadsClient(settings.llm), writer_for_run(args.out, RUN_ID))
    same_judge = cast(ScadsClient, AsGenerator(cast(ScadsClient, traced)))
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_context(run_id=RUN_ID):
        for count, entry in enumerate(todo, start=1):
            fixed_ok = reliable.get(entry.entry_id)
            if fixed_ok is None:
                raise ValueError(f"entry {entry.entry_id} is not in Tier 1")
            row = evaluate_entry(entry, mutation[entry.entry_id], calls, same_judge, fixed_ok)
            with rows_path.open("a", encoding="utf-8") as handle:
                handle.write(row.model_dump_json() + "\n")
            print(f"  {count}/{len(todo)} entries", flush=True)

    lines = rows_path.read_text(encoding="utf-8").splitlines()
    rows = [JudgeRow.model_validate_json(line) for line in lines if line.strip()]
    summary = {**summarize(rows), "prompt": "judge_batch@v1",
               "different_family_model": settings.llm.judge_model,
               "same_family_model": settings.llm.generator_model}  # fmt: skip
    (args.out / "judges.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def _fixed_reliable(path: Path) -> dict[int, bool]:
    """Tier 1: does each entry's fixed tool pass all of its own dataset tests?"""
    found: dict[int, bool] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = ToolOutcome.model_validate_json(line)
            if row.variant == "fixed":
                found[row.entry_id] = row.verdict_dynamic == "ACCEPT"
    return found


def _done(path: Path) -> set[int]:
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {JudgeRow.model_validate_json(line).entry_id for line in lines if line.strip()}


if __name__ == "__main__":
    raise SystemExit(main())
