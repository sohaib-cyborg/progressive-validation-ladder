# STRUCTURE.md — Canonical Project Layout

This is the authoritative folder structure. **Do not create files outside this
layout without asking** (CLAUDE.md Rule 8). Claude Code: when adding a file, place
it here; if it doesn't fit, that's a signal to ask.

```
toolvalidator/                     # ← repo root
│
├── CLAUDE.md                      # standing orders (read automatically)
├── README.md                      # human-facing: what/why/how-to-run
├── pyproject.toml                 # deps, tool config (ruff/mypy/pytest), pinned
├── .gitignore
├── .env.example                   # SCADS_API_KEY=...  (real .env is git-ignored)
│
├── docs/
│   ├── MEMORY.md                  # durable context + session log (READ FIRST)
│   ├── PLAN.md                    # the research plan + 2-week schedule
│   ├── STRUCTURE.md               # this file
│   ├── DECISIONS.md               # append-only log of design decisions + why
│   ├── PROJECT_LOG.md             # one-file overview: architecture, timeline, results, open items
│   └── reports/                   # progress reports: what was done, commands, real output
│       ├── README.md              # index + entry format
│       ├── SPRINTS.md             # sprint plan (5 sprints over the 14 days) + risks
│       └── sprint-NN.md           # one work log per sprint
│
├── toolvalidator/                 # ← the package (the pipeline itself)
│   │
│   ├── __init__.py
│   ├── contracts.py               # ALL shared types (pydantic). The spine.
│   ├── config.py                  # settings: models, timeouts, thresholds, paths
│   ├── pipeline.py                # the state machine: runs S0→S7, short-circuits
│   ├── cli.py                     # thin entry point (argparse). NO logic here.
│   │
│   ├── stages/                    # one file per stage; each: f(artifact,record,sandbox)->StageResult
│   │   ├── __init__.py
│   │   ├── s0_provision.py        # S0: create/destroy the Docker sandbox
│   │   ├── s1_parse.py            # S1: ast.parse; SyntaxError → reject
│   │   ├── s2_static.py           # S2: bandit (danger) + mypy (types)  [minimal]
│   │   ├── s3_testgen.py          # S3: orchestrates generation + judging
│   │   ├── s4_execute.py          # S4: run tool vs tests IN sandbox (stdin or typed call)
│   │   ├── harness.py             # the scripts that run inside the container + text compare
│   │   ├── compare.py             # structural comparison of typed outputs
│   │   ├── s5_mutation.py         # S5: mutation testing, dispatches to both arms
│   │   ├── s5b_rubberduck.py      # S5b: LLM explains code → semantic signal
│   │   ├── s6_score.py            # S6: assemble signals → reliability score
│   │   └── s7_mcp_schema.py       # S7: generate MCP JSON schema for accepted tools
│   │
│   ├── sandbox/                   # Docker isolation (the safety boundary)
│   │   ├── __init__.py
│   │   ├── Dockerfile             # sandbox image: python:3.12-slim + numpy + mutmut (pinned)
│   │   ├── container.py           # provision/destroy, resource limits, caps
│   │   └── exec.py                # run a script in the container, capture out/err/exit
│   │
│   ├── testgen/                   # test generation subsystem (S3's guts)
│   │   ├── __init__.py
│   │   ├── generator.py           # LLM generator: request+code → typed test cases
│   │   ├── judge.py               # independent LLM judge: is this test valid? (blind to code)
│   │   └── schemas.py             # Pair, Property types for generated tests
│   │
│   ├── mutation/                  # S5's two arms (the RQ3 comparison)
│   │   ├── __init__.py
│   │   ├── arm_a_mutmut.py        # real mutation testing (systematic)
│   │   ├── arm_b_llm.py           # LLM-invented mutants
│   │   └── kill.py                # run surviving tests vs mutants → kill rate
│   │
│   ├── scoring/                   # S6's guts (the reliability score)
│   │   ├── __init__.py
│   │   ├── signals.py             # Signal type; collect signals from a record
│   │   └── model.py               # the fitted logistic regression + calibration
│   │
│   ├── prompts/                   # versioned prompt registry (docs/PROMPTS.md is generated)
│   │   ├── __init__.py            # REGISTRY + lookup + markdown_catalogue
│   │   ├── spec.py                # PromptSpec + the docs renderer
│   │   ├── testgen.py             # generate_tests@v1, judge_test@v1
│   │   └── rubberduck.py          # explain_code@v1, compare_explanation@v1 (S5b)
│   │
│   ├── llm/                       # SCADS client (the only place network-to-LLM lives)
│   │   ├── __init__.py
│   │   ├── scads_client.py        # sync, retry, typed LLMResult, defensive JSON parse
│   │   ├── trace.py               # one JSONL row per call: provenance, tokens, latency
│   │   └── replay.py              # re-derive a result offline from a trace
│   │
│   └── repair.py                  # builds FailureReport (repair signals) from a record
│
├── data/                          # datasets (git-ignored if large; loaders are not)
│   ├── loaders/
│   │   ├── __init__.py
│   │   └── runbugrun.py           # RunBugRun (Python subset) → CapabilityRequest+tool+tests+label
│   └── runbugrun_py/              # the extracted Python problems (git-ignored)
│
├── experiments/                   # THE DELIVERABLE — each produces numbers/figures
│   ├── __init__.py
│   ├── common.py                  # shared: load dataset, run pipeline over it, save results
│   ├── run_static_vs_dynamic.py   # RQ1/RQ2: the headline comparison
│   ├── run_testgen_strategies.py  # RQ3: generator/mutation-A/mutation-B/rubberduck
│   ├── fit_reliability_score.py   # RQ4: fit regression, correlation, calibration, ablation
│   ├── run_mcp_accuracy.py        # RQ5: schema accuracy vs reference
│   └── run_judge_independence.py  # (optional) same-family vs cross-family judge
│
├── results/                       # experiment outputs: json + figures (git-ignored)
│   └── .gitkeep
│
├── examples/                      # tiny hand-made tools for smoke tests
│   ├── celsius.py                 # a correct tool
│   ├── celsius.json               # its Capability Request
│   └── broken_celsius.py          # a wrong one (for testing the reject path)
│
└── tests/                         # pytest — MIRRORS the package structure
    ├── __init__.py                # (each tests/<subpkg>/ also has an empty __init__.py)
    ├── conftest.py                # fixtures: fake sandbox, sample records, tmp containers
    ├── test_contracts.py
    ├── test_pipeline.py
    ├── stages/
    │   ├── test_s0_provision.py
    │   ├── test_s1_parse.py
    │   ├── test_s2_static.py
    │   ├── test_s3_testgen.py
    │   ├── test_s4_execute.py
    │   ├── test_s5_mutation.py
    │   ├── test_s5b_rubberduck.py
    │   ├── test_s6_score.py
    │   └── test_s7_mcp_schema.py
    ├── sandbox/
    │   ├── test_container.py
    │   └── test_exec.py
    ├── testgen/
    │   ├── test_generator.py
    │   └── test_judge.py
    ├── mutation/
    │   ├── test_arm_a_mutmut.py
    │   ├── test_arm_b_llm.py
    │   └── test_kill.py
    └── scoring/
        ├── test_signals.py
        └── test_model.py
```

## Layout principles

- **`toolvalidator/` is the library; `experiments/` is what you run.** Keep them
  separate: the pipeline never imports from `experiments/`, but experiments import
  the pipeline.
- **`contracts.py` is the spine** — every module depends on it; it depends on
  nothing internal. Change it deliberately.
- **`tests/` mirrors the package** — file `toolvalidator/stages/s4_execute.py` →
  test `tests/stages/test_s4_execute.py`. Always.
- **`cli.py` and `experiments/*` are thin** — they wire things together and call
  the library. No business logic lives in an entry point.
- **The only place that talks to the LLM network is `llm/scads_client.py`.** Every
  other module calls *that*, so there's one choke point to mock in tests.
- **The only place that runs untrusted code is `sandbox/`.** Same reason:
  one boundary, easy to audit.

## Where things go (quick reference for Claude Code)

| If you're adding… | Put it in… |
|---|---|
| a new pipeline stage | `toolvalidator/stages/sN_*.py` + test |
| a shared type | `toolvalidator/contracts.py` |
| a config value (model, threshold) | `toolvalidator/config.py` |
| an LLM prompt/call | the relevant subsystem (`testgen/`, `mutation/`, `s5b_`), calling `llm/` |
| dataset parsing | `data/loaders/` |
| an experiment | `experiments/run_*.py` |
| a throwaway smoke tool | `examples/` |
| anything that doesn't fit above | **stop and ask** (CLAUDE.md Rule 8) |
