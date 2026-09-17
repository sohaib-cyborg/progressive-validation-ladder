# DECISIONS.md — Design Decision Log

Append-only. Every non-trivial design decision gets an entry so future-you (and
Claude Code) knows *why*, not just *what*. Newest at bottom. Never delete entries;
if a decision is reversed, add a new entry that supersedes the old one.

> Format:
> ## YYYY-MM-DD — <short title>
> **Decision:** what we chose.
> **Why:** the reasoning.
> **Alternatives rejected:** what we didn't pick and why.
> **Supersedes:** (if applicable) which earlier decision this overrides.

---

## Day 0 — Fresh start, clean structure
**Decision:** Abandon the previous codebase; rebuild from scratch per STRUCTURE.md.
**Why:** Prior code lacked a consistent structure, which was slowing iteration and
would be fatal on a 2-week deadline.
**Alternatives rejected:** Refactoring the old code in place — too risky, the
structural problems were pervasive.

## Day 0 — RunBugRun (Python subset) as the sole dataset
**Decision:** Use RunBugRun, extracting only Python problems.
**Why:** It is executable, large enough to fit the reliability-score regression,
and each entry has a problem statement, buggy code, tests, and a fix — matching
our required input shape. Large size removes the overfitting risk for RQ4.
**Alternatives rejected:** BugsInPy (project-level, dependency-heavy, too slow to
set up in 2 weeks); injecting our own bugs (weaker credibility than an
established benchmark); MCP-Atlas (measures tool *usage*, not tool *correctness* —
wrong axis).

## Day 0 — Keep all three research components
**Decision:** Mutation testing (two arms), rubber-duck semantics, and MCP schema
generation are all in scope.
**Why:** This is a research project; each is an experimental arm producing a
comparative result, not optional polish.
**Alternatives rejected:** The earlier "trim to core" plan that cut them — rejected
because the supervisor wants comparative experimental results.

## Day 0 — Minimal static checks
**Decision:** S2 = bandit + mypy only.
**Why:** Their role is to be the cheap baseline that dynamic checks are compared
against (RQ2). Comprehensiveness is not the goal; the comparison is.
**Alternatives rejected:** secrets scan, pip-audit, import allowlist — deferred to
future work to protect focus and timeline.

## Day 0 — Reliability score fit from data, not hand-weighted
**Decision:** Fit a logistic regression (signals → P(correct)) on RunBugRun;
report correlation, calibration, AUC, ablation. Hard safety gates stay outside
the regression.
**Why:** A score is only meaningful if it predicts a real outcome; fitted weights
are defensible where hand-picked ones (the old 0.4/0.3/0.3) are not.
**Alternatives rejected:** Pre-declared fixed weights — kept as a fallback if the
dataset proves too small, but the large dataset makes fitting sound.

<!-- Claude Code: append new decisions below -->

## 2026-09-17 — Progress reports live in `docs/reports/`
**Decision:** Add `docs/reports/` holding the sprint plan (`SPRINTS.md`) and one
work log per sprint (`sprint-NN.md`) that records every task, command, and actual output.
**Why:** Sohaib asked that everything done be reported in a separate docs folder
and that the work be planned as sprints.
**Alternatives rejected:** Growing the MEMORY.md session log. It is meant to stay a
one-line-per-session index, not a detailed record.

## 2026-09-17 — Python 3.12 via a project `.venv`
**Decision:** Development uses `.venv` created with `py -3.12` (currently 3.12.10),
installed with `pip install -e ".[dev]"`.
**Why:** `requires-python = ">=3.12"` and CLAUDE.md §5 mandate 3.12. Only 3.11.1
was on the machine, so Sohaib installed 3.12.
**Alternatives rejected:** Lowering the target to 3.11 would contradict CLAUDE.md §5.

## 2026-09-17 — Installable package is `toolvalidator` only
**Decision:** `[tool.setuptools.packages.find] include = ["toolvalidator*"]` in
pyproject.toml. `experiments/` and `data/` are run from the repo root, not installed.
**Why:** With both `toolvalidator/` and `experiments/` as top-level packages,
setuptools' flat-layout auto-discovery refuses to build, so `pip install -e .` fails.
It also matches STRUCTURE.md: the library is `toolvalidator/`, and experiments are what you run.
**Alternatives rejected:** A `src/` layout would contradict STRUCTURE.md.

## 2026-09-17 — Pre-flight probes excluded from ruff
**Decision:** `docker_probe.py` and `mutmut_probe.py` are in ruff `extend-exclude`
and left exactly as committed.
**Why:** They are one-off diagnostic scripts, not project code. `ruff check .`
flagged 11 lint issues in them (unused `noqa`, SIM105, an unused import), which blocked the
gate. Rewriting diagnostics that haven't been run yet risks changing what they test.
**Alternatives rejected:** Auto-fixing them.

## 2026-09-17 — Gate type-checks `data/` and `experiments/` too
**Decision:** The gate is now
`ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q`
(updated in CLAUDE.md §6, START_HERE.md, README.md, pyproject.toml comment).
**Why:** The old gate (`mypy --strict toolvalidator`) never checked the RunBugRun
loader, which is on the critical path, or the experiment scripts that produce every
reported number. Confirmed by Sohaib.
**Alternatives rejected:** Keeping the documented gate.

## 2026-09-17 — Mutation arm A (mutmut) runs inside the sandbox
**Decision:** `mutation/arm_a_mutmut.py` runs `mutmut` inside the Docker sandbox
container, not on the host. The sandbox image must have mutmut available.
**Why:** mutmut executes the tool's code (and its mutants). CLAUDE.md §7 says all
tool execution happens in the container. It likely also avoids mutmut 3.x's
Windows limitations (unverified; the dev machine is Windows). Confirmed by Sohaib.
**Alternatives rejected:** Running mutmut on the host, as `mutmut_probe.py` does,
would break the sandbox rule.
**Consequence:** The `mutmut_probe.py` result on the host is not sufficient on its own.
Before task 2.7, verify mutmut also runs inside the locked-down container.

## 2026-09-17 — Skeleton commit accepts pytest exit 5 (no tests collected)
**Decision:** The Phase 0 skeleton commit is made with `pytest` exiting 5 ("no tests
ran"). Every other gate step is green. The very next commit (contracts) adds real tests.
**Why:** A placeholder smoke test would be a file outside STRUCTURE.md that exists only
to satisfy the gate for one commit.
**Alternatives rejected:** `tests/test_package.py` import smoke test.

## 2026-09-17 — Test subfolders are packages
**Decision:** Every `tests/<subpkg>/` has an empty `__init__.py`, mirroring the package.
**Why:** `tests/__init__.py` already exists (STRUCTURE.md). Making the subfolders
packages too keeps pytest's module naming unambiguous as mirrored test files are added.

## 2026-09-17 — Contract shapes (contracts.py)
**Decision:**
- Example I/O is `IOExample{input, output}` with pydantic `JsonValue` values, and
  `CapabilityRequest.examples: list[IOExample]`.
- `ValidationRecord` holds `request`, `results`, `failures`, and `verdict`
  (`None` until decided), plus `add(result) -> result`.
- `ToolArtifact` is `{tool_id, code, metadata}`. `StageResult.category` is `None` on pass.
- Every type except `ValidationRecord` is frozen, and all of them forbid extra fields.
**Why:** RunBugRun's input style (stdin vs. function-call) is still unconfirmed.
`JsonValue` covers both without a contract change later. The stage signature
`f(artifact, record, sandbox)` has no request parameter, so the record must carry
the request (S3 needs it). Freezing results supports a deterministic verdict, and
`extra="forbid"` catches typos in hand-written request JSON.
**Alternatives rejected:** Separate stdin/func example types, which would decide the
dataset format before inspecting it. Adding `score` to the record now; it waits for
S6 and will be raised as a contract change then.

## 2026-09-17 — Config: no invented defaults, no new dependency
**Decision:** `config.py` reads `SCADS_API_KEY` (as `SecretStr`), `SCADS_BASE_URL`,
`SCADS_GENERATOR_MODEL`, and `SCADS_JUDGE_MODEL` from the environment over `.env`,
using a ~20-line parser. Model IDs have no defaults, and identical generator/judge IDs are
rejected. Sandbox defaults: `python:3.12-slim`, 512m, 128 pids (from `docker_probe.py`),
10 s exec timeout. No score thresholds yet.
**Why:** Exact SCADS model IDs aren't known, so a guessed default would be invented
data (CLAUDE.md rule 7). Thresholds are fit from data in S6. `SecretStr` keeps the key out
of logs, reprs, and reports. Avoiding pydantic-settings / python-dotenv keeps the
dependency list unchanged (rule 8).
**Alternatives rejected:** pydantic-settings or python-dotenv (a new dependency for about 20 lines).
**Open:** the 10 s exec timeout is an engineering default and should be revisited once real
RunBugRun run times are measured.
