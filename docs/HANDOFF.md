# Handoff — start here in a new session

**Written:** 2026-09-28 (Day 12 of the 14-day plan in `docs/PLAN.md`) · **Branch:** main ·
**Last commit:** `f4cea99` · **Gate:** green, **323 tests, 0 skips**.

Read, in order: this file → `docs/PROJECT_LOG.md` (one-file log: architecture, timeline,
decisions, results) → `docs/MEMORY.md` (locked decisions + session log) →
`docs/reports/STATUS.md` (results with caveats). Deeper: `DECISIONS.md`, `ARCHITECTURE.md`,
`LLM.md`, `PROMPTS.md`, `WORKFLOW.md`.

---

## 0. Working agreements with Sohaib (follow exactly)

1. **Claude never commits.** No `git commit`, amend, rebase or any history change. After
   each step, stop at a green gate and list the changed files plus a suggested
   `<area>: <summary>` commit message. Sohaib commits.
2. **No AI attribution anywhere** — no `Co-Authored-By`, no mention of Claude in commit
   messages, PR text or docs. (All 72 old attribution lines were removed on 2026-09-27.)
3. **Wait for "implement"** before building from a plan; Sohaib reviews plans first.
4. **Explain in plain names with a concrete example**, not stage codes. Glossary:
   S1 syntax check · S2 static analysis (bandit + mypy) · S3 test generation · S4 test run
   in the sandbox · S5 mutation · S5b rubber-duck · S6 score · S7 MCP schema.
5. **Keep `docs/PROJECT_LOG.md` complete** as work lands (§1 state, §3 architecture, §5
   timeline, §6 decisions, §7 results, §8 open items) and re-read it fully before calling it
   complete.
6. Never invent a number; say "estimate" or "unverified" when it is one.

## 1. Verify the environment first

```bash
cd C:\Users\User\Downloads\tool_validator
.\.venv\Scripts\Activate.ps1
ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q
```

Expect **323 passed, 0 skipped**. If tests skip, something below is not running:

| Needs | Check | If missing |
|---|---|---|
| Docker Desktop | `docker version` | start it (`C:\Program Files\Docker\Docker\Docker Desktop.exe`); the real-Docker tests skip without it |
| sandbox image | `docker images toolvalidator-sandbox:py3.12` | `docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox` |
| dataset | `ls data/runbugrun_py/raw` | see §5 (files are git-ignored) |
| SCADS | `.env` has key + `SCADS_GENERATOR_MODEL=Qwen/Qwen3.8-27B`, `SCADS_JUDGE_MODEL=zai-org/GLM-5.3-Flash` | the real-LLM tests skip without it |

A skip always prints its reason. **A skipped sandbox test is not a passing one.**

## 2. Where things stand

| Research question | State |
|---|---|
| RQ1/RQ2 static vs execution | ✅ Tier 1 (1,999 entries, all tests): static slip 100%, execution slip 0.35%, false rejection 1.5% |
| RQ3 tests from the request | ✅ eval (274/300 entries): bugs caught — statement samples 74.5%, generated 89.8%, judged 88.7% |
| RQ4 reliability score | ✅ out of fold: AUC 0.966, ρ 0.808, Brier 0.058; without rubber-duck 0.927 |
| RQ5 MCP schema | ❌ not started |

Built: syntax check, static analysis, test generation (per-test or batched judge, prebuilt
suites), test run (stdin + typed modes, real-Docker verified), rubber-duck
(`compare_explanation@v2`), `scoring/` (signals + grouped-CV model), RQ1/RQ2, RQ3 and RQ4
runners, LLM tracing + offline replay, prompt registry, completion caps, 429 waits.
**Not built:** mutation (S5, both arms), the score *stage* (S6), MCP schema (S7), `agents/`.

Results on disk (git-ignored): `results/tier1/`, `results/rq3/testgen_eval.*` + trace
`results/rq3/rq3-eval/`, `results/rq4/score_eval.json`, pilots `results/pilot*`.

## 3. Do this next

**The plan for mutation + the side-by-side strategy comparison is written and awaiting
Sohaib's review:** `C:\Users\User\.claude\plans\generator-proposes-n-tests-snug-gem.md`.
Do not start it until he says "implement". In short:

- **Arm A** — operator-based mutants (mutmut's operator classes, own `ast` engine, because
  mutmut 3 cannot mutate module-level scripts = 86% of programs); **Arm B** — LLM-invented
  mutants (`invent_mutants@v1`, generator role, code only).
- Mutation's role (agreed): **"mutants killed per strategy"** (test strength), an RQ4
  signal, and Arm A vs Arm B agreement. Filtering tests by kills cannot change bug detection
  (a killing test must pass on the tool), so it is not a detection arm.
- On the **first 100 completed RQ3 eval entries**; suites **rebuilt offline** from the RQ3
  trace with `ReplayClient` (no regeneration).
- One comparison table, every strategy a row with the same columns (bugs caught, correct
  tools rejected, mutation score A/B, tokens, seconds): statement samples · generated ·
  judged · rubber-duck alone · judged ∪ rubber-duck. Then the conclusion, from the numbers.
- Parallel strategies apply to the **experiment only**; the pipeline keeps "failed test →
  REJECT" (Sohaib, 2026-09-28).

After that: S6 score stage (approved; the `scoring/metrics.py` split needs approval), RQ5
(S7), then writing (Days 13–14).

## 4. Decisions already made (don't relitigate; see DECISIONS.md)

- **`CapabilityRequest` is Project B's schema verbatim**; sample I/O lives on
  `RunBugRunEntry.examples`, not on the request.
- **Execution mode comes from the declared inputs** (only `stdin` → stdin/stdout program).
- **Output comparison**: trailing whitespace ignored; numeric tolerance only when the
  expected value is fractional.
- **Scale**: seeded, ≤ 2 entries per problem; Tier 1 = 2,000; Tier 2 = 300 eval + 50 dev
  (dev never reported). A 25-test cap exists; the RQ1/RQ2 headline uses all tests.
- **Models**: generator `Qwen/Qwen3.8-27B`, judge `zai-org/GLM-5.3-Flash` (since 2026-09-26;
  GLM-5.3's 3,000-token window could not serve one call). Caps: judge 8,192, generator
  16,384 completion tokens. `alias-*` names banned.
- **RQ3 design**: one blind suite per entry (no code, no samples), batched judge, shared by
  buggy and fixed.
- **RQ4**: inputs never include the dataset's own tests; folds grouped by problem; missing →
  indicator; report named signal sets (joint ablation).

## 5. Dataset (git-ignored, re-download if absent)

`data/runbugrun_py/raw/` from
`https://github.com/giganticode/run_bug_run_data/releases/download/v0.0.1/`:
`python_valid0.jsonl.gz`, `python_test0.jsonl.gz`, `tests_all.jsonl.gz`,
`Manifest.json.gz`; plus problem statements from
`https://raw.githubusercontent.com/IBM/Project_CodeNet/main/doc/problem_descriptions.tar.gz`.
SHA-256 values are in `docs/reports/sprint-01.md` and `sprint-02.md`.

## 6. House rules and known traps

Test first and watch it fail · full gate before handing over a step · refactor and feature
never mixed in one step · ask before changing `contracts.py`, the pipeline contract, adding a
dependency or a new top-level module · infrastructure failures raise, never verdicts · tool
code runs **only** in the container · never invent a number.

Traps seen: a fake sandbox cannot validate a harness (run the real Docker tests); SCADS
rate limits and runaway reasoning (LLM.md §6); PowerShell `*>` logs are UTF-16 and
buffered; Python heredocs through the Bash tool turned `\n` inside string literals into real
newlines — use the Edit tool for such lines. A backup of the pre-rewrite history is on
branch `backup/before-coauthor-removal` (Sohaib may delete it).
