# Sprint Plan (Project D, 2-week sprint)

Derived from `docs/PLAN.md` §8 (schedule) and `START_HERE.md` (build order).
Day 1 = **2026-09-17 (Thu)**, assuming consecutive working days. Adjust the
dates if weekends are off. The PLAN.md deadline logic still holds: **all
experiments frozen by end of Day 10.**

Each sprint has a goal, the tasks (in dependency order), **preconditions**
(things that must be true before a task starts; these are hard stops), and
**exit criteria** (how we know it's done). The definition of done for every task
is the CLAUDE.md gate: `ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q`
green, plus a commit.

---

## Sprint 1: The spine (Days 1–2)

**Goal:** the pipeline runs S1+S2 end-to-end on the smoke examples and a few real
RunBugRun entries, with a real sandbox that can execute a script.

| # | Task (START_HERE step) | File(s) | Precondition |
|---|---|---|---|
| 1.1 | Project skeleton (Phase 0) | package tree, `__init__.py`s | Python 3.12 environment |
| 1.2 | Contracts (step 3) | `contracts.py` + test | 1.1 |
| 1.3 | Config (step 4) | `config.py` + test | 1.2 |
| 1.4 | RunBugRun loader (step 5) | `data/loaders/runbugrun.py` + test | ⛔ **a real RunBugRun Python entry inspected; input style (stdin vs. func-call) recorded in MEMORY.md** |
| 1.5 | Sandbox container (step 6) | `sandbox/container.py` + test | ⛔ **`docker_probe.py` prints ALL CHECKS PASSED** (Docker Desktop must be running) |
| 1.6 | Sandbox exec (step 7) | `sandbox/exec.py` + test | 1.5 |
| 1.7 | S1 parse (step 8) | `stages/s1_parse.py` + test | 1.2 |
| 1.8 | S2 static (step 9) | `stages/s2_static.py` + test | 1.2 |
| 1.9 | Pipeline state machine (step 10) | `pipeline.py` + test | 1.7, 1.8 |
| 1.10 | CLI + smoke examples (step 11) | `cli.py`, `examples/*` | 1.9 |

**Exit criteria:** `python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json`
prints a verdict; a syntax-error tool is rejected; gate green. *(Corrected 2026-09-17:
`broken_celsius.py` has a logic bug, which static-only checks accept by design. See DECISIONS.md.)*

**Status: ✅ COMPLETE (2026-09-17, tag `sprint-1`).** All tasks 1.1–1.10 done, plus a minimal
`repair.py` and `NoExecutionSandbox`. 96 tests. Static pipeline and Docker sandbox smoke-tested on
10 real RunBugRun entries. Log: [sprint-01.md](sprint-01.md).

**Reordering allowed:** 1.7–1.9 depend only on contracts, so they can run
*before* 1.4–1.6 if the dataset or Docker preconditions are still blocked.
This keeps the sprint moving without skipping a precondition.

---

## Sprint 2: Dynamic signals (Days 3–5)

**Goal:** every dynamic signal produces a number on the real dataset.

| # | Task | File(s) | Precondition |
|---|---|---|---|
| 2.1 | LLM client (single choke point) | `llm/scads_client.py` + test | `SCADS_API_KEY` in `.env` works (one real call) |
| 2.2 | Test-gen types | `testgen/schemas.py` + test | 1.2 |
| 2.3 | Generator + judge | `testgen/generator.py`, `testgen/judge.py` + tests | 2.1, 2.2 |
| 2.4 | S3 orchestration | `stages/s3_testgen.py` + test | 2.3 |
| 2.5 | S4 execute (+ stdin harness if 1.4 says stdin) | `stages/s4_execute.py` + test | 1.6 |
| 2.6 | **First RQ1/RQ2 numbers:** static-only config over the Tier 1 subset (2,000 entries, seeded; DECISIONS.md) | `experiments/common.py`, `experiments/run_static_vs_dynamic.py` | 1.4, 1.10 |
| 2.7 | S5 arm A (mutmut, inside sandbox; scripts must be wrapped in a function first) | `mutation/arm_a_mutmut.py`, `mutation/kill.py` + tests | ✅ `mutmut_probe.py` passed inside the sandbox image (2026-09-17) |
| 2.8 | S5 arm B (LLM mutants) | `mutation/arm_b_llm.py` + test | 2.1 |
| 2.9 | S5 dispatcher | `stages/s5_mutation.py` + test | 2.7, 2.8 |
| 2.10 | S5b rubber-duck (first pass) | `stages/s5b_rubberduck.py` + test | 2.1 |

**Exit criteria:** static-only results for the Tier 1 subset saved under
`results/`; S4, S5 (both arms), S5b each produce a signal on a dev sample.
**Day 5 self-check (PLAN.md):** is the dynamic config running end-to-end on the full set?

---

## Sprint 3: Headline measurement + score (Days 6–7)

| # | Task | File(s) |
|---|---|---|
| 3.1 | Tune rubber-duck prompt on a dev split; report inter-run agreement | `stages/s5b_rubberduck.py` |
| 3.2 | Full static+dynamic run → headline table (PLAN §6.1) | `experiments/run_static_vs_dynamic.py` |
| 3.3 | Signals table | `scoring/signals.py` + test |
| 3.4 | Fit logistic regression; correlation, calibration, AUC, ablation on held-out split (§6.3) | `scoring/model.py`, `stages/s6_score.py`, `experiments/fit_reliability_score.py` |

**Exit criteria:** RQ1/RQ2 table and RQ4 metrics exist as files in `results/`,
computed only on held-out data.

---

## Sprint 4: Remaining RQs + freeze (Days 8–10)

| # | Task | File(s) |
|---|---|---|
| 4.1 | S7 MCP schema generation + accuracy experiment (§6.4) | `stages/s7_mcp_schema.py`, `experiments/run_mcp_accuracy.py` |
| 4.2 | Test-gen strategy comparison, Arm A vs. Arm B (§6.2) | `experiments/run_testgen_strategies.py` |
| 4.3 | (Optional) judge independence (§6.5): **first thing dropped** if late | `experiments/run_judge_independence.py` |
| 4.4 | Richer repair signals (minimal `repair.py` exists since Sprint 1) | `repair.py` + test |
| 4.5 | **Freeze all results**; Day 10 = buffer / re-runs | — |

**Exit criteria:** every number and figure the report needs exists in `results/`
and is reproducible from a command.

---

## Sprint 5: Report (Days 11–14)

Days 11–13 write (intro, related work, method, one section per RQ, limitations
including the human-bugs-as-proxy framing, conclusion). Day 14 polish + submit.
No new code except bug fixes to reproduce a frozen number.

---

## Risks tracked across sprints

| ID | Risk | Mitigation / status |
|---|---|---|
| R1 | Python 3.12 not installed (only 3.11.1 found on 2026-09-17) | ✅ Resolved 2026-09-17: Sohaib installed 3.12; `.venv` uses Python 3.12.10. |
| R2 | Docker Desktop daemon not running (2026-09-17) | ✅ Resolved 2026-09-17: Docker running, `docker_probe.py` ALL CHECKS PASSED. |
| R3 | mutmut executes tool code, and the probe runs it **on the host**. CLAUDE.md §7 forbids executing tool code outside the container. mutmut 3.x may also not run natively on Windows (unverified). | ✅ Decided 2026-09-17: mutmut runs **inside the sandbox container** for arm A (DECISIONS.md). The probe must still pass before 2.7. |
| R4 | PLAN.md assumes S0–S3 are "already built", but the fresh start (DECISIONS Day 0) means S3 (generator + judge + LLM client) must be built from scratch in Sprint 2. | Sprint 2 is the most overloaded sprint. If it slips, PLAN §8 slack order applies: drop 6.5 first, then Arm B detail. |
| R5 | `mypy --strict toolvalidator` does not type-check `data/` or `experiments/`, so the loader (critical path) would go unchecked. | ✅ Decided 2026-09-17: gate widened to `mypy --strict toolvalidator data experiments` (DECISIONS.md). |
| R6 | Rubber-duck tuning (3.1) and score fit (3.4) are the likeliest overruns (PLAN §8). | Day 10 buffer. |
| R7 | Cost of full-dataset runs (static ≈ 0.5 s/tool, sandbox run ≈ 0.3 s, measured). | ✅ Decided 2026-09-17: seeded subsets (Tier 1: 2,000 entries, Tier 2: 300 + 50 dev) + W parallel workers, one container per tool (DECISIONS.md). W = 3 until Docker Desktop memory is raised (then 10). S4 must still batch test cases. |
| R8 | Sandbox image lacks numpy. | ✅ Resolved 2026-09-17: `toolvalidator-sandbox:py3.12` (numpy 1.26.4, mutmut 3.8.0, pytest 9.1.1). |
| R9 | mutmut 3 generates **no mutants for module-level code**; ~86% of entries have no `def`. | Arm A (2.7) needs a documented script→function wrapping transform; report it as methodology. |
| R10 | Docker Desktop has 1.9 GiB, which limits parallel sandboxes to 3. | Sohaib to raise to 8 GB (Settings → Resources). |
