# CLAUDE.md

**This file is read automatically by Claude Code at the start of every session.**
It defines how you (Claude Code) must behave while working on this project. Treat
it as standing orders. Read `docs/MEMORY.md` and `docs/PLAN.md` before writing any
code in a new session.

---

## 1. What this project is (one paragraph)

This is **Project D: a validation layer for LLM-synthesized tools.** It receives a
tool (Python code) plus a *Capability Request* (a task description with example
inputs/outputs), runs the tool through a pipeline of increasingly expensive checks
(parse → static analysis → sandboxed execution → mutation testing → semantic
check), and returns a verdict (**ACCEPT / REJECT / NEEDS_REVIEW**) with a
reliability score and structured *repair signals*. It is a **research project**:
the deliverable is experiments + a report, evaluated on the **RunBugRun** dataset
(Python subset). See `docs/PLAN.md` for the full research plan and `docs/MEMORY.md`
for durable context.

---

## 2. Golden rules (never violate)

1. **Tests first.** For every new function or module, write the test *before or
   alongside* the implementation. No production code is "done" until it has a
   passing test. Use `pytest`.
2. **Everything is typed.** Full type annotations on every function signature.
   `mypy --strict` must pass. No `Any` unless justified with a comment.
3. **No god-files.** A file over ~200 lines is a smell; a function over ~40 lines
   is a smell. Split by responsibility. One module = one job.
4. **Small, atomic commits.** One logical change per commit. Never mix a refactor
   with a feature. Commit messages: `<area>: <imperative summary>` (e.g.
   `sandbox: add container timeout handling`).
5. **Deterministic core, LLM as subroutine.** The pipeline's verdict logic is
   plain deterministic Python. LLM calls only ever *propose* things (tests,
   explanations); they never decide a verdict. Never put an LLM call in the
   control-flow that decides ACCEPT/REJECT.
6. **Every stage has the same shape.** `def stage(artifact, record, sandbox) ->
   StageResult`. It appends a `StageResult` to the record and returns it. Stages
   never raise for expected failures — they return a failed `StageResult`.
7. **Never invent data.** If a dataset field, API response, or result is missing,
   say so and stop. Do not fabricate example outputs, fake test results, or
   placeholder numbers that could be mistaken for real ones.
8. **Ask before large moves.** Before creating a new top-level module, changing
   the pipeline contract, or adding a dependency, state the plan in one sentence
   and wait for confirmation. Small stuff (a helper, a test) — just do it.

---

## 3. How to behave like a software engineer (not a code generator)

This is the part that matters most. A code generator emits plausible code. An
engineer does this:

- **Read before you write.** At the start of a task, read the relevant existing
  files fully. Never edit a file you haven't read this session. Never duplicate a
  function that already exists — search first (`grep`/`rg`).
- **Plan, then execute.** For any non-trivial task, first write a short numbered
  plan (3–6 steps) as a comment or in your reply. Then execute it step by step.
  If the plan changes mid-task, say why.
- **One thing at a time.** Finish and test one stage before starting the next. Do
  not scaffold ten empty files. Depth over breadth — a working S4 beats five
  half-built stages.
- **Verify your own work.** After writing code, run it. Run the test. Run `ruff`
  and `mypy`. Report the actual output, not "this should work." If you can't run
  it, say so explicitly.
- **Fail loudly and honestly.** If something doesn't work, or you're unsure, or
  the approach is wrong — say so directly. Do not paper over a problem with a
  hack and move on silently. A blocked task reported is better than a broken task
  hidden.
- **Leave the campsite cleaner.** If you touch a file and see something broken or
  untyped nearby, fix it or flag it. But don't scope-creep — note it, don't
  silently rewrite half the module.
- **No premature abstraction.** Don't build a framework for one use case. Write
  the concrete thing first; abstract only when the second use case actually
  appears.
- **Respect the deadline.** This is a 2-week sprint (see `docs/PLAN.md` schedule).
  When a choice is "correct but slow" vs. "good enough and fast," pick fast and
  leave a `# TODO(scope):` note. But NEVER cut corners on: the sandbox isolation,
  the determinism of the verdict, or the honesty of results.

---

## 4. The pipeline contract (do not break without asking)

The pipeline is a sequence of stages. The shared types live in
`toolvalidator/contracts.py` and must not change shape casually:

- `CapabilityRequest` — the task: name, description, example inputs/outputs.
- `ToolArtifact` — the code under test + metadata.
- `StageResult` — `{stage, passed: bool, category, detail, data}`. Every stage
  returns one.
- `ValidationRecord` — accumulates all `StageResult`s + the final verdict.
- `Verdict` — enum: `ACCEPT | REJECT | NEEDS_REVIEW`.
- `FailureReport` — the repair signal: `{stage, category, message, line}`.

**Rule:** a stage returns `passed=False` → the pipeline short-circuits to REJECT
(for hard failures) and records the `FailureReport`. Stages are pure functions of
their inputs; all state goes in the `ValidationRecord`.

---

## 5. Stack & tooling (enforced)

- **Python 3.12.** Use modern syntax (`match`, `|` unions, `list[str]` not
  `List[str]`).
- **pytest** for tests. Every module `x.py` has a `tests/test_x.py`.
- **ruff** for lint + format. Run `ruff check .` and `ruff format .` before every
  commit.
- **mypy --strict** for types. Must pass before every commit.
- **pydantic** for the contract models (validation + serialization for free).
- **Docker** (via `docker` SDK) for the sandbox. Never run untrusted tool code
  outside the container.
- Dependencies pinned in `pyproject.toml`. Adding one requires a one-line
  justification (Rule 8).

**Definition of done for any unit of work:**
`ruff check` clean · `ruff format` applied · `mypy --strict` clean · `pytest`
green · committed with a clear message.

---

## 6. Commands (the project's muscle memory)

Run these; don't guess whether code works.

```bash
# setup (once)
pip install -e ".[dev]"
docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox   # sandbox image

# the full local gate — run before every commit
ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q

# run one stage's tests
pytest tests/test_sandbox.py -q

# run the whole pipeline on one tool (smoke)
python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json

# run an experiment
python -m experiments.run_static_vs_dynamic --dataset data/runbugrun_py --out results/
```

(If a command doesn't exist yet, that's a task — create it, don't fake its
output.)

---

## 7. Safety rules specific to this project

Because we execute untrusted, possibly-broken code:

- **All tool execution happens inside the Docker sandbox.** Network off, memory
  capped, capabilities dropped, hard timeout, container destroyed after. Parsing
  and static analysis run on the host (they don't execute code); *running* the
  tool never does.
- **Never disable the sandbox for convenience.** If a test needs to run tool code,
  it runs in the container. No exceptions "just to test quickly."
- **LLM output is untrusted input.** Validate/parse it defensively. A generator
  that returns malformed JSON must be handled, not assumed well-formed.

---

## 8. Session workflow (do this every session)

1. Read `docs/MEMORY.md` (durable context) and `docs/PLAN.md` (what we're doing
   now + the schedule).
2. State which task from the plan you're picking up.
3. Write/adjust the numbered plan for that task.
4. Execute test-first, one step at a time, running the gate as you go.
5. When done: update `docs/MEMORY.md` if anything durable changed (a decision, a
   new module, a gotcha), commit, and state what's next.

**At the end of every session, leave a one-line note in `docs/MEMORY.md` under
"Session log" so the next session knows where things stand.**

---

## 9. What NOT to do (hard nos)

- Don't write code you haven't tested and claim it works.
- Don't create files outside the structure in `docs/STRUCTURE.md` without asking.
- Don't put business logic in `cli.py` — it's a thin entry point only.
- Don't let an LLM call decide a verdict.
- Don't fabricate experimental results, ever. Missing = missing.
- Don't refactor and feature-change in the same commit.
- Don't add a dependency without justifying it.
- Don't build stages you were told are later in the plan — stay on the current task.
