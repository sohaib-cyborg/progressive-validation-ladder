# MEMORY.md — Durable Project Context

**Claude Code: read this file at the start of every session before writing code.**
It holds what stays true across sessions: who, what, the locked decisions, and a
running session log. Update the session log every time you finish work.

---

## Who

- **Author:** Sohaib Ashraf — sohaib.ashraf@mailbox.tu-dresden.de
- **Role:** Master's Student, Computer Science, TU Dresden
- **Supervisor:** AFM Mohimenul Joaa · Prof. Dr.-Ing. Michael Färber
- **Chair:** Scalable Software Architectures for Data Analytics

## What (the project in five sentences)

Project D validates LLM-synthesized tools. Input: a tool (Python) + a Capability
Request (task + example I/O), coming from Project C in the pipeline B→C→D→A. It
runs the tool through staged checks (parse → static → sandboxed execution →
mutation → semantic) and returns ACCEPT / REJECT / NEEDS_REVIEW + a reliability
score + repair signals. It is a **research project**: the output is experiments +
a report. Evaluated on the **RunBugRun** dataset, Python subset only.

## The research questions (fixed — do not reword)

- **RQ1** Slip rate: broken/unsafe tools passing naive (no-sandbox) vs. sandboxed.
- **RQ2** Is static analysis alone enough, or must dynamic execution run? *(headline)*
- **RQ3** Can tests be auto-generated from the Capability Request, no human
  annotation — and which strategy is best?
- **RQ4** Can a reliability score (from test pass rate, static results, synthesis
  metadata) be defined to *correlate* with true correctness? (fit from data)
- **RQ5** Can accurate MCP JSON schemas be generated from code + request?

## Locked decisions (do not relitigate without asking Sohaib)

1. **Fresh start.** Previous codebase is abandoned for poor structure. Build clean
   per STRUCTURE.md.
2. **Dataset = RunBugRun, Python subset only.** Extract only Python problems.
   Human-written bugs are used as a *proxy* for synthesized-tool errors — this is
   flagged honestly in the report. (QuixBugs optional as an early smoke test.)
3. **All three research components are IN scope:** mutation testing (two arms:
   real mutmut + LLM-invented), rubber-duck semantic checking, MCP schema
   generation. None are cut.
4. **Static checks are minimal on purpose:** bandit (dangerous calls) + mypy
   (types) only. They are the cheap baseline the dynamic checks are compared
   against. Secrets/pip-audit/allowlist are explicitly OUT (future work).
5. **Reliability score is fit from data** (logistic regression on RunBugRun),
   reported with correlation + calibration + AUC + signal ablation. Not
   hand-weighted. Hard-safety gates stay OUTSIDE the regression.
6. **Deterministic core, LLM as subroutine.** LLM never decides a verdict.
7. **Timeline: 2 weeks.** Experiments done ~Day 10, writing Days 11–14. See PLAN.md.

## Architecture invariants (from CLAUDE.md, repeated for memory)

- Every stage: `f(artifact, record, sandbox) -> StageResult`.
- Hard failure → short-circuit to REJECT + FailureReport (repair signal).
- All untrusted code runs in the Docker sandbox (network off, capped, dropped
  caps, timeout, destroyed after). Parse/static run on host.
- One LLM choke point: `llm/scads_client.py`. One sandbox boundary: `sandbox/`.
- `contracts.py` is the spine; `tests/` mirrors the package.

## Environment / access

- **SCADS LLM:** endpoint `https://llm.scads.ai/v1` (OpenAI-compatible), key in
  env `SCADS_API_KEY` (see `.env.example`). Models listed on 2026-09-17 (`GET /models`,
  23 entries) include Qwen/Qwen3.8-27B, zai-org/GLM-5.3(-Flash), openai/gpt-oss-120b,
  deepseek-ai/DeepSeek-V4.1-Flash, meta-llama/Llama-3.3-70B-Instruct,
  google/gemma-4-26B-A4B-it, MiniMaxAI/MiniMax-M3 (HTTP 500 that day), plus `alias-*`
  names. Qwen3-Coder is no longer listed.
- **Compute:** GPU + SCADS access confirmed working on Sohaib's machine.
- **Docker** required and available on the dev machine.

## Model roles (pinned for reproducibility)

- **Generator:** `Qwen/Qwen3.8-27B` (pinned 2026-09-17; Qwen3-Coder is no longer
  served by SCADS). Sees code as interface reference; treats the description as truth.
- **Judge:** `zai-org/GLM-5.3` (pinned 2026-09-17). A *different family*, and larger
  with stronger reasoning than the generator (Sohaib's requirement). Blind to the tool
  code. Decides if a generated test is valid. See DECISIONS.md.
- Set via `SCADS_GENERATOR_MODEL` / `SCADS_JUDGE_MODEL` in `.env`. Never use
  `alias-*` model names (they hide the underlying model, so results aren't reproducible).
- (Choice of exact models is pinned, not optimized — "best model" is out of scope
  beyond the optional judge-independence check.)

## Known gotchas / watch-outs

- RunBugRun has **145,400 Python bug instances** (confirmed) — far more than
  enough to fit the score regression; overfitting is a non-issue even after heavy
  filtering. Ships fine-grained bug-type labels (control flow / expressions /
  literals / function calls) → use these for per-category recall (no BugsInPy
  needed). Test cases are deterministic.
- **RunBugRun format (inspected 2026-09-17):** entries are **stdin/stdout scripts**
  (2,032/2,054 of python_valid0 read input; only 295 contain a `def`; median 10 LOC).
  Bug files: `python_{train0-2,valid0,test0}.jsonl.gz` = 145,370 entries with fields
  `id, buggy_submission_id, fixed_submission_id, problem_id, user_id, buggy_code,
  fixed_code, labels (list|null), change_count, line_hunks, errors (often absent)`.
  Tests: `tests_all.jsonl.gz` = 321,418 rows `{id, problem_id, input, output}` (stdin →
  expected stdout), linked by `problem_id` (median ~103 tests/problem in valid).
- **RunBugRun has NO problem descriptions in its release files.** Use CodeNet's
  `doc/problem_descriptions.tar.gz` (IBM/Project_CodeNet on GitHub): HTML per
  problem, covering 3,924/3,926 problems with tests. Two markups: AtCoder
  (`<h3>Sample Input N</h3><pre>`, bilingual with a `lang-en` span) and AOJ
  (`<H2>Sample Input N</H2>` + `<H2>Output for the Sample Input N</H2>`).
- Raw downloads live in `data/runbugrun_py/raw/` (git-ignored); sha256 in sprint-01.md.
- **Expected outputs are not newline-consistent:** 17,108/321,418 (5.3%) lack a trailing
  newline, 1,008 end in spaces/tabs, 0 contain `
`, 8 are empty. S4 must normalise trailing
  whitespace or it will fail correct programs.
- **Sandbox image** `toolvalidator-sandbox:py3.12` (numpy 1.26.4, mutmut 3.8.0, pytest 9.1.1) must be
  built once: `docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox`.
- **mutmut 3 does not mutate module-level code** (0 mutants on a script; 10 once wrapped in
  `def main()`). ~86% of RunBugRun entries have no `def`, so arm A must wrap scripts first.
- **Docker Desktop memory is 1.9 GiB** → at most 3 parallel 512m sandboxes until raised.
- **Experiment scale:** seeded subsets (Tier 1: 2,000 entries; Tier 2: 300 + 50 dev),
  one container per tool, W parallel workers (DECISIONS.md).
- **Sandbox cost (measured):** ~0.3 s per `DockerSandbox.run`; static S1+S2 ~0.5 s per real
  tool. S4 must batch test cases per tool.
- Mutation testing: **mutmut 3.8** (NOT 2.4). v3 API needs a `[mutmut]` section
  with `source_paths=` (the old `--paths-to-mutate` CLI flag is gone;
  `paths_to_mutate` is deprecated). No clean Python API → drive it as a
  **subprocess**: write tool+tests+`setup.cfg` to a temp dir, run `mutmut run`,
  parse `mutmut results` for the kill count. Confirmed working on single-function
  snippets. This makes `mutation/arm_a_mutmut.py` a subprocess orchestrator.
  **Update 2026-09-17:** that subprocess runs *inside the sandbox container*, not on
  the host (it executes tool code). See DECISIONS.md.
- **bandit severities are not what you'd guess** (bandit 1.9.4, measured): `eval`,
  `exec`, `pickle.loads` = MEDIUM; `os.system(var)`, `shell=True` with a variable,
  `hashlib.md5` = HIGH; `__import__("os").popen` = not flagged. S2 rejects at HIGH
  (configurable) and records all findings.
- **In-process mypy reads this repo's pyproject `strict = true`** unless called with
  `--config-file=`. S2 passes it. Never drop that flag.
- **Cost:** static S1+S2 ≈ 0.5 s per real RunBugRun tool (measured on 20). Full dataset,
  both versions, static-only ≈ 40 h serial (estimate). Decide subsample/parallelism before
  running experiments (SPRINTS.md R7).
- Rubber-duck output is noisy → tune the prompt on a dev split, report inter-run
  agreement.
- LLM JSON responses can be malformed → parse defensively in `scads_client.py`.
- Fitting the score needs a held-out split — never report on training data.

---

## Pre-flight checks (do before Day 1/2)

Two probe scripts are in the repo root. Run them on the dev machine:
- `python docker_probe.py` — confirms the locked-down container config
  (network off, mem/pids cap, caps dropped, no-new-privileges) actually runs on
  your Docker/OS, and that network is truly blocked. Must print ALL CHECKS PASSED.
- `python mutmut_probe.py` — confirms mutmut 3.8 runs on a single function.

Status (fill in after running):
- [x] docker_probe.py passed on dev machine (2026-09-17, ALL CHECKS PASSED)
- [x] mutmut_probe.py passed INSIDE the sandbox image (2026-09-17); verified a real kill
- [x] RunBugRun Python count confirmed (145.4K — plenty)  ✅ done via research
- [x] Inspected a real RunBugRun Python entry; input style = **stdin/stdout** (2026-09-17)

## Session log (append one entry per session — newest at bottom)

> Format: `### Day N (YYYY-MM-DD) — <what you set out to do>` then 2–4 bullets:
> what got done, what's committed, what's next, any new gotcha.

### Day 0 (setup) — scaffold
- Repo initialized from the Claude Code guideline scaffold (CLAUDE.md, docs/,
  empty package skeleton per STRUCTURE.md).
- Nothing built yet. Next: Day 1 — write `data/loaders/runbugrun.py` and get the
  dataset flowing (critical path).

<!-- Claude Code: add your session entries below this line -->

### Day 1 (2026-09-17) — Sprint 1: the spine
- Done + committed: skeleton (Python 3.12.10 `.venv`), contracts (+ `Sandbox`
  Protocol), config, S1 parse, S2 static, repair (minimal), pipeline,
  `NoExecutionSandbox`, CLI + examples. 71 tests, gate green. The static pipeline runs
  end-to-end via the CLI. Log: `docs/reports/sprint-01.md`, plan: `docs/reports/SPRINTS.md`.
  (Correction: the Day 0 "empty package skeleton" did not exist; it was created today.)
- Gate is now `mypy --strict toolvalidator data experiments`. mutmut runs in the
  sandbox. bandit rejects at HIGH (configurable). See DECISIONS.md 2026-09-17.
- Still blocked: 1.4 loader (RunBugRun entry not inspected), 1.5–1.6 Docker sandbox
  (docker_probe not run; daemon off). Next: whichever unblocks first, then Sprint 2.
- SCADS model IDs are not set in `.env` (`SCADS_GENERATOR_MODEL`, `SCADS_JUDGE_MODEL`);
  required before Sprint 2.

### Day 1 cont. (2026-09-17) — Sprint 1 completed
- Pre-flight: docker_probe passed; SCADS models pinned (Qwen3.8-27B / GLM-5.3); RunBugRun
  inspected (stdin/stdout, no descriptions → CodeNet descriptions).
- Done + committed: RunBugRun loader, sandbox container + DockerSandbox (real-Docker tests),
  max_output_bytes. 96 tests, gate green. Smoke on 10 real entries OK. Tagged `sprint-1`.
- Next: Sprint 2 (LLM client, testgen, S4 with batched runs + output normalisation).
  Open for Sohaib: numpy sandbox image; subsample/parallelism (R7); run mutmut_probe.
