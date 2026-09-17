# toolvalidator — Project D

Progressive validation of LLM-synthesized tools. Given a tool (Python) and a
Capability Request (task + example I/O), decide **ACCEPT / REJECT / NEEDS_REVIEW**
with a reliability score and structured repair signals — by running the tool
through staged checks from cheap (parse, static) to expensive (sandboxed
execution, mutation testing, semantic check).

Research project (TU Dresden). Evaluated on the RunBugRun dataset (Python subset).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add your SCADS_API_KEY

# the local gate (run before every commit)
ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q

# validate one tool
python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json
```

## The pipeline

S0 provision (Docker) → S1 parse → S2 static (bandit+mypy) → S3 test-gen
(LLM generator + independent judge) → S4 execute (in sandbox) → S5 mutation
(two arms) → S5b rubber-duck (semantic) → S6 score (fitted) → S7 MCP schema.

Deterministic core; LLMs only propose tests/explanations, never decide verdicts.
All untrusted code runs in a disposable, network-off, resource-capped container.

## Docs

- `CLAUDE.md` — engineering rules (read by Claude Code automatically)
- `docs/PLAN.md` — research plan + 2-week schedule
- `docs/MEMORY.md` — durable context + session log
- `docs/STRUCTURE.md` — folder layout
- `docs/DECISIONS.md` — why we chose what we chose
- `START_HERE.md` — day-1 bootstrap order

## Experiments (the deliverable)

```bash
python -m experiments.run_static_vs_dynamic --dataset data/runbugrun_py --out results/
python -m experiments.run_testgen_strategies --dataset data/runbugrun_py --out results/
python -m experiments.fit_reliability_score --results results/
python -m experiments.run_mcp_accuracy --dataset data/runbugrun_py --out results/
```
