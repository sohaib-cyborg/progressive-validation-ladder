"""Mutation arms (S5) on the RQ3 eval suites: how strong is each strategy's test suite?

    python -m experiments.run_mutation_arms --out results/mutation [--limit 2]

Entries: the first 100 RQ3 eval entries, in the seeded Tier-2 order, that RQ3 completed
with both variants past the static gates. Each entry's suite is **rebuilt offline** from
the RQ3 trace, replaying only that entry's own successful calls (entries of one problem
share identical prompts), so the tests are exactly the published ones; the rebuilt test
counts must equal the RQ3 row's, or the entry fails.

Per tool (buggy and fixed): Arm A = up to 20 operator mutants (seeded); Arm B = up to 5
LLM-invented mutants (one generator call, code only). Each arm runs the tool and its
mutants against one union suite (statement samples + generated tests) in a fresh container;
every strategy's score comes from that matrix. The tool's own pass/fail per suite is
compared with RQ3's and any disagreement is recorded, not hidden. Rows are appended per
entry, so an interrupted run resumes.
"""

import argparse
import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import Variant
from experiments.run_testgen_strategies import DEFAULT_N_TESTS, StrategyOutcome, tier2_entries
from toolvalidator.config import Settings, load_settings
from toolvalidator.contracts import IOExample, Sandbox
from toolvalidator.llm.replay import ReplayClient
from toolvalidator.llm.scads_client import LLMError, ScadsClient
from toolvalidator.llm.trace import (
    LLMCall,
    TracingClient,
    merge_traces,
    trace_context,
    writer_for_run,
)
from toolvalidator.mutation import Mutant, MutantSet
from toolvalidator.mutation.arm_a_mutmut import mutate
from toolvalidator.mutation.arm_b_llm import invent
from toolvalidator.mutation.kill import KillMatrix, SuiteScore, run_matrix, suite_score
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import DockerSandbox
from toolvalidator.stages import s3_testgen

type SandboxFactory = Callable[[], AbstractContextManager[Sandbox]]
SUITES = ("examples", "generated", "judged")
N_ENTRIES = 100


class ArmResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    mutants: list[Mutant]
    candidates: int
    dropped: int
    mutant_passes: list[list[bool]]  # per mutant, per union test
    scores: dict[str, SuiteScore]
    sandbox_seconds: float
    error: str | None = None  # Arm B's LLM reply was unusable: its scores are missing


class MutationRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: int
    problem_id: str
    variant: Variant
    is_correct: bool
    bug_labels: list[str]
    suites: dict[str, list[int]]  # indices into the union suite
    tool_passes: list[bool]  # per union test (from Arm A's run)
    tool_stable: bool  # the tool gave the same pass/fail in both arms' runs
    rq3_mismatches: list[str]  # suites where the tool's pass/fail differs from RQ3's row
    arms: dict[str, ArmResult]
    seconds: float


def rebuild_suite(
    calls: Sequence[LLMCall], entry: RunBugRunEntry, *, n_tests: int
) -> s3_testgen.JudgedSuite:
    """RQ3's suite for this entry, replayed from its own successful calls. A miss raises."""
    own = [c for c in calls if c.tool_id == str(entry.entry_id) and c.ok]
    client = cast(ScadsClient, ReplayClient(own))  # structural: same complete()
    return s3_testgen.build_suite(client, entry.request, code=None, n=n_tests, batch_judge=True)


def union_suite(
    entry: RunBugRunEntry, suite: s3_testgen.JudgedSuite
) -> tuple[list[IOExample], dict[str, list[int]]]:
    """Statement samples then every generated test; ``judged`` is the accepted subset."""
    start = len(entry.examples)
    generated = [IOExample(input=t.input, output=t.output) for t, _ in suite.judged]
    indices = {
        "examples": list(range(start)),
        "generated": list(range(start, start + len(generated))),
        "judged": [start + i for i, (_, verdict) in enumerate(suite.judged) if verdict.valid],
    }
    return [*entry.examples, *generated], indices


def evaluate_tool(
    entry: RunBugRunEntry,
    variant: Variant,
    suite: s3_testgen.JudgedSuite,
    rq3: StrategyOutcome,
    client: ScadsClient,
    sandbox: Sandbox,
    settings: Settings,
) -> MutationRow:
    started = time.perf_counter()
    code = entry.fixed_code if variant == "fixed" else entry.buggy_code
    tests, indices = union_suite(entry, suite)
    arm_a = mutate(code, seed=entry.entry_id * 2 + (variant == "fixed"))
    arm_b, error = _invent(client, code, entry.entry_id, variant)
    matrices = {
        arm: run_matrix(
            code,
            mutants.mutants,
            entry.request,
            tests,
            sandbox,
            timeout_s=settings.execution.test_timeout_s,
            rel_tol=settings.execution.float_rel_tol,
            abs_tol=settings.execution.float_abs_tol,
        )
        for arm, mutants in (("A", arm_a), ("B", arm_b))
    }
    tool = matrices["A"].tool
    return MutationRow(
        entry_id=entry.entry_id,
        problem_id=entry.problem_id,
        variant=variant,
        is_correct=variant == "fixed",
        bug_labels=entry.bug_labels,
        suites=indices,
        tool_passes=tool,
        tool_stable=matrices["B"].tool == tool,
        rq3_mismatches=[s for s in SUITES if rq3.arms[s].failed != _fails(tool, indices[s])],
        arms={
            "A": _arm(arm_a, matrices["A"], indices, None),
            "B": _arm(arm_b, matrices["B"], indices, error),
        },
        seconds=time.perf_counter() - started,
    )


def evaluate_entry(
    entry: RunBugRunEntry,
    rq3: dict[str, StrategyOutcome],
    calls: Sequence[LLMCall],
    client: ScadsClient,
    sandbox_for: SandboxFactory,
    settings: Settings,
    *,
    n_tests: int = DEFAULT_N_TESTS,
) -> list[MutationRow]:
    """Rebuild the entry's RQ3 suite (counts must match RQ3), then run both tools."""
    suite = rebuild_suite(calls, entry, n_tests=n_tests)
    rebuilt = (len(suite.judged), len(suite.accepted))
    for row in rq3.values():
        if rebuilt != (row.suite_generated, row.suite_accepted):
            raise ValueError(
                f"entry {entry.entry_id}: rebuilt suite {rebuilt} does not match RQ3 "
                f"({row.suite_generated}, {row.suite_accepted})"
            )
    rows: list[MutationRow] = []
    for variant in ("buggy", "fixed"):
        with sandbox_for() as sandbox:  # a fresh container per tool, as in RQ3
            rows.append(
                evaluate_tool(entry, variant, suite, rq3[variant], client, sandbox, settings)
            )
    return rows


def _invent(
    client: ScadsClient, code: str, entry_id: int, variant: Variant
) -> tuple[MutantSet, str | None]:
    try:
        with trace_context(tool_id=str(entry_id), variant=variant):
            return invent(client, code), None
    except LLMError as exc:  # keep Arm A; Arm B is missing for this tool
        return MutantSet(mutants=[], candidates=0, dropped=0), f"{type(exc).__name__}: {exc}"[:300]


def _arm(
    mutants: MutantSet, matrix: KillMatrix, indices: dict[str, list[int]], error: str | None
) -> ArmResult:
    return ArmResult(
        mutants=mutants.mutants,
        candidates=mutants.candidates,
        dropped=mutants.dropped,
        mutant_passes=matrix.mutants,
        scores={s: _score(matrix, indices[s], error) for s in SUITES},
        sandbox_seconds=matrix.seconds,
        error=error,
    )


def _score(matrix: KillMatrix, indices: list[int], error: str | None) -> SuiteScore:
    score = suite_score(matrix, indices)
    return score if error is None else score.model_copy(update={"score": None})


def _fails(tool: list[bool], indices: list[int]) -> bool:
    """As RQ3 counts it: a suite with tests fails the tool if any test fails."""
    return bool(indices) and not all(tool[i] for i in indices)


def completed_entries(rows: Sequence[StrategyOutcome]) -> set[int]:
    """RQ3 entries with both variants written and past the static gates."""
    seen: dict[int, set[str]] = {}
    for row in rows:
        if row.gate_category is None:
            seen.setdefault(row.entry_id, set()).add(row.variant)
    return {entry_id for entry_id, variants in seen.items() if len(variants) == 2}


def done_entries(path: Path) -> set[int]:
    if not path.exists():
        return set()
    seen: dict[int, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = MutationRow.model_validate_json(line)
            seen.setdefault(row.entry_id, set()).add(row.variant)
    return {entry_id for entry_id, variants in seen.items() if len(variants) == 2}


def summarize(rows: Sequence[MutationRow]) -> dict[str, JsonValue]:
    """Mean mutation score per arm, variant and suite; missing scores are counted, not zeroed."""
    arms: dict[str, JsonValue] = {}
    for arm in ("A", "B"):
        per_variant: dict[str, JsonValue] = {}
        for variant in ("buggy", "fixed"):
            tools = [r for r in rows if r.variant == variant]
            per_variant[variant] = {s: _mean([r.arms[arm].scores[s].score for r in tools])
                                    for s in SUITES}  # fmt: skip
        arms[arm] = per_variant | {
            "mutants": sum(len(r.arms[arm].mutants) for r in rows),
            "candidates": sum(r.arms[arm].candidates for r in rows),
            "dropped": sum(r.arms[arm].dropped for r in rows),
            "errors": sum(1 for r in rows if r.arms[arm].error is not None),
            "sandbox_seconds": round(sum(r.arms[arm].sandbox_seconds for r in rows), 1),
        }
    return {
        "n_tools": len(rows),
        "rq3_mismatched_tools": sum(1 for r in rows if r.rq3_mismatches),
        "unstable_tools": sum(1 for r in rows if not r.tool_stable),
        "arms": arms,
    }


def _mean(scores: Sequence[float | None]) -> dict[str, JsonValue]:
    present = [s for s in scores if s is not None]
    mean = sum(present) / len(present) if present else None
    return {"mean_score": mean, "n_scored": len(present), "n_missing": len(scores) - len(present)}


# --- command line ------------------------------------------------------------------

_worker: dict[str, Any] = {}  # per process: RQ3 trace, traced LLM client, Docker client
RUN_ID = "mutation-eval"


def _run_entry(
    entry: RunBugRunEntry, rq3: dict[str, StrategyOutcome], settings: Settings, rq3_dir: Path,
    out: Path,
) -> list[MutationRow]:  # fmt: skip
    import docker

    if not _worker:
        _worker["calls"] = merge_traces(rq3_dir / "rq3-eval")
        traced = TracingClient(ScadsClient(settings.llm), writer_for_run(out, RUN_ID))
        _worker["client"] = cast(ScadsClient, traced)  # structural: same complete()
        _worker["docker"] = docker.from_env(timeout=int(settings.sandbox.timeout_s) + 120)

    @contextmanager
    def sandbox_for() -> Iterator[Sandbox]:
        with provision(_worker["docker"], settings.sandbox) as container:
            yield DockerSandbox(container, settings.sandbox)

    with trace_context(run_id=RUN_ID):
        return evaluate_entry(
            entry, rq3, _worker["calls"], _worker["client"], sandbox_for, settings
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_mutation_arms")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/runbugrun_py/raw"))
    parser.add_argument("--rq3", type=Path, default=Path("results/rq3"))
    parser.add_argument("--out", type=Path, default=Path("results/mutation"))
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--n-entries", type=int, default=N_ENTRIES)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="entries this run, 0 = all")
    args = parser.parse_args(argv)

    settings = load_settings()
    rq3_rows = [
        StrategyOutcome.model_validate_json(line)
        for line in (args.rq3 / "testgen_eval.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_entry: dict[int, dict[str, StrategyOutcome]] = {}
    for row in rq3_rows:
        by_entry.setdefault(row.entry_id, {})[row.variant] = row
    completed = completed_entries(rq3_rows)
    ordered = tier2_entries(args.raw_dir, "eval", seed=args.seed)
    chosen = [e for e in ordered if e.entry_id in completed][: args.n_entries]
    rows_path = args.out / "mutation_eval.jsonl"
    done = done_entries(rows_path)
    todo = [e for e in chosen if e.entry_id not in done]
    todo = todo[: args.limit] if args.limit else todo
    print(f"{len(chosen)} entries chosen, {len(done)} done, {len(todo)} to run")

    started = time.perf_counter()
    errors: list[dict[str, str]] = []
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_entry, e, by_entry[e.entry_id], settings, args.rq3, args.out): e
            for e in todo
        }
        for count, future in enumerate(as_completed(futures), start=1):
            entry = futures[future]
            try:
                rows = future.result()
            except Exception as exc:  # one bad entry must not lose the run; it reruns later
                errors.append(
                    {"entry_id": str(entry.entry_id), "error": f"{type(exc).__name__}: {exc}"[:500]}
                )
            else:
                with rows_path.open("a", encoding="utf-8") as handle:
                    handle.writelines(row.model_dump_json() + "\n" for row in rows)
            elapsed = time.perf_counter() - started
            print(
                f"  {count}/{len(todo)} entries  {elapsed:.0f}s  {len(errors)} errors", flush=True
            )

    all_rows = [
        MutationRow.model_validate_json(line)
        for line in rows_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if rows_path.exists() else []  # fmt: skip
    summary = {
        **summarize(all_rows),
        "entries_chosen": len(chosen),
        "entries_done": len({r.entry_id for r in all_rows}),
        "seed": args.seed,
        "prompts": ["invent_mutants@v1"],
        "generator_model": settings.llm.generator_model,
        "this_run_wall_clock_s": round(time.perf_counter() - started, 1),
        "this_run_entries": len(todo),
        "errors": errors[:20],
        "n_errors": len(errors),
    }
    (args.out / "mutation_eval.summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if all_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
