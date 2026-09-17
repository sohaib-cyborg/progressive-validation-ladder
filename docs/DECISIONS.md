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

## 2026-09-17 — Sandbox is a Protocol in contracts.py
**Decision:** `contracts.py` defines `ExecResult{stdout, stderr, exit_code, duration_s, timed_out}`,
a `runtime_checkable` `Sandbox` Protocol with `run(script, *, stdin="", timeout_s=None) -> ExecResult`,
and `type Stage = Callable[[ToolArtifact, ValidationRecord, Sandbox], StageResult]`.
`tests/conftest.py` provides `FakeSandbox`, which records calls and never executes anything.
**Why:** The stage signature needs a sandbox type before Docker is available. A
Protocol lets S1, S2, and the pipeline be built and tested now, and `sandbox/exec.py`
implements it later. Approved by Sohaib (contract change, CLAUDE.md rule 8).
**Alternatives rejected:** Waiting for the Docker sandbox, which would block Sprint 1 on the probe.

## 2026-09-17 — S1 parse: parser overflow is a failure; empty code passes
**Decision:** S1 maps `SyntaxError` (including `IndentationError` and null bytes) to
`syntax_error` with `data.line` / `data.error_type`. `MemoryError` / `RecursionError`
from the parser maps to `too_complex`. Empty code passes S1.
**Why:** Measured on CPython 3.12.10: `ast.parse("-"*200000 + "1")` raises
`MemoryError: Parser stack overflowed`, not SyntaxError. Without handling it, a
pathological tool would crash the pipeline (rule 6). Empty code is syntactically valid.
The spec for S1 is "SyntaxError → reject", so emptiness is left to dynamic stages.
**Open:** Under the static-only configuration an empty tool is ACCEPTED. Revisit if it
appears in RunBugRun.

## 2026-09-17 — S2 static: bandit threshold, mypy mode, how analyzers run
**Decision:**
- bandit rejects at or above `StaticSettings.bandit_reject_severity`
  (default `HIGH`, per the plan). Every finding at every severity is stored in
  `data.bandit`, so experiments can re-threshold offline. Confirmed by Sohaib.
- mypy is a soft signal only, run with `--check-untyped-defs --ignore-missing-imports
  --no-site-packages --config-file=` (empty). Confirmed by Sohaib.
- bandit runs as a subprocess (`-f json`, cwd = temp dir). mypy runs in-process via `mypy.api`.
- If an analyzer crashes, times out, or returns unreadable output, S2 raises `StaticAnalysisError`
  and does **not** return a failed StageResult.
**Why (measured 2026-09-17, bandit 1.9.4, mypy 2.3.1):**
- bandit severities: `subprocess.call(var, shell=True)` HIGH, `os.system(var)` HIGH,
  `hashlib.md5` HIGH (a false alarm for tool safety), `eval(input())` MEDIUM, `exec` MEDIUM,
  `pickle.loads` MEDIUM, `__import__("os").popen` not flagged. The threshold therefore
  materially changes RQ1/RQ2, so it is a recorded, configurable choice.
- Without `--config-file=`, in-process mypy picked up this repo's `strict = true`
  and reported "Function is missing a type annotation" on tool code. Verified, then fixed.
- `--check-untyped-defs` is needed to find `"a" + 1` inside an unannotated function
  (verified with and without the flag). `--strict` would mostly measure "is it annotated?".
- Timing per call: bandit subprocess ~0.30 s. mypy subprocess ~0.26 s vs.
  in-process ~0.05 s (warm cache), so mypy runs in-process.
- An analyzer crash is our infrastructure failing. Rejecting the tool for it would put
  false rejections into the results (rule 7, honesty).
**Alternatives rejected:** MEDIUM+ threshold (likely false rejections on RunBugRun code
using `eval(input())`). mypy `--strict`. Plain default mypy (skips untyped bodies).

## 2026-09-17 — Minimal repair.py pulled forward from Sprint 4
**Decision:** `repair.failure_report(result)` maps a failed StageResult to a
FailureReport (`message = detail`, `line = data.line` if it is a positive int, else
None; missing category → `"unspecified"`). Richer repair signals remain Sprint 4 (task 4.4).
**Why:** CLAUDE.md §4 requires a FailureReport on short-circuit, and STRUCTURE.md puts
that job in `repair.py`. Writing it in `pipeline.py` would mean moving it later.

## 2026-09-17 — Pipeline semantics before S6
**Decision:** `run_pipeline` runs stages in order. The first `passed=False` gives REJECT
plus one FailureReport, and later stages don't run. If all pass, the verdict is ACCEPT.
An empty stage list raises. A stage that doesn't add its own result to the record raises.
`static_stages(settings)` = `[s1_parse.run, partial(s2_static.run, reject_severity=…)]`.
**Why:** ACCEPT on all-pass is exactly the static-only configuration of PLAN §6.1.
NEEDS_REVIEW needs the score (S6), so there is a `TODO(scope)` in `pipeline.py`. Raising on an
empty stage list makes "accepted without any check" impossible. The record check
enforces rule 6 at runtime.

## 2026-09-17 — NoExecutionSandbox for static-only runs
**Decision:** `sandbox/exec.py` has `NoExecutionSandbox`, whose `run` raises
`ExecutionNotAllowedError`. The CLI uses it with the static stages. The Docker sandbox will
be added to the same module (task 1.6).
**Why:** The RQ1 "naive, no sandbox" and RQ2 "static-only" configurations must
never execute tool code. This makes that guaranteed, not just true today.

## 2026-09-17 — CLI contract and smoke examples
**Decision:** `python -m toolvalidator.cli validate --tool F --request R` prints the
ValidationRecord JSON. Exit codes: 0 ACCEPT, 1 REJECT, 2 usage/input error (argparse
convention), 3 NEEDS_REVIEW. `examples/broken_celsius.py` has a **logic bug**
(`c * 5/9 + 32`), not a syntax error, and the static-only CLI ACCEPTS it.
**Why:** A logic bug is the useful broken example for S4 and later stages, and it
illustrates the RQ2 gap. The reject path is tested with a temporary syntax-error file.
The Sprint 1 exit criterion in SPRINTS.md was corrected accordingly.

## 2026-09-17 — LLM models: generator Qwen3.8-27B, judge GLM-5.3
**Decision:** `SCADS_GENERATOR_MODEL=Qwen/Qwen3.8-27B`, `SCADS_JUDGE_MODEL=zai-org/GLM-5.3`.
**Why:** Sohaib's requirement: generator and reviewer differ, and the reviewer is a
bigger model with stronger reasoning. `GET /models` on SCADS (2026-09-17) no longer lists
Qwen3-Coder. A one-token call to each candidate confirmed availability and a reasoning trace.
Sizes are from public sources (vLLM recipes, Hugging Face, vendor posts), not verified by us:
Qwen3.8-27B ≈ 27.8B dense, strong coding benchmarks. GLM-5.3 ≈ 743B MoE / ~39B active,
reasoning model with adjustable effort. So the judge is from a different family (GLM vs.
Qwen) and larger in both total and active parameters.
**Alternatives rejected:**
- `openai/gpt-oss-120b`: 117B total but only ~5B active, so "bigger" is debatable.
- `deepseek-ai/DeepSeek-V4.1-Flash`: speed-tuned, ~8–16B active.
- `meta-llama/Llama-3.3-70B-Instruct`: no reasoning trace. It was the old example in MEMORY.md.
- `zai-org/GLM-5.3-Flash`: smaller than GLM-5.3.
- `alias-*`: responses report the alias, not the model, so they can't be reproduced.
- `MiniMaxAI/MiniMax-M3`: HTTP 500 at probe time.
**Risk:** GLM-5.3 is the slowest candidate (1.9 s for a one-token reply). Judge cost per test
must be measured in Sprint 2. If it's too slow, GLM-5.3-Flash keeps the family but is smaller;
that would need Sohaib's OK.

## 2026-09-17 — Capability Request descriptions come from CodeNet
**Decision:** The RunBugRun loader builds `CapabilityRequest.description` from IBM Project
CodeNet's `doc/problem_descriptions.tar.gz` (the English part), and `examples` from the
"Sample Input/Output" pairs in that HTML. RunBugRun's `tests_all` rows are the held-out
ground-truth tests. Name = `problem_id`.
**Why:** Inspection showed RunBugRun's release files contain no problem statement. PLAN.md
§7 assumed one existed. RunBugRun's own README says its problems come from CodeNet.
Coverage: 670/671 problems in `python_valid0`, 3,924/3,926 problems with tests. Using the statement's
own samples as "example I/O" matches the Capability Request contract (a task plus examples)
and keeps the ground-truth tests separate from what the generator sees.
**Alternatives rejected:** Drawing examples from `tests_all` (would leak ground truth into
the request). Proceeding without descriptions (would make RQ3, S5b, and RQ5 impossible).
**Open:** Entries whose problem has no description (≈0.05%) are skipped and counted. Check
CodeNet's terms of use before redistributing anything.

## 2026-09-17 — Commit + tag at every sprint completion
**Decision:** When a sprint's exit criteria are met, make one `sprint: complete Sprint N`
commit (SPRINTS.md status + log summary) and tag it `sprint-N`.
**Why:** Sohaib asked for commits at every sprint completion. Tags make each sprint's
state reproducible with `git checkout sprint-N`.

## 2026-09-17 — RunBugRun loader behaviour
**Decision:** `data/loaders/runbugrun.py` yields `RunBugRunEntry{entry_id, split, problem_id,
request, buggy_code, fixed_code, tests, bug_labels}`. Rows are validated with pydantic.
`labels: null` becomes `[]`. An entry is skipped, and counted in `LoadReport`, when its problem
has no (or empty) description or no tests. The description is the tag-stripped HTML text.
Samples are paired by number from `<h2|h3>` headings directly followed by `<pre>`: "Sample
Input N" and "Sample Output N" / "Output for the Sample Input N". The HTML-mandated newline
after `<pre>` is dropped. No language splitting.
**Why (inspected on real files):** No description file mixes `lang-en` and `lang-ja`
(1,503 en-only, 13 ja-only, 2,483 neither), so splitting is unnecessary. The 13 ja-only
statements are kept as-is. `labels` is null for 64/2,054 valid rows. Real valid split:
2,053/2,054 yielded (1 skipped, no description), 2,046 with ≥1 example, 2.4 s.
**Alternatives rejected:** An HTML parser dependency (BeautifulSoup etc.), unnecessary for two
regular markups.

## 2026-09-17 — Sandbox execution design (DockerSandbox)
**Decision:**
- One container per sandbox (`provision`), idling on `sleep infinity` as uid/gid 65534.
- Each `run` uploads `runner.py`, `script.py`, `stdin.txt` to `/tmp/tv-run-N/` with
  `put_archive` (owned by nobody), then `exec_run`s the runner.
- The runner (trusted code we write) starts the tool in a new session, kills the whole
  process group on timeout or completion, and caps stdout/stderr with `RLIMIT_FSIZE`.
  It prints JSON, which becomes `ExecResult`. A signal exit is reported as `128+signal`
  (a timeout gives 137).
- Upload failures, Docker API errors, and unreadable runner output raise `SandboxError`.
  They never produce a verdict.
- Root filesystem stays writable (container layer only, destroyed after). No mounts.
- New setting: `sandbox.max_output_bytes` = 1 MiB per stream.
**Why (measured on real Docker, 2026-09-17):**
- Inputs reach 1.37 MB, so environment variables or `-c` arguments can't carry stdin.
- The docker SDK's stdin attach is awkward over a Windows named pipe, and `put_archive` works.
- A capped output file stops an infinite print loop from exhausting host memory:
  a flood test was stopped at exactly the cap.
- Verified: stdin/stdout/stderr, exit codes, a 1 s timeout (killed, 137), network blocked,
  uid 65534, 1.4 MB stdin, no leftover containers.
- Cost: first container create ~8 s (cold), then ~0.25–0.33 s per run.
**Alternatives rejected:** A new container per run (too slow). `timeout`+shell pipelines
(no reliable output cap). A read-only root with tmpfs (`put_archive` can't write into
tmpfs mounts).
**Open:** No CPU quota yet (only mem/pids). A per-run cost of ~0.3 s × ~100 tests per program
is too slow for the full dataset, so S4 should batch many stdin cases into one runner call (R7).

## 2026-09-17 — Real-Docker tests skip (visibly) when the daemon is down
**Decision:** Tests that need Docker use the session fixture `docker_client`
(`tests/sandbox/conftest.py`), which calls `pytest.skip` with the reason if `ping()` fails.
They are marked `slow`.
**Why:** The gate must still run when Docker Desktop is off. `pytest -rs` shows the skip
reason, so a skipped sandbox test is never silently mistaken for a pass.

## 2026-09-17 — OPEN: sandbox image lacks numpy
**Finding:** 33/2,054 valid entries (1.6%) import `numpy`, which `python:3.12-slim` doesn't
have. Correct programs would fail in the sandbox and be mislabelled. Other non-stdlib names
seen (`fracions`, `collection`, `Math`, …) are typos, i.e. real bugs.
**Proposal (needs Sohaib's OK, since it adds a file outside STRUCTURE.md):** a small
`sandbox/Dockerfile` building `toolvalidator-sandbox:py3.12` = python:3.12-slim + pinned numpy
(+ mutmut for arm A). `SandboxSettings.image` already makes this a config change.
