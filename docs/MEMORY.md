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
  env `SCADS_API_KEY` (see `.env.example`). Models available: Qwen3-Coder-30B,
  Llama-3.3-70B, gpt-oss-120b, etc.
- **Compute:** GPU + SCADS access confirmed working on Sohaib's machine.
- **Docker** required and available on the dev machine.

## Model roles (pinned for reproducibility)

- **Generator:** a code-specialized model (Qwen3-Coder class). Sees code as
  interface reference; treats the description as truth.
- **Judge:** an independent model from a *different family* (e.g. Llama-70B).
  Blind to the tool code. Decides if a generated test is valid.
- (Choice of exact models is pinned, not optimized — "best model" is out of scope
  beyond the optional judge-independence check.)

## Known gotchas / watch-outs

- RunBugRun has **145,400 Python bug instances** (confirmed) — far more than
  enough to fit the score regression; overfitting is a non-issue even after heavy
  filtering. Ships fine-grained bug-type labels (control flow / expressions /
  literals / function calls) → use these for per-category recall (no BugsInPy
  needed). Test cases are deterministic.
- RunBugRun entries are competitive-programming style → likely **stdin/stdout**,
  not function-call. The S4 harness must feed stdin and read stdout. Confirm the
  exact format when writing `data/loaders/runbugrun.py`.
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
- **Cost:** S2 ≈ 0.35 s/tool, so full RunBugRun static-only ≈ 14 h serial (estimate).
  Decide subsample/parallelism before running experiments (SPRINTS.md R7).
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
- [ ] docker_probe.py passed on dev machine
- [ ] mutmut_probe.py passed on dev machine
- [x] RunBugRun Python count confirmed (145.4K — plenty)  ✅ done via research
- [ ] Inspected a real RunBugRun Python entry; input style = ______ (stdin / func-call)

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
