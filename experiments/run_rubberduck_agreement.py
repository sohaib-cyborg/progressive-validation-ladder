"""How noisy is the rubber-duck verdict? Re-run it and compare with RQ3 (PLAN §4.2).

    python -m experiments.run_rubberduck_agreement --out results/agreement

A seeded sample of 25 of the 100 mutation-run entries (50 tools). For each tool the
rubber-duck runs again with RQ3's prompts and models (``explain_code@v1``,
``compare_explanation@v2``); RQ3's verdict comes from its rows and its explanation from its
trace, matched by the exact prompt text. Reported: verdict agreement and Cohen's kappa,
Spearman of the semantics score, missing verdicts per run, and how often the explanation
text came back identical. A run whose LLM output is unusable is missing, not a verdict.
"""

import argparse
import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue

from data.loaders.runbugrun import RunBugRunEntry
from experiments.common import Variant
from experiments.compare_strategies import kappa
from experiments.run_testgen_strategies import StrategyOutcome, tier2_entries
from toolvalidator.config import load_settings
from toolvalidator.llm.scads_client import LLMError, ScadsClient, parse_json_object
from toolvalidator.llm.trace import (
    LLMCall,
    TracingClient,
    merge_traces,
    trace_context,
    writer_for_run,
)
from toolvalidator.prompts.rubberduck import render_explain
from toolvalidator.scoring.metrics import spearman
from toolvalidator.stages.s5b_rubberduck import (
    Explanation,
    compare_explanation,
    explain_code,
    semantics_score,
)

N_ENTRIES = 25
RUN_ID = "rubberduck-agreement"


class DuckRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    violation: bool | None  # None = no verdict (unusable LLM output)
    score: float | None
    error: str | None


class AgreementRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: int
    problem_id: str
    variant: Variant
    first: DuckRun  # RQ3's run
    second: DuckRun  # this run
    explanation_same: bool | None  # None when either explanation is unknown


def choose_entries(entry_ids: Sequence[int], n: int, *, seed: int) -> list[int]:
    return sorted(random.Random(seed).sample(sorted(entry_ids), n))


def first_run_explanations(calls: Sequence[LLMCall]) -> dict[str, str]:
    """RQ3's explanations, keyed by the exact explain prompt (it contains the tool's code)."""
    found: dict[str, str] = {}
    for call in calls:
        if call.prompt_id != "explain_code" or not call.ok or not call.user or not call.content:
            continue
        try:
            found.setdefault(
                call.user, Explanation.parse(parse_json_object(call.content)).explanation
            )
        except LLMError:
            continue
    return found


def rerun_tool(
    entry: RunBugRunEntry,
    variant: Variant,
    rq3: StrategyOutcome,
    client: ScadsClient,
    first_explanations: dict[str, str],
) -> AgreementRow:
    code = entry.fixed_code if variant == "fixed" else entry.buggy_code
    explanation: str | None = None
    try:
        with trace_context(tool_id=str(entry.entry_id), variant=variant):
            explanation = explain_code(client, code).explanation
            comparison = compare_explanation(client, entry.request, explanation)
    except LLMError as exc:
        second = DuckRun(violation=None, score=None, error=f"{type(exc).__name__}: {exc}"[:300])
    else:
        second = DuckRun(
            violation=comparison.count("violated") > 0,
            score=semantics_score(comparison),
            error=None,
        )
    first_text = first_explanations.get(render_explain(code))
    same = None if first_text is None or explanation is None else first_text == explanation
    first = DuckRun(violation=rq3.semantic_violation, score=rq3.semantics_score,
                    error=rq3.semantic_error)  # fmt: skip
    return AgreementRow(entry_id=entry.entry_id, problem_id=entry.problem_id, variant=variant,
                        first=first, second=second, explanation_same=same)  # fmt: skip


def summarize(rows: Sequence[AgreementRow]) -> dict[str, JsonValue]:
    both = [r for r in rows if r.first.violation is not None and r.second.violation is not None]
    counts = {"both": 0, "a_only": 0, "b_only": 0, "neither": 0}
    for r in both:
        a, b = bool(r.first.violation), bool(r.second.violation)
        counts["both" if a and b else "a_only" if a else "b_only" if b else "neither"] += 1
    scored = [(r.first.score, r.second.score) for r in rows]
    pairs = [(a, b) for a, b in scored if a is not None and b is not None]
    rho: float | None
    try:
        rho = spearman([a for a, _ in pairs], [b for _, b in pairs]) if len(pairs) > 1 else None
    except ValueError:  # constant scores: undefined, not 0
        rho = None
    verdict: dict[str, JsonValue] = {**counts, **kappa(counts)}
    return {
        "n_tools": len(rows),
        "both_present": len(both),
        "missing": {
            "first": sum(1 for r in rows if r.first.violation is None),
            "second": sum(1 for r in rows if r.second.violation is None),
        },
        "verdict": verdict,
        "score_spearman": rho,
        "score_pairs": len(pairs),
        "explanation_same": {
            "same": sum(1 for r in rows if r.explanation_same is True),
            "different": sum(1 for r in rows if r.explanation_same is False),
            "unknown": sum(1 for r in rows if r.explanation_same is None),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_rubberduck_agreement")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/runbugrun_py/raw"))
    parser.add_argument("--rq3", type=Path, default=Path("results/rq3"))
    parser.add_argument("--mutation", type=Path, default=Path("results/mutation"))
    parser.add_argument("--out", type=Path, default=Path("results/agreement"))
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--n-entries", type=int, default=N_ENTRIES)
    parser.add_argument("--limit", type=int, default=0, help="entries this run, 0 = all")
    args = parser.parse_args(argv)

    settings = load_settings()
    calls = merge_traces(args.rq3 / "rq3-eval")
    _check_same_models(calls, settings.llm.generator_model, settings.llm.judge_model)
    rq3 = {(r.entry_id, r.variant): r for r in _rq3_rows(args.rq3)}
    mutated = {json.loads(line)["entry_id"] for line in
               (args.mutation / "mutation_eval.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()}  # fmt: skip
    chosen = set(choose_entries(sorted(mutated), args.n_entries, seed=args.seed))
    entries = [
        e for e in tier2_entries(args.raw_dir, "eval", seed=args.seed) if e.entry_id in chosen
    ]
    rows_path = args.out / "agreement.jsonl"
    done = _done(rows_path)
    todo = [e for e in entries if e.entry_id not in done]
    todo = todo[: args.limit] if args.limit else todo
    print(f"{len(entries)} entries chosen, {len(done)} done, {len(todo)} to run", flush=True)

    explanations = first_run_explanations(calls)
    client = cast(
        ScadsClient, TracingClient(ScadsClient(settings.llm), writer_for_run(args.out, RUN_ID))
    )
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_context(run_id=RUN_ID):
        for count, entry in enumerate(todo, start=1):
            pair = [rerun_tool(entry, v, rq3[(entry.entry_id, v)], client, explanations)
                    for v in ("buggy", "fixed")]  # fmt: skip
            with rows_path.open("a", encoding="utf-8") as handle:
                handle.writelines(row.model_dump_json() + "\n" for row in pair)
            print(f"  {count}/{len(todo)} entries", flush=True)

    lines = rows_path.read_text(encoding="utf-8").splitlines()
    rows = [AgreementRow.model_validate_json(line) for line in lines if line.strip()]
    summary = {**summarize(rows), "seed": args.seed, "entries": sorted(chosen),
               "prompts": ["explain_code@v1", "compare_explanation@v2"],
               "generator_model": settings.llm.generator_model,
               "judge_model": settings.llm.judge_model}  # fmt: skip
    (args.out / "agreement.summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


def _check_same_models(calls: Sequence[LLMCall], generator: str | None, judge: str | None) -> None:
    """The re-run is only a re-run if RQ3 used the same models (from its trace)."""
    used = {(c.prompt_id, c.model_requested) for c in calls
            if c.prompt_id in ("explain_code", "compare_explanation")}  # fmt: skip
    expected = {("explain_code", generator), ("compare_explanation", judge)}
    if used != expected:
        raise ValueError(
            f"RQ3 used {sorted(map(str, used))}, this run would use {sorted(map(str, expected))}"
        )


def _rq3_rows(rq3_dir: Path) -> list[StrategyOutcome]:
    text = (rq3_dir / "testgen_eval.jsonl").read_text(encoding="utf-8")
    return [StrategyOutcome.model_validate_json(line) for line in text.splitlines() if line.strip()]


def _done(path: Path) -> set[int]:
    if not path.exists():
        return set()
    seen: dict[int, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = AgreementRow.model_validate_json(line)
            seen.setdefault(row.entry_id, set()).add(row.variant)
    return {e for e, variants in seen.items() if len(variants) == 2}


if __name__ == "__main__":
    raise SystemExit(main())
