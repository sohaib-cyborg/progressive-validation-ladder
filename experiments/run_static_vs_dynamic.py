"""RQ1/RQ2: static-only vs. static+execution on a seeded RunBugRun subset.

    python -m experiments.run_static_vs_dynamic --n 200 --out results/

Writes ``static_vs_dynamic.jsonl`` (one row per tool) and ``static_vs_dynamic.summary.json``.
The execution arm uses the dataset's own tests, i.e. the best case for dynamic
checking; generated tests (RQ3) come later.
"""

import argparse
import json
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import docker

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import (
    ToolOutcome,
    default_workers,
    evaluate_tool,
    sample_entries,
    summarize,
    write_jsonl,
)
from toolvalidator.config import Settings, load_settings
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import DockerSandbox

_client: Any = None


def _docker_client(settings: Settings) -> Any:
    global _client  # one client per worker process
    if _client is None:
        _client = docker.from_env(timeout=int(settings.sandbox.timeout_s) + 120)
    return _client


def evaluate_entry(entry: RunBugRunEntry, settings: Settings) -> list[ToolOutcome]:
    """Both variants of one entry, each in its own fresh container (docs/DECISIONS.md)."""
    client = _docker_client(settings)
    outcomes = []
    for variant in ("buggy", "fixed"):
        with provision(client, settings.sandbox) as container:
            sandbox = DockerSandbox(container, settings.sandbox)
            outcomes.append(evaluate_tool(entry, variant, sandbox, settings))
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_static_vs_dynamic")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/runbugrun_py/raw"))
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--n", type=int, default=2000, help="entries (each gives 2 tools)")
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--max-per-problem", type=int, default=2)
    parser.add_argument("--splits", nargs="+", default=["valid", "test"])
    parser.add_argument("--workers", type=int, default=0, help="0 = auto")
    args = parser.parse_args(argv)

    settings = load_settings()
    entries = sample_entries(
        args.raw_dir,
        splits=args.splits,
        n=args.n,
        seed=args.seed,
        max_per_problem=args.max_per_problem,
    )
    client = _docker_client(settings)
    workers = args.workers or default_workers(settings, client.info()["MemTotal"])
    print(f"{len(entries)} entries ({2 * len(entries)} tools), {workers} workers")

    started = time.perf_counter()
    outcomes: list[ToolOutcome] = []
    errors: list[dict[str, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate_entry, entry, settings): entry for entry in entries}
        for done, future in enumerate(as_completed(futures), start=1):
            entry = futures[future]
            try:
                outcomes.extend(future.result())
            except Exception as exc:  # one bad entry must not lose the whole run
                errors.append(
                    {"entry_id": str(entry.entry_id), "error": f"{type(exc).__name__}: {exc}"}
                )
            if done % 25 == 0 or done == len(entries):
                elapsed = time.perf_counter() - started
                print(f"  {done}/{len(entries)} entries  {elapsed:.0f}s  {len(errors)} errors")
    elapsed = time.perf_counter() - started

    if not outcomes:
        print("no outcomes produced; see errors")
        return 1
    write_jsonl(args.out / "static_vs_dynamic.jsonl", outcomes)
    summary = {
        **summarize(outcomes),
        "seed": args.seed,
        "splits": list(args.splits),
        "max_per_problem": args.max_per_problem,
        "workers": workers,
        "wall_clock_s": round(elapsed, 1),
        "seconds_per_tool": round(elapsed / len(outcomes), 3),
        "errors": errors[:20],
        "n_errors": len(errors),
        "sandbox_image": settings.sandbox.image,
    }
    summary_path = args.out / "static_vs_dynamic.summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
