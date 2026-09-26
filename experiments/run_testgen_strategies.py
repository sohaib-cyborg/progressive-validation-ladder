"""RQ3: which test-generation strategy catches bugs, from the request alone?

    python -m experiments.run_testgen_strategies --set dev --out results/rq3

Per entry, ONE suite is generated blind (request only: no code, no statement samples) and
judged in one batched call; the same suite runs on the buggy and the fixed tool
(docs/DECISIONS.md 2026-09-26). Per tool, S4 runs three arms — ``examples`` (statement
samples, no LLM), ``generated`` (every generated test), ``judged`` (judge-accepted only) —
and S5b runs once. The label is the variant; the dataset's own tests are never used here.
The ``judged`` record (S1→S2→S3→S4→S5b) yields the RQ4 signals. Rows are appended per
entry, so an interrupted run resumes where it stopped.
"""

import argparse
import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import Variant, sample_entries
from toolvalidator.config import Settings, load_settings
from toolvalidator.contracts import IOExample, Sandbox, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import LLMError, ScadsClient
from toolvalidator.llm.trace import TracingClient, trace_context, writer_for_run
from toolvalidator.pipeline import static_stages
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import DockerSandbox, NoExecutionSandbox
from toolvalidator.scoring.signals import Signals, collect_signals
from toolvalidator.stages import s3_testgen, s4_execute, s5b_rubberduck

type SandboxFactory = Callable[[], AbstractContextManager[Sandbox]]
ARMS = ("examples", "generated", "judged")
DEV_SIZE, EVAL_SIZE = 50, 300
DEFAULT_N_TESTS = 8


class ArmOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    n_tests: int
    pass_rate: float | None
    category: str | None  # S4 failure category; None = all tests passed
    failed_tests: list[int] = []  # indices of failed tests (S4 reports at most 5)

    @property
    def failed(self) -> bool:
        """A real test failure (an arm with no tests cannot fail a tool)."""
        return self.n_tests > 0 and self.category is not None


class StrategyOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    entry_id: int
    problem_id: str
    split: str
    variant: Variant
    is_correct: bool
    bug_labels: list[str]
    gate_category: str | None  # S1/S2 hard-gate rejection: nothing else ran
    suite_generated: int
    suite_accepted: int
    arms: dict[str, ArmOutcome]
    semantics_score: float | None
    semantic_violation: bool | None
    signals: Signals | None
    semantic_error: str | None = None  # S5b's LLM output was unusable: semantics missing


def tier2_entries(
    raw_dir: Path, which: Literal["dev", "eval"], *, seed: int
) -> list[RunBugRunEntry]:
    """The seeded Tier-2 order: first 50 = dev (tuning, never reported), next 300 = eval."""
    entries = sample_entries(raw_dir, n=DEV_SIZE + EVAL_SIZE, seed=seed, max_per_problem=2)
    return entries[:DEV_SIZE] if which == "dev" else entries[DEV_SIZE:]


def evaluate_entry(
    entry: RunBugRunEntry,
    client: ScadsClient,
    sandbox_for: SandboxFactory,
    settings: Settings,
    *,
    n_tests: int = DEFAULT_N_TESTS,
) -> list[StrategyOutcome]:
    with trace_context(tool_id=str(entry.entry_id)):
        suite = s3_testgen.build_suite(
            client, entry.request, code=None, n=n_tests, batch_judge=True
        )
        return [
            _evaluate_tool(entry, variant, suite, client, sandbox_for, settings)
            for variant in ("buggy", "fixed")
        ]


def _evaluate_tool(
    entry: RunBugRunEntry,
    variant: Variant,
    suite: s3_testgen.JudgedSuite,
    client: ScadsClient,
    sandbox_for: SandboxFactory,
    settings: Settings,
) -> StrategyOutcome:
    code = entry.fixed_code if variant == "fixed" else entry.buggy_code
    artifact = ToolArtifact(tool_id=f"{entry.entry_id}-{variant}", code=code)
    record = ValidationRecord(request=entry.request)
    base: dict[str, object] = {
        "entry_id": entry.entry_id,
        "problem_id": entry.problem_id,
        "split": entry.split,
        "variant": variant,
        "is_correct": variant == "fixed",
        "bug_labels": entry.bug_labels,
        "suite_generated": len(suite.judged),
        "suite_accepted": len(suite.accepted),
    }
    no_exec = NoExecutionSandbox()
    for stage in static_stages(settings):
        gate = stage(artifact, record, no_exec)
        if not gate.passed:  # hard safety gate: outside the score, nothing else runs
            return StrategyOutcome.model_validate(
                base
                | {
                    "gate_category": gate.category or "unspecified",
                    "arms": {},
                    "semantics_score": None,
                    "semantic_violation": None,
                    "signals": None,
                }
            )
    s3_testgen.run(artifact, record, no_exec, suite=suite)
    generated = [IOExample(input=t.input, output=t.output) for t, _ in suite.judged]
    accepted = [IOExample(input=t.input, output=t.output) for t in suite.accepted]
    with sandbox_for() as sandbox:
        arms = {
            "examples": _arm(artifact, entry, entry.examples, sandbox, settings),
            "generated": _arm(artifact, entry, generated, sandbox, settings),
        }
        judged = _execute(artifact, record, accepted, sandbox, settings)
        arms["judged"] = _outcome(judged, len(accepted))
    score: JsonValue = None
    violated: JsonValue = None
    error: str | None = None
    try:
        duck = s5b_rubberduck.run(artifact, record, no_exec, client=client)
    except LLMError as exc:  # keep the execution arms; the semantic signal is missing
        error = f"{type(exc).__name__}: {exc}"[:300]
    else:
        violated = duck.data.get("violated")
        score = duck.data.get("semantics_score")
    return StrategyOutcome.model_validate(
        base
        | {
            "gate_category": None,
            "arms": arms,
            "semantics_score": float(score) if isinstance(score, int | float) else None,
            "semantic_violation": violated > 0 if isinstance(violated, int) else None,
            "signals": collect_signals(record),
            "semantic_error": error,
        }
    )


def _arm(
    artifact: ToolArtifact,
    entry: RunBugRunEntry,
    tests: Sequence[IOExample],
    sandbox: Sandbox,
    settings: Settings,
) -> ArmOutcome:
    scratch = ValidationRecord(request=entry.request)
    return _outcome(_execute(artifact, scratch, tests, sandbox, settings), len(tests))


def _execute(
    artifact: ToolArtifact,
    record: ValidationRecord,
    tests: Sequence[IOExample],
    sandbox: Sandbox,
    settings: Settings,
) -> StageResult:
    return s4_execute.run(
        artifact,
        record,
        sandbox,
        tests=tests,
        timeout_s=settings.execution.test_timeout_s,
        rel_tol=settings.execution.float_rel_tol,
        abs_tol=settings.execution.float_abs_tol,
    )


def _outcome(result: StageResult, n_tests: int) -> ArmOutcome:
    rate = result.data.get("pass_rate")
    failures = result.data.get("failures")
    indices = [
        f["index"]
        for f in (failures if isinstance(failures, list) else [])
        if isinstance(f, dict) and isinstance(f.get("index"), int)
    ]
    return ArmOutcome(
        n_tests=n_tests,
        pass_rate=float(rate) if isinstance(rate, int | float) else None,
        category=None if result.passed else result.category,
        failed_tests=[i for i in indices if isinstance(i, int)],
    )


def summarize_strategies(rows: Sequence[StrategyOutcome]) -> dict[str, JsonValue]:
    """Per arm: bugs caught / correct tools failed; plus what S5b adds over ``judged``."""
    buggy = [r for r in rows if not r.is_correct and r.gate_category is None]
    fixed = [r for r in rows if r.is_correct and r.gate_category is None]
    arms: dict[str, JsonValue] = {}
    for arm in ARMS:
        arms[arm] = {
            "detection_rate": _rate([r.arms[arm].failed for r in buggy]),
            "false_rejection_rate": _rate([r.arms[arm].failed for r in fixed]),
            "buggy_without_tests": sum(1 for r in buggy if r.arms[arm].n_tests == 0),
            "fixed_without_tests": sum(1 for r in fixed if r.arms[arm].n_tests == 0),
        }
    missed = [r for r in buggy if not r.arms["judged"].failed]
    passed_fixed = [r for r in fixed if not r.arms["judged"].failed]
    return {
        "n_tools": len(rows),
        "gate_rejected": sum(1 for r in rows if r.gate_category is not None),
        "arms": arms,
        "semantic": {
            "errors": sum(1 for r in rows if r.semantic_error is not None),
            "violation_rate_buggy": _rate([r.semantic_violation is True for r in buggy]),
            "violation_rate_fixed": _rate([r.semantic_violation is True for r in fixed]),
            "extra_catches_over_judged": sum(1 for r in missed if r.semantic_violation is True),
            "extra_false_alarms_over_judged": sum(
                1 for r in passed_fixed if r.semantic_violation is True
            ),
        },
    }


def _rate(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def done_entries(path: Path) -> set[int]:
    """Entries with both variants already written (safe to skip on resume)."""
    if not path.exists():
        return set()
    seen: dict[int, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = StrategyOutcome.model_validate_json(line)
            seen.setdefault(row.entry_id, set()).add(row.variant)
    return {entry_id for entry_id, variants in seen.items() if len(variants) == 2}


# --- command line ------------------------------------------------------------------

_worker: dict[str, Any] = {}  # per-process LLM + Docker clients


def _run_entry(
    entry: RunBugRunEntry, settings: Settings, out: Path, run_id: str, n_tests: int
) -> list[StrategyOutcome]:
    import docker

    if not _worker:
        traced = TracingClient(ScadsClient(settings.llm), writer_for_run(out, run_id))
        _worker["client"] = cast(ScadsClient, traced)  # structural: same complete()
        _worker["docker"] = docker.from_env(timeout=int(settings.sandbox.timeout_s) + 120)

    @contextmanager
    def sandbox_for() -> Iterator[Sandbox]:
        with provision(_worker["docker"], settings.sandbox) as container:
            yield DockerSandbox(container, settings.sandbox)

    with trace_context(run_id=run_id):
        return evaluate_entry(entry, _worker["client"], sandbox_for, settings, n_tests=n_tests)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_testgen_strategies")
    parser.add_argument("--set", choices=["dev", "eval"], required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/runbugrun_py/raw"))
    parser.add_argument("--out", type=Path, default=Path("results/rq3"))
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--n-tests", type=int, default=DEFAULT_N_TESTS)
    parser.add_argument("--workers", type=int, default=4, help="LLM-bound: keep small")
    parser.add_argument("--limit", type=int, default=0, help="entries this run, 0 = all")
    args = parser.parse_args(argv)

    settings = load_settings()
    rows_path = args.out / f"testgen_{args.set}.jsonl"
    done = done_entries(rows_path)
    todo = [
        e for e in tier2_entries(args.raw_dir, args.set, seed=args.seed) if e.entry_id not in done
    ]
    todo = todo[: args.limit] if args.limit else todo
    run_id = f"rq3-{args.set}"
    print(f"{len(done)} entries done, {len(todo)} to run, {args.workers} workers")

    started = time.perf_counter()
    errors: list[dict[str, str]] = []
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_entry, e, settings, args.out, run_id, args.n_tests): e for e in todo
        }
        for count, future in enumerate(as_completed(futures), start=1):
            entry = futures[future]
            try:
                rows = future.result()
            except Exception as exc:  # one bad entry must not lose the run; it reruns later
                errors.append(
                    {"entry_id": str(entry.entry_id), "error": f"{type(exc).__name__}: {exc}"}
                )
            else:
                with rows_path.open("a", encoding="utf-8") as handle:
                    handle.writelines(row.model_dump_json() + "\n" for row in rows)
            elapsed = time.perf_counter() - started
            print(
                f"  {count}/{len(todo)} entries  {elapsed:.0f}s  {len(errors)} errors", flush=True
            )

    all_rows = (
        [
            StrategyOutcome.model_validate_json(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if rows_path.exists()
        else []
    )
    if not all_rows:
        print("no rows produced; see errors", errors[:5])
        return 1
    summary = {
        **summarize_strategies(all_rows),
        "set": args.set,
        "seed": args.seed,
        "n_tests_requested": args.n_tests,
        "prompts": [
            "generate_tests@v1",
            "judge_batch@v1",
            "explain_code@v1",
            "compare_explanation@v2",
        ],
        "generator_model": settings.llm.generator_model,
        "judge_model": settings.llm.judge_model,
        "this_run_wall_clock_s": round(time.perf_counter() - started, 1),
        "this_run_entries": len(todo),
        "errors": errors[:20],
        "n_errors": len(errors),
    }
    summary_path = args.out / f"testgen_{args.set}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
