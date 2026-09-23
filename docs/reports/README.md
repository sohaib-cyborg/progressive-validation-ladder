# docs/reports — Progress Reports

A running, factual record of the work done on this project: what was
done, the exact commands that were run, what they printed, and what is blocked.
Nothing here is aspirational. If something wasn't run, the report says so.

| File | What it holds |
|---|---|
| [STATUS.md](STATUS.md) | **Start here.** Current state: what is built, methodology, tests run, results and their caveats. |
| [SPRINTS.md](SPRINTS.md) | The sprint plan: 5 sprints mapped to the 14-day schedule in `docs/PLAN.md`, with exit criteria and preconditions. |
| [sprint-01.md](sprint-01.md) | Work log for Sprint 1 (the spine). ✅ complete, tag `sprint-1`. |
| [sprint-02.md](sprint-02.md) | Work log for Sprint 2 (dynamic signals). In progress. |

Project-level docs live one level up: `ARCHITECTURE.md` (layers, module map, diagrams),
`PROMPTS.md` (generated prompt appendix), `LLM.md` (models, tracing, cost),
`WORKFLOW.md` (how code and experiments are run), `capability_request.md` (the upstream
schema we consume).

## How these relate to the other docs

- `docs/PLAN.md`: the research plan (the *why*). Not modified by reports.
- `docs/DECISIONS.md`: every design decision, with rationale (append-only).
  Reports link to decisions instead of repeating them.
- `docs/MEMORY.md`: durable context and a one-line session log.
- `docs/reports/`: the detailed *what happened*, task by task.

## Entry format (sprint logs)

```
### <task id>: <title>  (<date>)
**Status:** done | blocked | in progress
**What was done:** bullets
**Commands run + actual output:** (trimmed, never invented)
**Decisions:** links to DECISIONS.md entries
**Commit:** <hash> <message>, or "not committed" and why
**Open issues / next:** bullets
```
