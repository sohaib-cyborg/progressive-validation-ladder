# Project D — Status Report

**As of:** 2026-09-17 (Day 1 of the 14-day plan) · **Branch:** main · **Gate:** green
(`ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q`)

A snapshot of what exists, how it works, what has actually been run, and what the
numbers say so far. Every number below comes from a real run; nothing is estimated
unless it says "estimate". Detailed per-task logs: [sprint-01.md](sprint-01.md),
[sprint-02.md](sprint-02.md). Decisions with rationale: [../DECISIONS.md](../DECISIONS.md).

---

## 1. What the system does today

A tool (a Python program) plus a Capability Request (task description + example I/O)
goes through staged checks and comes out with a verdict, ACCEPT or REJECT:

| Stage | What it does | Status |
|---|---|---|
| S1 parse | `ast.parse`; syntax errors and parser overflow → REJECT | ✅ built |
| S2 static | bandit (dangerous calls, hard gate) + mypy (type errors, soft signal) | ✅ built |
| S3 test-gen | generator proposes tests, independent judge filters them | ✅ built (not yet run at scale) |
| S4 execute | runs the tool against tests **inside the sandbox** | ✅ built |
| S5 mutation | mutation testing, two arms | ❌ not built |
| S5b rubber-duck | LLM explains the code; compare to the description | ❌ not built |
| S6 score | reliability score fit from data | ❌ not built |
| S7 MCP schema | generate an MCP JSON schema | ❌ not built |

Supporting parts that exist: the pipeline state machine, contracts, settings, the
RunBugRun loader, the Docker sandbox (container + execution), the SCADS LLM client,
repair signals, a CLI, and one experiment runner.

**Size:** 1,786 lines of library + loader + experiment code, 2,138 lines of tests.
*(Debt: `stages/s4_execute.py` is 238 lines, over the ~200-line smell threshold in
CLAUDE.md §2. It should be split, probably harness vs. stage logic.)*

---

## 2. Methodology (what a reader of the report needs to know)

### 2.1 Dataset
- **RunBugRun**, Python subset: 145,370 entries (`train` 133,705 · `valid` 2,054 · `test` 9,611).
  Each entry = one problem, a **buggy** and a **fixed** version of a real submission,
  and fine-grained bug-type labels.
- **Programs are stdin/stdout scripts**, not function-call APIs (2,032/2,054 of the valid
  split read stdin; only 295 contain a `def`; median 10 lines).
- **Tests:** RunBugRun ships 321,418 stdin→stdout test cases, linked by problem
  (median ~103 per problem in the valid split).
- **Problem statements are NOT in RunBugRun.** They come from IBM Project CodeNet
  (`problem_descriptions.tar.gz`), covering 3,924 of the 3,926 problems that have tests.
  The Capability Request is: name = problem id, description = statement text,
  examples = the "Sample Input/Output" pairs parsed from that statement.
- **Held-out pool for experiments:** `valid` + `test` = 11,665 entries. The `train`
  split is untouched so far.
- **Framing (unchanged from PLAN.md):** these are human-written bugs used as a proxy
  for LLM-synthesized tool errors, stated explicitly in the report.

### 2.2 Sampling and parallelism
- Seeded sampling (`seed=20260917`), **at most 2 entries per problem** so popular
  problems cannot dominate.
- **Tier 1** (cheap: S1, S2, S4 against dataset tests): 2,000 entries = 4,000 tools.
- **Tier 2** (expensive: LLM and mutation stages): 300 entries, plus a **disjoint 50-entry
  dev set** for prompt tuning that is never reported.
- Runs are parallel: one process per worker, **a fresh container per tool**, worker count
  bounded by CPUs and Docker memory (currently 10 on a 12-CPU machine with 8 GB for Docker).

### 2.3 Isolation (every execution, without exception)
Container per tool: **network disabled**, memory and swap capped at 512 MB, 128 pids,
**all Linux capabilities dropped**, `no-new-privileges`, runs as uid 65534 (nobody),
no host mounts, force-removed afterwards. Per-test timeout (10 s) kills the whole
process group; stdout/stderr are capped with `RLIMIT_FSIZE` so a runaway print loop
cannot exhaust memory. Verified by `docker_probe.py` (ALL CHECKS PASSED) and by
8 tests that run against the real daemon.

Image: `toolvalidator-sandbox:py3.12` = `python:3.12-slim` (digest-pinned) + numpy 1.26.4
+ mutmut 3.8.0 + pytest 9.1.1. numpy is needed because 1.6% of entries import it.

### 2.4 How a program's output is judged correct
1. Trailing whitespace is ignored (5.3% of expected outputs have no trailing newline).
2. Otherwise compare token by token; **numbers are compared with a tolerance
   (`math.isclose`, rel/abs 1e-6) only when the expected answer is fractional.**
   If the task expects `1326`, then `1326.0` is wrong — that is a real bug class
   (RunBugRun labels it `type_conversion`), and tolerating it hid 4 real bugs (§4.3).
3. A test passes only if the program also exits 0 and does not time out.

### 2.5 Models (pinned, not optimised)
- **Generator:** `Qwen/Qwen3.8-27B` (~27.8B dense). May see the code as an *interface*
  reference, but the description is the specification.
- **Judge:** `zai-org/GLM-5.3` (~743B MoE, ~39B active), a different family and a
  stronger reasoner, **blind to the tool's code**. It judges tests, never tools.
- Model aliases (`alias-*`) are banned: the API reports the alias, not the model, so
  results would not be reproducible.

### 2.6 Honesty rules baked into the code
- An **analyzer or harness failure raises**; it never becomes a verdict on the tool.
  bandit/mypy crashes, sandbox failures and unreadable LLM output are infrastructure
  errors, so they cannot silently inflate the rejection rate.
- **S3 never rejects a tool**: failing to generate tests says something about the
  validator, not the code.
- The experiment records **`unusable_fixed`**: correct programs that fail their own
  dataset tests in our sandbox. That is an upper bound on label noise, reported, not hidden.
- Tests that need Docker, SCADS, or the dataset **skip with a visible reason** rather
  than passing vacuously.
- An empty stage list is an error: a tool can never be accepted without being checked.

---

## 3. Tests that have actually run

**199 tests, all passing**, run as part of the gate before every commit. 22 of them are
marked `slow` because they use real infrastructure rather than fakes.

| Area | Tests | Of which real infrastructure |
|---|---|---|
| `test_s4_execute.py` (S4 + output comparison) | 48 | 8 real Docker |
| `test_contracts.py` | 21 | — |
| `test_exec.py` (sandbox execution) | 16 | 8 real Docker |
| `test_scads_client.py` | 15 | 1 real SCADS call per role |
| `test_common.py` (experiment plumbing) | 13 | reads real dataset |
| `test_s2_static.py` | 12 | runs real bandit + mypy |
| `test_config.py` | 11 | — |
| `test_runbugrun.py` (loader) | 9 | 1 real dataset load |
| `test_schemas.py` (LLM payloads) | 9 | — |
| `test_s1_parse.py`, `test_pipeline.py` | 8 + 8 | — |
| `test_generator.py`, `test_judge.py` | 6 + 5 | 1 real LLM call each |
| `test_s3_testgen.py`, `test_cli.py` | 5 + 5 | — |
| `test_repair.py` | 4 | — |
| `test_container.py` | 3 | 1 real Docker |
| `test_run_static_vs_dynamic.py` | 1 | full experiment, 2 entries |

**What the real-infrastructure tests verify:** that the sandbox blocks network access,
runs as nobody, kills infinite loops, caps output, accepts 1.4 MB of stdin, leaves no
containers behind; that numpy is importable inside it; that bandit and mypy behave as
assumed; that the loader parses real RunBugRun entries; and that both SCADS models
answer and the judge rejects a wrong test.

**Method:** every module was written test-first. In each case the test was run and seen
to fail before the implementation existed. Three defects were caught this way that would
otherwise have reached the results: mypy silently not type-checking `data/`, in-process
mypy applying *our* strict settings to the tools under test, and the float-tolerance
problem in §4.3.

---

## 4. Results so far

All numbers are from **200 entries (400 tools)** sampled from the held-out splits,
10 workers, ~14.5 minutes per run, 0 infrastructure errors. **These are pilot numbers on
200 of 11,665 held-out entries, not the final result.** The execution arm uses the
dataset's own tests, i.e. the best case for dynamic checking; generated-test arms (RQ3)
come later.

### 4.1 Static vs. dynamic (the RQ2 comparison)

| Configuration | Buggy tools accepted (slip rate) | Correct tools rejected |
|---|---|---|
| **Static only** (parse + bandit + mypy) | **200/200 = 100%** | 0/200 = 0% |
| **Static + execution**, run 1: exact text comparison, 5 s per-test timeout | 1/200 = 0.5% | 9/200 = 4.5% |
| **Static + execution**, run 2: numeric tolerance everywhere, 10 s timeout | 5/200 = 2.5% | 4/200 = 2.0% |
| **Static + execution**, run 3 (current rule): tolerance only for fractional answers, 10 s timeout | **1/200 = 0.5%** | **4/200 = 2.0%** |

The three rows differ **only** in the output-comparison rule and the per-test timeout;
the tools, the sample and the tests are identical. The rule alone moves both rates by
percentage points, in opposite directions (§4.3).

**Static analysis caught none of the 200 bugs, in any bug category.** Per-category recall
was 0.00 for all eleven categories (call, control_flow, expression, literal, assignment,
identifier, io, misc, variable_access, function, type_conversion). That is the headline
RQ2 signal: these are logic bugs, and bandit and mypy are blind to them.

Dynamic per-category recall under the current rule (run 3) is 1.00 in every category
except `call` (0.99), including `type_conversion` (1.00), which run 2's over-broad
tolerance had dropped to 0.50.

**Run 3 is the configuration to quote.** Its 4 remaining false rejections are 3 correct
programs still too slow for a 10 s per-test limit (pass rates 0.73, 0.98, 0.98) and 1
whose expected output looks malformed upstream (entry 26394, pass rate 0.00). The single
slip is entry 451069, the buggy program that passes all 103 of its own tests.

### 4.2 Cost (measured)
- Static checks: ~0.5 s per tool (bandit ~0.30 s as a subprocess, mypy ~0.05 s in-process).
- Sandbox: ~0.3 s per run; a container costs ~8 s cold, then fractions of a second.
- **Batching matters:** 50 tests in one sandbox call = 1.32 s (~26 ms/test), versus
  ~300 ms/test with one call per test.
- End-to-end: **2.16 s per tool** at 10 workers → 400 tools in 14.5 min.
  Tier 1 (4,000 tools) is therefore roughly 2.5 hours (estimate).
- SCADS latency is highly variable: the same two trivial calls took 53 s once and 8 s later.
  Generator ~1.5 s, judge ~6 s on a one-token reply.

### 4.3 What went wrong, and what it taught us
The first run wrongly rejected 9 correct programs. Causes, found by inspecting each one:
- **3 float formatting:** expected `12.5663706144`, Python prints `12.566370614359172`.
- **4 timeouts:** correct but slow programs against a 5 s per-test limit.
- **2 output-spacing quirks**, still unexplained.

Adding a numeric tolerance and a 10 s timeout fixed 4 of those false rejections — but
**also let 4 genuinely buggy programs through**, because they print `1326.0` where `1326`
is expected (float division instead of integer division), and recall for the
`type_conversion` bug category fell to 0.5. The comparison rule now applies tolerance
only when the expected answer is fractional. Run 3 confirms that this keeps both gains:
false rejections 4 (down from 9) **and** slips back to 1, with `type_conversion` recall
restored to 1.00.

**This is a methodological result worth reporting:** the output-comparison rule is not a
detail — it moves both the slip rate and the false-rejection rate by percentage points,
in opposite directions.

### 4.4 Label noise in the dataset
- One buggy program (entry 451069) **passes all 103 of its own tests**. No validator can
  catch it; it is mislabelled or under-tested upstream.
- 4–9 of 200 "fixed" programs fail their own tests in our sandbox (`unusable_fixed`).
This is why the experiment reports that count alongside every rate.

---

## 5. Not built yet

- **S5 mutation testing** (both arms), **S5b rubber-duck**, **S6 score**, **S7 MCP schema**.
- **Four of five experiment scripts:** test-generation strategies (RQ3), the score fit
  (RQ4), MCP accuracy (RQ5), the optional judge study.
- RQ3, RQ4 and RQ5 therefore have **no results at all** yet.
- The full Tier 1 run (2,000 entries) has not been done; only 200-entry pilots.

**Known blocker for S5 arm A:** mutmut 3 produces **no mutants for module-level code**
(verified: 0 mutants for a script, 10 for the same logic inside `def main()`), and ~86%
of RunBugRun entries have no `def`. Arm A needs a script→function wrapping step, which
is a methodology choice that must be described in the report.

**Known scaling issue:** with ~100 tests per program, a program that times out on every
test costs up to 1,000 s. A per-tool time budget is needed before the 2,000-entry run.

---

## 6. Reproducing what exists

```bash
pip install -e ".[dev]"
docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox
cp .env.example .env    # SCADS_API_KEY, SCADS_GENERATOR_MODEL, SCADS_JUDGE_MODEL

# the gate (all 199 tests)
ruff format . && ruff check . && mypy --strict toolvalidator data experiments && pytest -q

# one tool, static configuration
python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json

# the RQ1/RQ2 experiment (pilot size)
python -m experiments.run_static_vs_dynamic --n 200 --out results/pilot
```

Dataset files (git-ignored) live in `data/runbugrun_py/raw/`: `python_valid0.jsonl.gz`,
`python_test0.jsonl.gz`, `tests_all.jsonl.gz`, `Manifest.json.gz`,
`problem_descriptions.tar.gz`. SHA-256 values are recorded in the sprint logs.
