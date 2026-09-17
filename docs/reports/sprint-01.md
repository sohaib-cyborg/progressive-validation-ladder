# Sprint 1 Work Log: The Spine (Days 1–2)

Plan and exit criteria: [SPRINTS.md](SPRINTS.md#sprint-1-the-spine-days-12).
All command output below is copied from real runs, trimmed but never edited.

---

### Pre-work: read docs, check environment  (2026-09-17)
**Status:** done
**What was done:**
- Read CLAUDE.md, docs/MEMORY.md, START_HERE.md, docs/STRUCTURE.md, docs/PLAN.md,
  pyproject.toml, .gitignore, docs/DECISIONS.md, both probe scripts.
- Found: git root was the home directory (Sohaib then created a repo in the project
  folder), only Python 3.11.1 was installed, and the Docker daemon was not running.
- Flagged doc inconsistencies: PLAN.md marks S0–S3 as "built" (stale after the fresh
  start). MEMORY.md Day 0 says a package skeleton existed, but it did not.
**Commands run + actual output:**
```
$ py -0p
 -V:3.11 *        C:\Program Files\Python311\python.exe
$ docker info
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine ...
```
**Decisions:** asked Sohaib three questions → Python 3.12 install, mutmut in sandbox,
wider mypy gate (see DECISIONS.md 2026-09-17 entries).

---

### 1.1: Project skeleton  (2026-09-17)
**Status:** done
**What was done:**
- Sohaib installed Python 3.12. Created `.venv` with `py -3.12 -m venv .venv` and
  installed with `pip install -e ".[dev]"`.
- Created package tree per STRUCTURE.md (16 empty `__init__.py` + `results/.gitkeep`).
- pyproject: setuptools discovery limited to `toolvalidator*`, probes excluded from ruff.
- .gitignore: `results/` → `results/*` + `!results/.gitkeep` (the old rule ignored the
  `.gitkeep` STRUCTURE.md requires).
- Created `docs/reports/` (this folder) + sprint plan. Widened gate in CLAUDE.md,
  START_HERE.md, README.md.
**Commands run + actual output:**
```
$ .venv/Scripts/python.exe --version
Python 3.12.10
$ ruff --version; mypy --version; pytest --version
ruff 0.16.8 / mypy 2.3.1 (compiled: yes) / pytest 9.1.1
$ pip list  (project deps)
bandit 1.9.4, docker 7.2.0, mutmut 3.8.0, numpy 2.5.3, openai 3.14.1,
pydantic 2.13.5, scikit-learn 1.9.1, toolvalidator 0.1.0 (editable)

# first gate run:
$ ruff check .
Found 11 errors.   ← all in docker_probe.py / mutmut_probe.py (RUF100, SIM105, F401)
# → restored probes with `git checkout`, excluded them from ruff (DECISIONS.md)

# gate after fix:
$ ruff format .      → 24 files left unchanged
$ ruff check .       → All checks passed!
$ mypy --strict toolvalidator data experiments
pyproject.toml: note: unused section(s): module = ['bandit.*', 'docker.*', 'mutmut.*', 'sklearn.*']
Success: no issues found in 9 source files
$ pytest -q          → exit 5 (no tests collected; accepted for this commit, see DECISIONS.md)
```
**Decisions:** progress reports folder; Python 3.12 venv; package discovery; probes
excluded from ruff; wider gate; mutmut in sandbox; pytest exit 5 on skeleton; test
subfolders are packages.
**Commit:** `06f3bcd chore: project skeleton`, `3c791c5 docs: widen mypy gate to data and experiments`,
`d1d4a83 docs: add reports folder, sprint plan, and Day 1 decisions`
**Open issues / next:**
- The mypy "unused section(s)" note is expected until docker/mutmut/bandit/sklearn are
  imported. It is a note, not an error (exit 0).
- Git warns LF→CRLF on every add (global `core.autocrlf`). Harmless; no action taken.

---

### 1.2: Contracts  (2026-09-17)
**Status:** done
**What was done:**
- Wrote `tests/test_contracts.py` first (17 tests: construction, validation errors,
  immutability, unknown-field rejection, JSON round-trip, `record.add`).
- Confirmed it failed before implementation, then wrote `toolvalidator/contracts.py` (82 lines).
**Commands run + actual output:**
```
$ pytest -q tests/test_contracts.py     (before implementation)
E   ModuleNotFoundError: No module named 'toolvalidator.contracts'
$ ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q
26 files left unchanged
All checks passed!
Success: no issues found in 10 source files
.................                                                        [100%]
gate exit=0
```
**Decisions:** DECISIONS.md "Contract shapes (contracts.py)".
**Commit:** `0fdefa3 contracts: add pipeline spine types`

---

### 1.3: Config  (2026-09-17)
**Status:** done
**What was done:**
- Wrote `tests/test_config.py` first (9 tests), confirmed it failed, then wrote
  `toolvalidator/config.py` (91 lines).
- Added `SCADS_GENERATOR_MODEL` / `SCADS_JUDGE_MODEL` (empty) to `.env.example`.
- Verified the real `.env` parses (printed key names only, never values).
**Commands run + actual output:**
```
$ pytest -q tests/test_config.py        (before implementation)
ERROR tests/test_config.py   (collection error: module missing)
$ ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q
1 file reformatted, 27 files left unchanged
All checks passed!
Success: no issues found in 11 source files
..........................                                               [100%]
gate exit=0
$ python -c "...load_settings()..."
keys in .env: ['SCADS_API_KEY', 'SCADS_BASE_URL']
api_key set: True | base_url: https://llm.scads.ai/v1 | generator_model: None | judge_model: None
```
**Decisions:** DECISIONS.md "Config: no invented defaults, no new dependency".
**Commit:** `895d87f config: load settings from environment and .env`
**Open issues / next:**
- SCADS model IDs are not set in `.env`. Needed before Sprint 2 (task 2.1), not before.

---

### Contracts: Sandbox protocol  (2026-09-17)
**Status:** done
**What was done:** Sohaib approved the contract change ("ok proceed"). Tests first (4 new
tests + `tests/conftest.py` with `FakeSandbox`, `record` fixtures), confirmed failing
(`ImportError: cannot import name 'ExecResult'`), then added `ExecResult`, `Sandbox`,
`Stage` to `contracts.py`.
**Commands run + actual output:**
```
$ docker version   → client 29.6.1; "failed to connect to the docker API ... dockerDesktopLinuxEngine"
$ <gate>  → 30 files left unchanged / All checks passed! / Success: no issues found in 11 source files / 30 passed, gate exit=0
```
**Decisions:** DECISIONS.md "Sandbox is a Protocol in contracts.py".
**Commit:** `37c034c contracts: add Sandbox protocol, ExecResult, and Stage type`

---

### 1.7: S1 parse  (2026-09-17)
**Status:** done
**What was done:** Probed `ast.parse` edge cases on 3.12.10 before writing tests.
Tests first (8), confirmed failing, then implemented `stages/s1_parse.py`. First gate
run failed on mypy (dict invariance, `dict[str, int | str]` vs `dict[str, JsonValue]`),
which was fixed by annotating as `JsonValue`.
**Commands run + actual output:**
```
$ python -c "<ast.parse edge cases>"
empty: OK
null byte: SyntaxError: source code string cannot contain null bytes | lineno=None
deep parens: SyntaxError: too many nested parentheses (<unknown>, line 1) | lineno=1
deep unary: MemoryError: Parser stack overflowed - Python source too complex to parse | lineno=None
indent: IndentationError: expected an indented block after function definition on line 1 (<unknown>, line 2) | lineno=2
bad token: SyntaxError: invalid syntax (<unknown>, line 1) | lineno=1
$ <gate, 1st>  → s1_parse.py:28: error: Argument "data" to "StageResult" has incompatible type "dict[str, int | str]" ... [arg-type]
$ <gate, 2nd>  → Success: no issues found in 12 source files / 38 passed, gate exit=0
```
**Decisions:** DECISIONS.md "S1 parse: parser overflow is a failure; empty code passes".
**Commit:** `b9ff485 stages: add S1 parse`
**Open issues:** an empty tool passes S1 (and is ACCEPTED by static-only config).

---

### 1.8: S2 static  (2026-09-17)
**Status:** done
**What was done:**
- Probed real bandit JSON and mypy output on a scratch file before writing parsers.
- Found that bandit rates `eval`/`exec`/`pickle` only MEDIUM. Asked Sohaib: keep HIGH
  threshold but configurable, and record all findings. Asked about mypy mode: default +
  `--check-untyped-defs`.
- Found and verified that in-process mypy picked up the repo's strict config, and
  fixed it with `--config-file=`.
- Config commit (bandit severity setting, 2 tests), then S2 tests first (12, calling
  real bandit and mypy), confirmed failing, implemented `stages/s2_static.py` (138 lines).
**Commands run + actual output:**
```
$ python -m bandit -f json -q high.py   (scratch file; line, test_id, severity, confidence)
3 B602 HIGH HIGH - subprocess call with shell=True identified, security issue.
4 B605 HIGH HIGH - Starting a process with a shell, possible injection detected, security
5 B102 MEDIUM HIGH - Use of exec detected.
6 B324 HIGH HIGH - Use of weak MD5 hash for security. Consider usedforsecurity=False
  (line 7, __import__("os").popen(cmd): no finding)
$ python -m bandit ... tool.py   → eval(input()) B307 MEDIUM/HIGH; pickle.loads B301 MEDIUM/HIGH;
                                   subprocess.call("ls", shell=True) B602 LOW/HIGH
timings: bandit subprocess 0.30s 0.30s 0.29s | mypy subprocess (warm cache) 0.26s 0.25s 0.27s |
         mypy in-process api 0.20s 0.05s 0.05s
$ mypy.api.run(<flags> untyped.py) without --config-file (cwd = repo root)
untyped.py:1: error: Function is missing a type annotation  [no-untyped-def]
$ ... with --config-file=   → ('', '', 0)
$ untyped2.py with --check-untyped-defs → errors on lines 2 and 5; without → only line 5
$ <gate>  → Success: no issues found in 13 source files / 52 passed, gate exit=0
  slowest: 1.66s test_clean_code_passes (cold mypy cache), others ~0.5s
```
**Decisions:** DECISIONS.md "S2 static: bandit threshold, mypy mode, how analyzers run".
**Commit:** `ff6b5a8 config: add configurable bandit reject severity`,
`48a9351 stages: add S2 static (bandit gate + mypy soft signal)`

---

### 1.9: repair + pipeline  (2026-09-17)
**Status:** done
**What was done:** `repair.py` (4 tests), pulled forward in minimal form because the
pipeline must record a FailureReport. First version used a `type: ignore`, which was
replaced by a narrowing helper. Then `pipeline.py` (8 tests: fake stages for
short-circuit/order/errors, plus real S1+S2 via `static_stages`).
**Commands run + actual output:**
```
$ <gate> (repair)   → Success: no issues found in 14 source files / 56 passed, gate exit=0
$ <gate> (pipeline) → Success: no issues found in 15 source files / 64 passed, gate exit=0
```
**Decisions:** DECISIONS.md "Minimal repair.py pulled forward", "Pipeline semantics before S6".
**Commit:** `ac6c2e8 repair: build FailureReport from a failed StageResult`,
`509da24 pipeline: add stage runner with short-circuit to REJECT`

---

### 1.10: CLI + smoke examples  (2026-09-17)
**Status:** done
**What was done:** `NoExecutionSandbox` in `sandbox/exec.py` (2 tests). CLI tests
first (5), then `examples/celsius.py`, `examples/broken_celsius.py` (logic bug),
`examples/celsius.json`, `toolvalidator/cli.py`. Replaced an `assert` in the CLI with an
explicit check. Ran the documented smoke command.
**Commands run + actual output:**
```
$ <gate> (exec)  → Success: no issues found in 16 source files / 66 passed, gate exit=0
$ <gate> (cli)   → Success: no issues found in 17 source files / 71 passed, gate exit=0
$ python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json
... "results": [ {"stage": "s1_parse", "passed": true, ...},
                 {"stage": "s2_static", "passed": true, ..., "data": {"bandit": [], "mypy": [], "mypy_error_count": 0}} ],
"failures": [], "verdict": "ACCEPT"
exit=0
$ python -m toolvalidator.cli validate --tool examples/broken_celsius.py --request examples/celsius.json
  "verdict": "ACCEPT"
exit=0      ← expected: static-only checks cannot see the logic bug (RQ2)
```
**Decisions:** DECISIONS.md "NoExecutionSandbox for static-only runs", "CLI contract and smoke examples".
**Commit:** `77158bd sandbox: add NoExecutionSandbox for static-only runs`,
`3573a6f cli: add validate command and smoke examples`

---

### Sprint 1 status at end of Day 1  (2026-09-17)
| Task | Status |
|---|---|
| 1.1 skeleton, 1.2 contracts, 1.3 config | ✅ done |
| 1.7 S1, 1.8 S2, 1.9 pipeline (+ repair), 1.10 CLI | ✅ done: static pipeline runs end-to-end, 71 tests, gate green |
| 1.4 loader | ⛔ blocked: a real RunBugRun Python entry has not been inspected, so the input style is unknown |
| 1.5–1.6 Docker sandbox | ⛔ blocked: `docker_probe.py` not run. Docker Desktop daemon still not running (`docker version` at 2026-09-17) |

**New risk found:** static-only cost. Measured ~0.30 s (bandit) + ~0.05 s (mypy)
per tool on small scratch files. Estimate, not a measurement: 145,400 tools × ~0.35 s ≈
14 h serial for the static-only run alone (task 2.6). Needs a subsampling or
parallelism decision before 2.6 (added as R7 in SPRINTS.md).
