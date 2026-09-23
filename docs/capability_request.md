# Capability Requests

This document explains the project end to end, with a focus on the
`CapabilityRequest` schema: what it contains, how it is produced, how gold
requests are built, and how generated requests are evaluated.

For setup and a full file-by-file guide, see [KNOWLEDGE.md](../KNOWLEDGE.md) and
the main [README.md](../README.md).

---

## 1. Project in one paragraph

When a tool-using AI agent fails, the cause is sometimes that **no available
tool can do what the task needs**. This is a **capability gap** (label F6). Given
a user task, the agent's available tools, and its execution trace, the system:

1. Works out why the agent failed (F0–F8 taxonomy).
2. Decides whether the failure is a capability gap (F6).
3. If it is, emits a **capability request**: a structured spec of the missing
   tool that would have let the agent finish the task.

Step 3 is the main contribution. The baseline, **AgentRx** (Microsoft Research,
2026), stops at a diagnosis (critical step + category) and never proposes the
missing capability. In AgentRx, "Intent Not Supported" (the F6 equivalent) is
one of 9 categories and appears in only about 7% of its public data.

### Failure taxonomy ([src/taxonomy.py](../src/taxonomy.py))

| Label | Meaning |
|---|---|
| F0 | Success, no failure |
| F1 | Reasoning or planning error |
| F2 | Wrong tool selected |
| F3 | Wrong tool parameters |
| F4 | Tool runtime error |
| F5 | Tool documentation or schema error |
| **F6** | **Missing capability gap** (project focus) |
| F7 | Insufficient user information |
| F8 | Environment or state error |

---

## 2. The `CapabilityRequest` schema

Defined in [src/schemas.py](../src/schemas.py) as a Pydantic model:

```python
class CapabilityRequest(BaseModel):
    """A structured spec for a missing tool that would close a capability gap."""

    name: str
    capability: str
    description: str
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    rationale: Optional[str] = None
```

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Name of the tool that should exist, e.g. `realtime_weather` |
| `capability` | yes | Canonical snake_case capability slug. Evaluation compares this against the capability that was actually missing |
| `description` | yes | One line describing what the tool does |
| `inputs` | no (default `[]`) | Input parameters, each `{name, type, description}`; gold requests also carry `required` |
| `outputs` | no (default `[]`) | Output fields, each `{name, type, description}` |
| `rationale` | no | Why the task needs this tool, grounded in the task or trace |

### Example (real output)

From [outputs/evaluation/predictions_capmatch-fair_all.jsonl](../outputs/evaluation/predictions_capmatch-fair_all.jsonl),
trace `live_rt_weather_berlin_gap`
(task: *"Get the current weather in Berlin from a live weather source."*):

```json
{
  "name": "realtime_weather",
  "capability": "realtime_weather",
  "description": "Fetch current weather conditions from a live weather API",
  "inputs": [
    {"name": "location", "type": "string", "description": "City or region name (e.g., Berlin)"}
  ],
  "outputs": [
    {"name": "temperature", "type": "string", "description": "Current temperature in Celsius"},
    {"name": "condition", "type": "string", "description": "Weather condition (e.g., sunny, rainy)"}
  ],
  "rationale": "The task requires accessing real-time weather data, which is essential for providing accurate current weather information in Berlin."
}
```

---

## 3. Where the schema lives in the pipeline

### 3.1 Predictions

`Prediction` ([src/schemas.py](../src/schemas.py)) carries two fields that are
populated only when F6 is detected:

```python
missing_capabilities: list[str] = []  # e.g. ["realtime_weather"]
capability_requests: list[CapabilityRequest] = []  # one spec per missing capability
```

Both are written to `outputs/evaluation/predictions_*.jsonl` when evaluation is
run with `--save-predictions`.

### 3.2 Ground truth

`AgentTrace` carries evaluation-only fields. Classifiers must never include
them in their prompts:

```python
gold_missing_capabilities: list[str] = []
gold_capability_requests: list[CapabilityRequest] = []
```

For live MCP traces, [src/live_agent.py](../src/live_agent.py) builds the gold
requests from the **real MCP schema of each withheld tool**:

| Gold field | Source |
|---|---|
| `name` | The withheld tool's name |
| `capability` | `tools_to_capabilities([tool.name])[0]` (shared vocabulary) |
| `description` | The tool's MCP description |
| `inputs` | `inputSchema.properties`, plus `required` from `inputSchema.required` |
| `outputs` | `outputSchema.properties` |
| `rationale` | `"This withheld tool is required to complete: <user_task>"` |

---

## 4. How the capability matcher produces requests

Implemented in [src/capability_matcher.py](../src/capability_matcher.py)
(`capmatch-fair` / `capmatch-oracle`).

1. **Extract required capabilities.** An LLM reads the user task, available
   capabilities, tool calls and final response, and lists the capabilities the
   *task* needs, independent of which tools exist. For each it returns a
   `slug`, `description`, `evidence`, `matched_available`, and, when nothing
   covers it, a `capability_request`.
2. **Deterministic matching.** Code computes
   `required − available = missing`. The LLM's claim of coverage is not
   trusted: `_is_covered` checks that the claimed `matched_available` slug is
   really in the trace's available capability set, and the required slug
   itself is also checked against that set.
3. **Build the request.** For each missing slug, `_to_capability_request`
   converts the LLM output into a `CapabilityRequest`, filling defaults when
   fields are missing:

   | Field | Default |
   |---|---|
   | `name` | `<slug>_tool` |
   | `capability` | `<slug>` |
   | `description` | `Provides the '<slug>' capability.` |
   | `rationale` | `Required by task: <first 160 chars of task>` |
   | `inputs` / `outputs` | `[]` |

   The text fields are therefore never empty; `inputs` and `outputs` can be.
4. **Label.** If anything is missing, the trace is labeled
   `F6_missing_capability_gap` with confidence 0.8, `new_tool_needed=True`, and
   the requests attached. Otherwise the matcher defers to the `llm-fair`
   baseline for the fine-grained F0–F8 label.

The LLM is asked to return JSON in this shape:

```json
{
  "required_capabilities": [
    {
      "slug": "string",
      "description": "string",
      "evidence": "string",
      "matched_available": "string-or-null",
      "capability_request": {
        "name": "string",
        "capability": "string",
        "description": "string",
        "inputs": [{"name": "string", "type": "string", "description": "string"}],
        "outputs": [{"name": "string", "type": "string", "description": "string"}],
        "rationale": "string"
      }
    }
  ],
  "reasoning": "string"
}
```

The matcher is testable offline by passing a `complete` callable instead of
calling the API.

---

## 5. How requests are evaluated

Implemented in [src/evaluation/request_metrics.py](../src/evaluation/request_metrics.py).
Only traces with gold label F6 **and** a non-empty
`gold_missing_capabilities` are scored.

| Metric | Definition |
|---|---|
| Capability precision / recall / F1 | Predicted `missing_capabilities` vs gold, using the slug matching rule below |
| Exact match rate | Fraction of traces where the predicted set equals the gold set |
| Request coverage | Fraction of gold missing capabilities that received a matching request (`request.capability`) |
| Schema completeness | For requests matching a gold capability, the fraction of 6 checks passed: non-empty `name`, `capability`, `description`, `rationale`, `inputs`, `outputs` |

**Slug matching rule.** Two slugs match if, after canonicalization, at least
2/3 of their tokens overlap. Generic tokens (`api`, `tool`, `get`, `current`)
are ignored, simple plurals are normalized (`emails` → `email`,
`holidays` → `holiday`), and `conversion` / `converter` map to `convert`. So
`email_search` and `search_emails` count as equivalent.

These metrics measure whether the right capability was named and whether the
spec is structurally complete. They do not measure prose quality or whether a
tool built from the spec would work.

---

## 6. Datasets

| Source | Contents | Status |
|---|---|---|
| AgentRx `tau_retail` (Hugging Face, gated) | 29 failed traces, 15-tool universe | Fully usable |
| AgentRx `magentic_one` | 44 traces | Gold labels parse; tool calls not yet parsed |
| AgentRx `flash` | — | Not public |
| Live MCP traces ([src/live_agent.py](../src/live_agent.py)) | Paired control / gap runs with known missing capability | Main F6 source |
| Qwen realtime ([data/live_realtime_traces_qwen3_clean.jsonl](../data/live_realtime_traces_qwen3_clean.jsonl)) | 60 traces: 30 controls, 30 gaps | Clean |
| MCP-Atlas | Baseline / ablated paired runs | Scripts ready; external validation pending |

F6 is rare in real AgentRx data (about 5 cases), which is why the project
generates its own gap traces. Each live task runs twice:

- **control:** full toolset.
- **gap:** every tool that provides the needed capability is withheld.

Withholding must be by *capability*, not by tool: removing only `calculator`
did not create a gap because the agent used `run_python` instead. Live-data
tasks (weather, exchange rates, earthquakes, ISS position, public holidays,
Open Library) give the cleanest gaps.

---

## 7. Methods

| Name | Description | Emits requests? |
|---|---|---|
| `llm-fair` | LLM-as-judge baseline; does not see the gold explanation | No |
| `llm-oracle` | Same, but sees the gold explanation (upper bound) | No |
| `capmatch-fair` | Capability matcher (main method) | Yes |
| `capmatch-oracle` | Matcher with gold explanation (upper bound) | Yes |

---

## 8. Latest results

Full paired Qwen evaluation (60 traces, clean controls labeled
`F0_success_no_failure`), from
[outputs/evaluation/summary_all.json](../outputs/evaluation/summary_all.json):

| Method | Accuracy | F6 F1 | Request F1 | Exact match | Coverage | Schema completeness |
|---|---:|---:|---:|---:|---:|---:|
| `llm-fair` | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `capmatch-fair` | 1.000 | 1.000 | 0.600 | 0.600 | 0.600 | 1.000 |

Request scores are computed over the 30 eligible gap traces.

Both methods classify every trace correctly. Only the matcher produces
capability requests, and every matched request has all six fields filled in.
About 40% of requests name the missing capability differently from the gold
slug; inspecting those mismatches is an open next step.

Current claim:

> A prototype capability-gap detector that matches an LLM-as-judge baseline on
> Qwen-generated controlled F6 classification and adds structured
> missing-capability request generation, which the baseline does not provide.

---

## 9. Running it

```bash
uv sync
export SCADS_API_KEY="your-tud-ai-key"

# Full paired Qwen evaluation, saving per-trace requests
uv run python -m src.evaluate --traces data/live_realtime_traces_qwen3_clean.jsonl \
  --method llm-fair capmatch-fair --split all --label-clean-controls --save-predictions

# Replay one trace and see its capability request
uv run python -m src.demo --trace data/live_traces.jsonl \
  --trace-id live_weather_berlin_gap --method capmatch-fair
```

---

## 10. Key files

| File | Role |
|---|---|
| [src/schemas.py](../src/schemas.py) | `AgentTrace`, `ToolCall`, `Prediction`, `CapabilityRequest` |
| [src/capability_matcher.py](../src/capability_matcher.py) | Gap detection and request generation |
| [src/llm_classifier.py](../src/llm_classifier.py) | LLM-as-judge baseline |
| [src/live_agent.py](../src/live_agent.py) | Live trace generation and gold requests |
| [src/evaluation/request_metrics.py](../src/evaluation/request_metrics.py) | Request scoring |
| [src/evaluation/capabilities.py](../src/evaluation/capabilities.py) | Shared capability vocabulary |
| [mcp_servers/research_tools/server.py](../mcp_servers/research_tools/server.py) | MCP server (~17 tools) |
