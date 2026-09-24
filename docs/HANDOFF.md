# Handoff — start here in a new session

**Written:** 2026-09-24 (Day 8 of the 14-day plan in `docs/PLAN.md`) ·
**Branch:** main · **Last commit:** `b919d5f` · **Gate:** green, 258 tests, 0 skips.

Read this, then `docs/MEMORY.md` (durable context + locked decisions) and
`docs/reports/SPRINTS.md` (plan + risks). Deeper: `docs/ARCHITECTURE.md`,
`docs/LLM.md`, `docs/PROMPTS.md`, `docs/WORKFLOW.md`,
`docs/reports/STATUS.md` (results and caveats), `docs/DECISIONS.md` (why).

---

## 1. Verify the environment first (2 minutes)

```bash
cd C:\Users\User\Downloads\tool_validator
.\.venv\Scripts\Activate.ps1
ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q
```

Expect **258 passed**. If tests skip, something below is not running:

| Needs | Check | If missing |
|---|---|---|
| Docker Desktop | `docker version` | start it; 22 tests skip without it |
| sandbox image | `docker images toolvalidator-sandbox:py3.12` | `docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox` |
| dataset | `ls data/runbugrun_py/raw` | see §5 for the URLs (files are git-ignored) |
| SCADS | `.env` has key + both model ids | 3 tests skip without it |

A skip always prints its reason. **A skipped sandbox test is not a passing one.**

## 2. What exists

Built and tested: contracts, config, pipeline, repair, CLI, S1 parse, S2 static
(bandit + mypy), S3 test generation (generator + independent judge), S4 execute in the
Docker sandbox **in two modes** (stdin/stdout and typed function call), the RunBugRun +
CodeNet loader, the SCADS client with call tracing and offline replay, a versioned prompt
registry, and the RQ1/RQ2 experiment runner.

**Not built:** S5 mutation (both arms), S5b rubber-duck, S6 score, S7 MCP schema,
`agents/`, `skills/`, and four of five experiment scripts. **RQ3, RQ4 and RQ5 have no
results yet.** RQ1/RQ2 have pilot numbers only (200 entries; see STATUS §4).

## 3. Do this next, in this order

1. **S5b rubber-duck** (`stages/s5b_rubberduck.py`): an LLM explains the code, a second
   call compares that explanation to the request's description. Two new prompts in the
   registry (`explain_code@v1`, `compare_explanation@v1`); the *stage*, in plain Python,
   turns the comparison into a signal. Gives RQ3 its semantic arm.
2. **S6 score** (`scoring/signals.py`, `scoring/model.py`, `stages/s6_score.py`): collect
   signals from a record, fit logistic regression, report correlation, calibration, AUC
   and a drop-one-out ablation, cross-validated **grouped by `problem_id`**. Answers RQ4.
   Hard safety gates stay outside the regression.
3. **`experiments/run_testgen_strategies.py`** (RQ3) and `fit_reliability_score.py` (RQ4).
4. **Tier 1 run**: 2,000 entries with a 25-test cap (§4), then the RQ1/RQ2 table.
5. **S5 mutation** and **S7 MCP schema** if time allows.

The approved LangGraph plan is at `C:\Users\User\.claude\plans\ok-one-thing-is-sunny-hopcroft.md`.
Steps 0-3 are done (langgraph pinned, tracing, replay, prompt registry). Remaining:
skills wrappers, bounded concurrency, the S3 graph, then the agents for the stages above.
**If the schedule bites, cut the graphs and call the skills directly** — the cut order is
in that plan, and nothing outside `agents/` may import langgraph, so backing out is cheap.

## 4. Decisions already made (don't relitigate; see DECISIONS.md)

- **`CapabilityRequest` is Project B's schema verbatim** (`docs/capability_request.md`):
  `name`, `capability`, `description`, typed `inputs`/`outputs`, `rationale`. Sample I/O
  is **not** on the request; it lives on `RunBugRunEntry.examples`.
- **Execution mode comes from the declared inputs**: only `stdin` → stdin/stdout program;
  named typed parameters → import and call the entrypoint.
- **Output comparison**: trailing whitespace ignored; numeric tolerance (1e-6) **only when
  the expected value is fractional** — tolerating it everywhere hid 4 real int/float bugs.
- **Experiment scale**: seeded subsets, ≤2 entries per problem. Tier 1 = 2,000 entries;
  Tier 2 (LLM/mutation) = 300 + a disjoint 50-entry dev set. **A 25-test cap per program
  is agreed but NOT yet implemented** — it belongs in `experiments/common.py`, and it will
  change the pilot numbers, so report both as a sensitivity check.
- **Models pinned**: generator `Qwen/Qwen3.8-27B`, judge `zai-org/GLM-5.3` (different
  family, blind to the code). `alias-*` names are banned.
- **mutmut produces no mutants for module-level code**, and ~86% of entries have no `def`,
  so arm A needs a documented script→function wrapping step.

## 5. Dataset (git-ignored, re-download if absent)

`data/runbugrun_py/raw/` from
`https://github.com/giganticode/run_bug_run_data/releases/download/v0.0.1/`:
`python_valid0.jsonl.gz`, `python_test0.jsonl.gz`, `tests_all.jsonl.gz`,
`Manifest.json.gz`; plus problem statements from
`https://raw.githubusercontent.com/IBM/Project_CodeNet/main/doc/problem_descriptions.tar.gz`.
SHA-256 values are in `docs/reports/sprint-01.md` and `sprint-02.md`. The `train` split
(3 files, ~16 MB) is **not** downloaded and is not needed unless the score fit wants it.

## 6. House rules that matter most

Test first and watch it fail · the gate gates the commit · refactor and feature never
share a commit · ask before changing the spine, adding a dependency or creating a
top-level module · infrastructure failures raise, they never become verdicts · tool code
runs **only** in the container · never invent a number, and say when something is an
estimate or unverified.

The last session proved the point: function mode passed its unit tests but was
**completely broken in a container** (a missing `Any` import) until the real Docker tests
ran. Run the real tests.
