# Handoff — start here in a new session

**Written:** 2026-10-02 (after Day 14 of the plan in `docs/PLAN.md`) · **Branch:** main ·
**Gate:** green, **457 tests, 0 skips**. Sohaib commits; check `git log` for the last commit.

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

Expect **457 passed, 0 skipped**. If tests skip, something below is not running:

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
| RQ3 tests from the request | ✅ eval (274/300 entries): bugs caught — statement samples 74.5%, generated 89.8%, judged 88.7%; **side-by-side table with mutation on 100 entries: STATUS §4.8** |
| RQ4 reliability score | ✅ out of fold: AUC 0.966, ρ 0.808, Brier 0.058; without rubber-duck 0.927 |
| RQ5 MCP schema | ✅ 23 real MCP tools (Project B): LLM input schemas exact 138/138; output schema valid 74–80% (STATUS §4.12) |

Built: syntax check, static analysis, test generation (per-test or batched judge, prebuilt
suites), test run (stdin + typed modes, real-Docker verified), rubber-duck
(`compare_explanation@v2`), `scoring/` (signals + grouped-CV model), RQ1/RQ2, RQ3 and RQ4
runners, LLM tracing + offline replay, prompt registry, completion caps, 429 waits.
Mutation (S5, both arms) built and run on 100 entries (experiment only, not in `pipeline.py`).
S6 score stage + pipeline mapping (>= 0.5 → ACCEPT, else NEEDS_REVIEW), S7 MCP schema, rubber-duck
agreement and judge-independence runners (2026-10-02). **Not built:** `agents/` (optional).

Results on disk (git-ignored): `results/tier1/`, `results/rq3/testgen_eval.*` + trace
`results/rq3/rq3-eval/`, `results/rq4/score_eval.json`, `results/mutation/` (+ trace `mutation-eval/`),
`results/comparison/strategies.{json,md}`, `results/agreement/`, `results/judge_independence/`,
`results/rq4/score_model.json` (the deployed S6 model), `results/rq5/`, pilots `results/pilot*`.
RQ5 needs Project B on disk: `C:/Users/User/Documents/ramiya/Capability-Gap-Detection-in-Agentic-Workflows`.

## 3. Where things stand and what to do next (2026-10-02)

**Done:** every PLAN.md item has a result (RQ1–RQ5, mutation arms, rubber-duck agreement,
judge independence, S6 stage; STATUS §4.5–4.12) and the **report is drafted**:
`docs/reports/Project_D_Report.docx` (Word, A4, ~4,000 words, 8 tables; schema-validated).

**Next, in this order:**
1. **Commit** the uncommitted work (§3a). Sohaib makes the commits.
2. **Sohaib reviews the report** in Word: accept "update fields" (or the contents page is
   empty); check layout visually (never rendered here: no LibreOffice on this machine), the
   title-page date and names, and the Discussion's last paragraph (the draft conclusion of
   STATUS §4.8, phrased as a suggestion).
3. **Decide the S6 threshold** (default 0.5; trade-off table STATUS §4.11 / report Table 7).
4. Optional: add Sohaib's own related-work papers (he chose "only what the repo cites" for now;
   never invent citations); split the 11 oversized files (needs approval for new files); give
   the CLI a full LLM + Docker configuration.

**Report build script:** `build_report.js` (docx-js) lives only in the 2026-10-02 session's
scratch folder `C:/Users/User/AppData/Local/Temp/claude/c--Users-User-Downloads-tool-validator/
9dc86c4b-883d-49fc-b701-df797d1fe237/scratchpad/` and may be deleted with it. To change the
report, edit the .docx in Word, or ask to save the script into the repo (a new file → approval).

### 3a. Uncommitted work and the suggested commits (in this order — later files import earlier ones)
1. `toolvalidator/mutation/kill.py`, `tests/mutation/test_kill.py` —
   `mutation: pass float tolerances through run_matrix`
2. `experiments/run_mutation_arms.py` + test — `experiments: add the mutation-arms runner with suites replayed from the RQ3 trace`
3. `toolvalidator/scoring/metrics.py`, `scoring/model.py`, `tests/scoring/test_metrics.py`,
   `tests/scoring/test_model.py` — `scoring: split metrics out of model.py; add the deployed ScoreModel`
   (`model.py` holds both; use `git add -p` to keep the refactor in its own commit)
4. `toolvalidator/config.py`, `pipeline.py`, `stages/s6_score.py`, `tests/test_config.py`,
   `tests/test_pipeline.py`, `tests/stages/test_s6_score.py` —
   `s6: add the score stage and map the score to ACCEPT or NEEDS_REVIEW`
5. `experiments/fit_reliability_score.py` + test — `experiments: fit extra signal sets and write the deployed S6 model`
6. `experiments/compare_strategies.py` + test — `experiments: add the side-by-side strategy comparison`
7. `experiments/run_rubberduck_agreement.py` + test — `experiments: measure rubber-duck run-to-run agreement`
8. `experiments/run_judge_independence.py` + test — `experiments: compare a same-model judge with the other-family judge`
9. `.gitignore`, `data/loaders/mcp_tools.py`, `tests/data/loaders/test_mcp_tools.py` —
   `data: load Project B's MCP tools and real schemas (never committed)`
10. `toolvalidator/prompts/mcp.py`, `prompts/__init__.py`, `stages/s7_mcp_schema.py`,
    `tests/stages/test_s7_mcp_schema.py`, `tests/prompts/test_registry.py`, `docs/PROMPTS.md` —
    `s7: add the MCP schema stage and generate_mcp_schema@v1`
11. `experiments/run_mcp_accuracy.py` + test — `experiments: add the RQ5 MCP schema accuracy runner`
12. `docs/DECISIONS.md`, `HANDOFF.md`, `MEMORY.md`, `PROJECT_LOG.md`, `STRUCTURE.md`,
    `reports/STATUS.md` — `docs: record agreement, judge independence, S6 and RQ5 results`
13. `docs/reports/Project_D_Report.docx` — `docs: add the final written report`

Never commit `data/mcp_tools/` (Project B has no licence; it is git-ignored) or `results/`.

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
