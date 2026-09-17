# START_HERE.md — Day 1 Bootstrap (for Claude Code)

You are starting this project from an empty repo that contains only the docs
(`CLAUDE.md`, `docs/*.md`), `pyproject.toml`, and config files. Your job over the
first sessions is to build the skeleton **in dependency order**, test-first, one
piece at a time. Do NOT scaffold all files at once — build, test, commit, repeat.

Follow this order. Each numbered item is roughly one commit. Run the gate
(`ruff format . && ruff check . && mypy --strict toolvalidator && pytest -q`)
before each commit.

## Phase 0 — project skeleton (Day 1 morning)
1. Create the package dirs with empty `__init__.py` per STRUCTURE.md
   (`toolvalidator/`, `stages/`, `sandbox/`, `testgen/`, `mutation/`, `scoring/`,
   `llm/`, `data/loaders/`, `experiments/`, `tests/` + mirrors). Just the tree.
2. Install: `pip install -e ".[dev]"`. Confirm ruff/mypy/pytest run on the empty
   tree. Commit: `chore: project skeleton`.

## Phase 1 — the spine (Day 1)
3. `contracts.py`: define `CapabilityRequest`, `ToolArtifact`, `StageResult`,
   `ValidationRecord`, `Verdict` (enum), `FailureReport` — all pydantic, all
   typed. Write `tests/test_contracts.py` first (construct each, check
   validation). Commit.
4. `config.py`: settings (SCADS url/key from env, model names, timeouts,
   thresholds, dataset paths). Test that it loads from env. Commit.

## Phase 2 — dataset flowing (Day 1 → Day 2) — CRITICAL PATH
5. `data/loaders/runbugrun.py`: parse the RunBugRun Python subset into an iterable
   of `(CapabilityRequest, tool_code, tests, correct_version, label)`.
   **First, inspect a real RunBugRun entry** and confirm the input style
   (stdin/stdout vs function-call) — record it in MEMORY.md gotchas. Test the
   loader on a few real entries. Commit: `data: RunBugRun Python loader`.

## Phase 3 — sandbox (Day 2)
6. `sandbox/container.py`: provision a `python:3.12-slim` container (network off,
   mem cap, caps dropped, timeout), and destroy it. Test with `@pytest.mark.slow`
   (real Docker) + a fast unit test of the config assembly. Commit.
7. `sandbox/exec.py`: run a script string inside the container, capture
   stdout/stderr/exit-code, enforce timeout. Test with a trivial script. Commit.

## Phase 4 — the cheap stages (Day 2)
8. `stages/s1_parse.py`: `ast.parse`; on `SyntaxError` return failed StageResult
   with category `syntax_error`. Test both paths. Commit.
9. `stages/s2_static.py`: run bandit (HIGH → hard reject) + mypy (type errors →
   soft signal). Test on a clean and a dangerous example. Commit.
10. `pipeline.py`: the state machine that runs stages in order and short-circuits
    on `passed=False`. Wire S1+S2 only for now. Test the short-circuit logic with
    fake stages. Commit.
11. `cli.py`: thin `validate` command that loads a tool+request and runs the
    pipeline. Smoke-test on `examples/`. Commit.

> **Checkpoint (end of Day 2):** pipeline runs S0–S2 on the smoke examples and on
> a few RunBugRun entries, green gate. This is the spine working. Everything after
> is adding stages onto a proven base — follow PLAN.md Days 3–10.

## Rules while doing this
- One file + its test per commit. Gate must be green.
- Read STRUCTURE.md before placing any file.
- If an entry doesn't fit the structure, stop and ask (CLAUDE.md Rule 8).
- Update MEMORY.md session log at the end of each session.
- Do not jump ahead to S4/S5/etc. until the spine (through step 11) is done and
  committed. Depth over breadth.
