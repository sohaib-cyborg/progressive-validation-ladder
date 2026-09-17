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

### Blocked: remaining Sprint 1 tasks  (2026-09-17)
| Task | Blocked on |
|---|---|
| 1.4 loader | ⛔ A real RunBugRun Python entry has not been inspected, so the input style is unknown |
| 1.5–1.6 sandbox | ⛔ `docker_probe.py` not run. Docker Desktop daemon was not running at session start |
| 1.7–1.9 S1, S2, pipeline | Stage signature needs a `sandbox` parameter type, which doesn't exist yet. Awaiting a decision (see session summary) |
