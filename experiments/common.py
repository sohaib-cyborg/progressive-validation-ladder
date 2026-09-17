"""Shared experiment plumbing: sample the subset, run configurations, save results.

Experiments import the library, never the other way round (docs/STRUCTURE.md).
Sampling is seeded and capped per problem, so runs are reproducible and no popular
problem dominates (docs/DECISIONS.md).
"""

import os
import random
from collections.abc import Iterable, Sequence
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from data.loaders.runbugrun import RunBugRunEntry, Split, iter_entries
from toolvalidator.config import Settings
from toolvalidator.contracts import Sandbox, Stage, ToolArtifact, ValidationRecord, Verdict
from toolvalidator.pipeline import run_pipeline, static_stages
from toolvalidator.sandbox.exec import NoExecutionSandbox
from toolvalidator.stages import s4_execute

type Variant = Literal["buggy", "fixed"]

CONFIG_STATIC = "static"
CONFIG_DYNAMIC = "static+exec"


class ToolOutcome(BaseModel):
    """One tool (one variant of one entry) under every configuration."""

    model_config = ConfigDict(frozen=True)

    entry_id: int
    problem_id: str
    split: str
    variant: Variant
    is_correct: bool
    n_tests: int
    bug_labels: list[str]
    verdict_static: str
    category_static: str | None
    verdict_dynamic: str
    category_dynamic: str | None
    pass_rate: float | None


def sample_entries(
    raw_dir: Path,
    *,
    splits: Sequence[Split] = ("valid", "test"),
    n: int,
    seed: int,
    max_per_problem: int,
) -> list[RunBugRunEntry]:
    pool: list[RunBugRunEntry] = []
    for split in splits:
        pool.extend(iter_entries(raw_dir, split=split))
    pool.sort(key=lambda e: e.entry_id)  # stable order before shuffling
    random.Random(seed).shuffle(pool)
    chosen: list[RunBugRunEntry] = []
    per_problem: dict[str, int] = {}
    for entry in pool:
        if per_problem.get(entry.problem_id, 0) >= max_per_problem:
            continue
        per_problem[entry.problem_id] = per_problem.get(entry.problem_id, 0) + 1
        chosen.append(entry)
        if len(chosen) == n:
            break
    return chosen


def evaluate_tool(
    entry: RunBugRunEntry, variant: Variant, sandbox: Sandbox, settings: Settings
) -> ToolOutcome:
    """Run both configurations on one variant. The dataset's own tests are the oracle."""
    code = entry.fixed_code if variant == "fixed" else entry.buggy_code
    artifact = ToolArtifact(tool_id=f"{entry.entry_id}-{variant}", code=code)
    static = static_stages(settings)
    static_record = run_pipeline(artifact, entry.request, static, NoExecutionSandbox())
    dynamic_stages: list[Stage] = [*static, partial(s4_execute.run, tests=entry.tests)]
    dynamic_record = run_pipeline(artifact, entry.request, dynamic_stages, sandbox)
    execute_result = next((r for r in dynamic_record.results if r.stage == s4_execute.STAGE), None)
    pass_rate = None if execute_result is None else execute_result.data.get("pass_rate")
    return ToolOutcome(
        entry_id=entry.entry_id,
        problem_id=entry.problem_id,
        split=entry.split,
        variant=variant,
        is_correct=variant == "fixed",
        n_tests=len(entry.tests),
        bug_labels=entry.bug_labels,
        verdict_static=_verdict(static_record.verdict),
        category_static=_category(static_record),
        verdict_dynamic=_verdict(dynamic_record.verdict),
        category_dynamic=_category(dynamic_record),
        pass_rate=pass_rate if isinstance(pass_rate, float) else None,
    )


def worker_count(cpus: int, docker_mem_bytes: int, *, mem_limit_bytes: int) -> int:
    """At least 1; bounded by CPUs (leaving 2 free) and by Docker's memory."""
    by_memory = docker_mem_bytes // mem_limit_bytes
    return max(1, min(cpus - 2, by_memory))


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def read_jsonl(path: Path) -> list[ToolOutcome]:
    with path.open("r", encoding="utf-8") as handle:
        return [ToolOutcome.model_validate_json(line) for line in handle if line.strip()]


def default_workers(settings: Settings, docker_mem_bytes: int) -> int:
    return worker_count(
        os.cpu_count() or 2,
        docker_mem_bytes,
        mem_limit_bytes=_bytes(settings.sandbox.mem_limit),
    )


def _bytes(mem_limit: str) -> int:
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    return int(mem_limit[:-1]) * units[mem_limit[-1].lower()]


def _verdict(verdict: Verdict | None) -> str:
    if verdict is None:  # run_pipeline always decides
        raise RuntimeError("pipeline produced no verdict")
    return verdict.value


def _category(record: ValidationRecord) -> str | None:
    return record.failures[0].category if record.failures else None
