# LLM configuration, tracing and cost

Everything about how this project calls a language model. Prompt text is in
[PROMPTS.md](PROMPTS.md) (generated from the code). Where the LLM sits in the system is
in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Roles, not models

Callers never name a model. They ask for a **role**, and the role resolves to a pinned
model id from settings:

| Role | Model (pinned 2026-09-17) | Sees the tool's code? | Job |
|---|---|---|---|
| `generator` | `Qwen/Qwen3.8-27B` | yes, as an *interface* reference | proposes test cases |
| `judge` | `zai-org/GLM-5.3` | **never** | decides whether one proposed test follows from the request |

Why these two: Sohaib's requirement was that the reviewer be a different model and a
stronger reasoner. Public figures (not verified by us): Qwen3.8-27B ≈ 27.8B dense;
GLM-5.3 ≈ 743B mixture-of-experts with ≈39B active per token, a reasoning model. So the
judge differs in family and is larger on both counts.

**`alias-*` model names are banned.** SCADS serves them, but the API reports the alias
back rather than the underlying model, so a result produced through one could not be
reproduced. `config.py` also rejects a judge equal to the generator.

The generator treating the description as truth, and the judge never seeing the code,
are the two properties that stop the tests from being written to match a buggy tool.
Tests assert both (`tests/testgen/test_judge.py`, `tests/stages/test_s3_testgen.py`).

## 2. Settings

| Setting | Env var | Default | Notes |
|---|---|---|---|
| base URL | `SCADS_BASE_URL` | `https://llm.scads.ai/v1` | OpenAI-compatible |
| API key | `SCADS_API_KEY` | none | held as `SecretStr`; never logged or printed |
| generator model | `SCADS_GENERATOR_MODEL` | none | no default: a guessed id would be invented data |
| judge model | `SCADS_JUDGE_MODEL` | none | must differ from the generator |
| timeout | — | 300 s | reasoning models can take minutes |
| retries | — | 3 | handled by the OpenAI client |
| temperature | — | 0.0 | fixed in code, not configurable |

## 3. What a call looks like

`ScadsClient.complete(role, *, system, user) -> LLMResult` sends exactly two messages
(system, then user) at temperature 0 and returns the content, the reasoning trace when
the server provides one, token counts, the **model the server actually served**, and
measured latency.

Failures are typed: `LLMError` (configuration, network, API error after retries) and
`LLMOutputError` (answered, but not usably). Neither is ever converted into a verdict —
an LLM outage must not look like a bad tool.

**Output is untrusted.** `parse_json_object` extracts the first JSON object, preferring
fenced blocks and tolerating surrounding prose; malformed output raises rather than being
repaired by guesswork. Payloads are then validated into typed models
(`GeneratedSuite`, `JudgeVerdict`), where numbers are coerced to strings (tools read
stdin), unknown keys are ignored, and a missing verdict field is a rejection, never a
default `valid=True`.

## 4. Every call is traced

`TracingClient` wraps the client and writes one JSONL row per call to
`results/<run_id>/llm_calls.<pid>.jsonl` — one file per process, so the experiment's
process pool needs no locking.

| Field | Why it is there |
|---|---|
| `run_id`, `tool_id`, `variant` | which run and which tool the call belongs to |
| `agent`, `node`, `skill`, `attempt` | where in a multi-step policy it happened |
| `prompt_id`, `prompt_version` | makes a prompt ablation possible after the fact |
| `role`, `model_requested`, `model_returned` | catches a server silently serving something else |
| `system_sha256`, `user_sha256` | identity of the request even when text is not stored |
| `system`, `user`, `content`, `reasoning` | the full exchange (can be switched off) |
| `prompt_tokens`, `completion_tokens`, `latency_s` | the cost table |
| `ok`, `error` | a failed call is recorded, then re-raised, so retries cannot hide in latency |

Context travels in a `ContextVar`, so nothing in the call path needed a new parameter.

## 5. Reproducing a result offline

`ReplayClient.from_run(run_dir)` answers `complete()` from a recorded trace, keyed by
(role, system, user), in recorded order. An unrecorded or exhausted prompt **raises
`ReplayMissError`**: it never falls back to the network and never invents a reply.
Recorded failures replay as failures.

This is what lets a published number be re-derived with no SCADS spend, and it survives
the models being rotated or the endpoint going down.

**What we do and do not claim:** temperature 0 on a hosted mixture-of-experts endpoint is
not bit-reproducible. The *procedure* is reproducible (seed, prompt version, served
model, budgets, attempt counts, all recorded); the *artifacts* are reproducible exactly,
through replay.

## 6. Cost

Measured so far (2026-09-17, one trivial call per role): generator ≈ 1.5 s, judge ≈ 6 s.
The same pair took 53 s on a cold first call, so **SCADS latency varies by an order of
magnitude** and per-prompt cost must be measured on real prompts, not extrapolated.

**Rate limits (measured 2026-09-24 from `x-ratelimit-model_per_key-*` headers, this key).**
The window is ~60 s, inferred from the reset times in 429 replies; SCADS does not document it.

| Model | Requests / window | Tokens / window |
|---|---|---|
| `Qwen/Qwen3.8-27B` (generator) | 120 | 40,000 |
| `zai-org/GLM-5.3` (judge) | **30** | **3,000** |
| `zai-org/GLM-5.3-Flash` | 60 | 10,000 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | 60 | 10,000 |
| `meta-llama/Llama-3.3-70B-Instruct` | 250 | 12,000 |
| `google/gemma-4-26B-A4B-it` | 120 | 60,000 |
| `openai/gpt-oss-120b` | 20 | 4,000 |

Measured per call on a toy task (n=1 each): S3 judge 278 tokens (3.7 s); S5b compare
1,015 tokens (45.5 s); S5b explain 486 tokens (2.5 s). Real CodeNet statements are ~10x
longer (median 1,063 chars), so real calls are larger. **The judge's 3,000-token window is
the binding constraint for every LLM experiment.** The client now waits for the stated
reset on HTTP 429 (bounded, logged; `rate_limit_waits`, `max_rate_limit_wait_s`).

SCADS publishes no price, so cost is reported in **tokens and wall-clock**. No monetary
figure appears anywhere; inventing one would breach CLAUDE.md rule 7.

Planned concurrency (not yet implemented): a global in-flight budget divided across
worker processes, with the LLM tier using fewer processes than the Docker tier because it
is latency-bound rather than CPU-bound. Rate-limit responses will show up as `ok=false`
rows so they cannot hide inside latency numbers.

## 7. Prompt versioning

A prompt is a `PromptSpec` in `toolvalidator/prompts/` with an id, a version, a role, a
purpose and a changelog. A released version is **never edited**: a change is a new object
beside it, so "v1 vs v2" is a real comparison rather than a re-run. Both ids appear on
every trace row, and `docs/PROMPTS.md` is generated from the registry with a test that
fails on drift.
