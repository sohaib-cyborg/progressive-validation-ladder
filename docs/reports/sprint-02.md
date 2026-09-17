# Sprint 2 Work Log: Dynamic Signals (Days 3–5)

Plan and exit criteria: [SPRINTS.md](SPRINTS.md#sprint-2-dynamic-signals-days-35).
All command output below is copied from real runs, trimmed but never edited.

---

### 2.0: Sprint 2 preconditions: sandbox image, mutmut probe, experiment scale  (2026-09-17)
**Status:** done
**What was done:**
- Sohaib approved the sandbox image and chose "subset + parallel". He asked how to run the mutmut probe;
  I ran it inside the sandbox image myself (the command is in the session summary).
- Checked numpy API usage and machine resources, built the digest-pinned image, and switched
  the default `SandboxSettings.image` test-first (97 tests).
- Verified mutmut inside the locked-down container and found that module-level scripts produce no mutants.
**Commands run + actual output:**
```
$ numpy usage in python_valid0
entries importing numpy: 33
{'fixed uses alias removed in 1.24 (np.int etc.)': 0, 'fixed uses name removed in 2.0': 0}
$ nproc → 12 · docker info → NCPU=12 MemTotal=2056273920 (1.9 GiB) · Kernel=6.12.76-linuxkit (Hyper-V backend)
$ host RAM → 31.5 GB
$ docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox → naming to docker.io/library/toolvalidator-sandbox:py3.12 done (real 0m27.8s)
$ docker run <sandbox flags> toolvalidator-sandbox:py3.12 python -c "<versions>"
uid 65534 | numpy 1.26.4 | mutmut 3.8.0 | pytest 9.1.1
$ docker run <sandbox flags> -i toolvalidator-sandbox:py3.12 python - < mutmut_probe.py
[ok] mutmut generated and ran mutants on a single function.
 ALL GOOD — mutmut works for S5 (drive it via subprocess).
probe exit=0
$ manual check (add(a, b) + one test)
mutmut run exit: 0 · run tail: '⠦ 1/1  🎉 1 🫥 0  ⏰ 0  🤔 0  🙁 0  🔇 0  🧙 0', '34.52 mutations/second'
mutmut results: tool.x_add__mutmut_1: killed
$ module-level vs. function
module-level script: run exit 1 | mutants listed: 0 | [] · tail: 'failed to collect stats. runner returned 2'
same logic wrapped in main(): run exit 1 | mutants listed: 10 | 'tool.x_main__mutmut_1: not checked', ...
$ <gate> → Success: no issues found in 19 source files / 97 passed, 0 skipped · leftover containers: 0
```
<sandbox flags> = `--rm --network none --memory 512m --memory-swap 512m --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges --user 65534:65534`
**Decisions:** DECISIONS.md "Sandbox image", "mutmut verified in the sandbox; module-level
scripts yield no mutants", "Experiment scale: seeded subsets + parallel sandboxes".
**Commit:** `29cf054 sandbox: add pinned sandbox image with numpy and mutmut`
**Open issues / next:** Docker Desktop memory is 1.9 GiB, so 3 parallel sandboxes (Sohaib to raise
it to 8 GB). Next task: 2.1 LLM client.

---

### 2.1: SCADS LLM client  (2026-09-17)
**Status:** done
**What was done:** Tests first (15: role→model resolution, result mapping, missing key/model,
empty output, JSON extraction incl. fenced/embedded/malformed, 1 real SCADS call per role),
confirmed failing, implemented `toolvalidator/llm/scads_client.py`. Added `LLMSettings.timeout_s`
(300 s) and `max_retries` (3). mypy caught untyped `messages` and an un-narrowed `content`, both fixed.
One test was wrong (a literal newline inside a JSON string); the parser was right to reject it,
so the test now asserts that rejection explicitly.
**Commands run + actual output:**
```
$ pytest tests/llm (before impl) → ModuleNotFoundError: No module named 'toolvalidator.llm.scads_client'
$ <gate, 1st> → scads_client.py:61 [arg-type] messages · scads_client.py:72 [arg-type] content
$ <gate> → Success: no issues found in 20 source files / 112 passed
  slowest: 53.06s (first real call pair) → 8.44s on the next run
$ ScadsClient(load_settings().llm).complete(role, "Reply with exactly: OK")
generator Qwen/Qwen3.8-27B 1.5s completion_tokens= 16 reasoning chars= 46 content= '\n\nOK'
judge zai-org/GLM-5.3 6.0s completion_tokens= 35 reasoning chars= 138 content= 'OK'
```
**Finding:** SCADS latency varies a lot (the same two trivial calls took 53 s once, 8 s later).
Tier 2 LLM cost must be measured on real prompts before fixing its size.
**Commit:** `b441c3b llm: add SCADS client with role-pinned models and defensive JSON parsing`
