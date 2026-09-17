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

---

### Pre-flight: Docker probe, SCADS models, RunBugRun inspection  (2026-09-17)
**Status:** done
**What was done:**
- Sohaib started Docker Desktop and ran `docker_probe.py`. The pasted output stopped
  before the final banner, so I re-ran it to confirm.
- Listed SCADS models, sent a one-token call to 12 candidates, looked up public
  model sizes, and chose generator/judge (DECISIONS.md). Appended both IDs to `.env`
  without reading the file (key never printed).
- Downloaded and inspected RunBugRun release files + CodeNet problem descriptions into
  `data/runbugrun_py/raw/` (git-ignored).
**Commands run + actual output:**
```
$ python docker_probe.py
[ok] Docker daemon reachable ... [ok] Network correctly blocked (inside process failed, exit=1)
[ok] Runaway container killed on timeout
 ALL CHECKS PASSED — sandbox config works on this machine.
probe exit=0

$ GET https://llm.scads.ai/v1/models   → count: 23
$ one-token chat call per model (served_as | latency | reasoning trace):
alias-code            -> alias-code  0.4s  trace=True     (alias: underlying model hidden)
alias-huge            -> HTTP 503 temporarily unavailable
Qwen/Qwen3.8-27B      -> 0.4s trace=True
openai/gpt-oss-120b   -> 1.4s trace=True
zai-org/GLM-5.3       -> 1.9s trace=True
zai-org/GLM-5.3-Flash -> 0.4s trace=True
deepseek-ai/DeepSeek-V4.1-Flash -> 0.4s trace=True
MiniMaxAI/MiniMax-M3  -> HTTP 500 InternalServerError
meta-llama/Llama-3.3-70B-Instruct -> 1.8s trace=False
google/gemma-4-26B-A4B-it -> 1.4s trace=False
$ load_settings() → api_key set: True | generator: Qwen/Qwen3.8-27B | judge: zai-org/GLM-5.3

$ downloads (github.com/giganticode/run_bug_run_data release v0.0.1; IBM/Project_CodeNet)
sha256 16e69d44…8d75  python_valid0.jsonl.gz   264,305 B
sha256 2fab824c…0d96  tests_all.jsonl.gz    20,539,859 B
sha256 c91c3026…1d34  Manifest.json.gz           1,341 B
problem_descriptions.tar.gz  3,492,211 B (3,999 HTML files)
Manifest python sizes: test0 9,611 · train0 50,000 · train1 50,000 · train2 33,705 · valid0 2,054 = 145,370
python_valid0: 2,054 rows · 671 problems · keys id, buggy_submission_id, fixed_submission_id,
  problem_id, user_id, buggy_code, fixed_code, labels, change_count, line_hunks, errors
  errors present: 481/2054 · labels None: 64 · uses input()/stdin: 2032/2054 · contains def: 295
  buggy LOC min/median/p90/max: 1 / 10 / 27 / 277
  label prefixes: call 1279, expression 841, control_flow 739, literal 535, assignment 451,
  identifier 408, io 326, misc 87, variable_access 76, function 16, type_conversion 2
tests_all: 321,418 rows {id, problem_id, input, output} · 3,926 problems ·
  valid problems with tests 671/671 · tests per valid problem min 1 / median 103 / max 132
descriptions: valid problems covered 670/671 · problems-with-tests covered 3,924/3,926
  markup: lang-en span 625 · <h3>Sample Input 624 · <H2>Sample Input 43 · no Sample Input 3
```
**Decisions:** DECISIONS.md "LLM models", "Capability Request descriptions come from CodeNet",
"Commit + tag at every sprint completion".
**Open issues / next:** `mutmut_probe.py` has not been run yet (needed before 2.7, inside the
sandbox). Next: 1.4 loader, 1.5 container, 1.6 exec, then the Sprint 1 completion commit + tag.

---

### 1.4: RunBugRun loader  (2026-09-17)
**Status:** done
**What was done:** Checked the real HTML first (language spans, sample markup). The initial
test fixture assumed a bilingual en+ja layout that does not occur in the data and was
corrected before implementing. Tests first (9, incl. one real-data test that skips if raw
files are absent), confirmed failing, implemented `data/loaders/runbugrun.py` (177 lines).
A literal NBSP was written into a regex, caught by ruff RUF001, and replaced with an ASCII escape.
**Commands run + actual output:**
```
$ lang span ordering over all 3,999 description files
{'none': 2483, 'has 入力例': 469, 'heading not directly followed by pre, then Sample': 0, 'en only': 1503, 'ja only': 13}
$ pytest tests/data (before impl) → ModuleNotFoundError: No module named 'data.loaders.runbugrun'
$ <gate> → Success: no issues found in 18 source files / 80 passed, gate exit=0
$ iter_entries(raw, split="valid")
valid: LoadReport(read=2054, yielded=2053, skipped_no_description=1, skipped_no_tests=0) in 2.4s
entries with >=1 example: 2046 / 2053 · distinct problems: 670
p02718 examples: [('4 1\n5 4 2 1\n', 'Yes\n'), ('3 2\n380 19 1\n', 'No\n')] · tests: 132
$ tests_all output endings
{'total': 321418, 'ends with \n': 304310, 'ends with space/tab': 1008, 'contains \r': 0, 'empty': 8}
```
**Decisions:** DECISIONS.md "RunBugRun loader behaviour".
**Commit:** `eae235e data: RunBugRun Python loader`

---

### 1.5–1.6: Sandbox container + DockerSandbox  (2026-09-17)
**Status:** done
**What was done:**
- Measured test I/O sizes and third-party imports.
- Prototyped the runner design against real Docker in the scratchpad.
- Implemented test-first: `max_output_bytes` setting (1 test assertion),
  `sandbox/container.py` (3 tests incl. 1 real Docker), `DockerSandbox` in `sandbox/exec.py`
  (14 tests incl. 7 real Docker). One lint fix (runner line > 100 chars).
**Commands run + actual output:**
```
$ sizes over tests_all
input bytes  median/p99/max: 24 710 1374658
output bytes median/p99/max: 5 200 180253
valid entries importing non-stdlib modules: 38 / 2054
non-stdlib modules: [('numpy', 33), ('fraction', 1), ('fracions', 1), ('future_builtins', 1), ('Math', 1), ('collection', 1)]

$ scratchpad prototype (real Docker)
create: 7.99s
echo      exit 0 | 0.30s  {'stdout': '42\n', 'stderr': 'err\n', 'exit_code': 0, 'timed_out': False}
exit3     0.25s  exit_code 3
timeout   1.21s  exit_code 137, timed_out True, duration_s 1.002
flood     0.26s  len stdout: 1048576, exit_code 1 (write past RLIMIT_FSIZE)
network   0.58s  exit_code 1 (urlopen failed)
whoami    0.24s  '65534 65534\n'
big_stdin 0.33s  '1400000\n'
remove: 0.08s

$ <gate> (config)    → 80 passed, gate exit=0
$ <gate> (container) → Success: no issues found in 19 source files / 83 passed, no skips
$ <gate> (exec)      → Success: no issues found in 19 source files / 96 passed, no skips
  slowest: 3.33s real loader test · 1.34s real timeout test · 0.72s real network test
$ docker ps -a --filter label=toolvalidator=sandbox → leftover sandbox containers: 0
```
**Decisions:** DECISIONS.md "Sandbox execution design", "Real-Docker tests skip (visibly)",
"OPEN: sandbox image lacks numpy".
**Commit:** `817fa93 config: add sandbox max_output_bytes`, `c3bf326 sandbox: provision and
destroy the locked-down container`, `c909d58 sandbox: run scripts in the container with timeout
and output caps`

---

### Sprint 1 completion check  (2026-09-17)
**Smoke on 10 real RunBugRun entries** (scratchpad script, not part of the repo; NOT an
experimental result: 10 entries, 3 tests each, naive rstrip comparison):
```
loader: LoadReport(read=10, yielded=10, skipped_no_description=0, skipped_no_tests=0)
static  (S1+S2, NoExecutionSandbox): all 20 tools (10 buggy + 10 fixed) → ACCEPT
static: 20 tools in 9.9s
sandbox entry 7249  p00000: buggy 0/1 | fixed 1/1
sandbox entry 9080  p00001: buggy 0/3 | fixed 3/3
sandbox entry 10105 p00003: buggy 0/3 | fixed 3/3
sandbox entry 10377 p00002: buggy 0/3 | fixed 3/3
sandbox entry 10378 p00002: buggy 0/3 | fixed 3/3
sandbox entry 12337 p00007: buggy 0/3 | fixed 3/3
sandbox entry 13516 p00010: buggy 0/3 | fixed 3/3
sandbox entry 14071 p00012: buggy 3/3 | fixed 3/3
sandbox entry 14826 p00016: buggy 0/3 | fixed 3/3
sandbox entry 18669 p00028: buggy 0/3 | fixed 3/3
sandbox: 56 runs in 18.4s
leftover containers: 0
```
**Exit criteria:**
| Criterion | Status |
|---|---|
| CLI prints a verdict for `examples/celsius.py` | ✅ ACCEPT, exit 0 |
| Syntax-error tool rejected | ✅ `tests/test_cli.py::test_syntax_error_is_rejected` |
| Static pipeline on a few real RunBugRun entries | ✅ 20 tools above |
| Real sandbox executes a script | ✅ 7 real-Docker exec tests + 56 real runs above |
| Gate green | ✅ 96 passed, 0 skipped |

**Sprint 1: COMPLETE.** Tagged `sprint-1`.
**Carried into Sprint 2:** numpy sandbox image (awaiting Sohaib), `mutmut_probe.py` (not run),
subsample/parallelism decision (R7), batched runs + output normalisation in S4.
