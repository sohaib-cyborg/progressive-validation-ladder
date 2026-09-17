# DECISIONS.md — Design Decision Log

Append-only. Every non-trivial design decision gets an entry so future-you (and
Claude Code) knows *why*, not just *what*. Newest at bottom. Never delete entries;
if a decision is reversed, add a new entry that supersedes the old one.

> Format:
> ## YYYY-MM-DD — <short title>
> **Decision:** what we chose.
> **Why:** the reasoning.
> **Alternatives rejected:** what we didn't pick and why.
> **Supersedes:** (if applicable) which earlier decision this overrides.

---

## Day 0 — Fresh start, clean structure
**Decision:** Abandon the previous codebase; rebuild from scratch per STRUCTURE.md.
**Why:** Prior code lacked a consistent structure, which was slowing iteration and
would be fatal on a 2-week deadline.
**Alternatives rejected:** Refactoring the old code in place — too risky, the
structural problems were pervasive.

## Day 0 — RunBugRun (Python subset) as the sole dataset
**Decision:** Use RunBugRun, extracting only Python problems.
**Why:** It is executable, large enough to fit the reliability-score regression,
and each entry has a problem statement, buggy code, tests, and a fix — matching
our required input shape. Large size removes the overfitting risk for RQ4.
**Alternatives rejected:** BugsInPy (project-level, dependency-heavy, too slow to
set up in 2 weeks); injecting our own bugs (weaker credibility than an
established benchmark); MCP-Atlas (measures tool *usage*, not tool *correctness* —
wrong axis).

## Day 0 — Keep all three research components
**Decision:** Mutation testing (two arms), rubber-duck semantics, and MCP schema
generation are all in scope.
**Why:** This is a research project; each is an experimental arm producing a
comparative result, not optional polish.
**Alternatives rejected:** The earlier "trim to core" plan that cut them — rejected
because the supervisor wants comparative experimental results.

## Day 0 — Minimal static checks
**Decision:** S2 = bandit + mypy only.
**Why:** Their role is to be the cheap baseline that dynamic checks are compared
against (RQ2). Comprehensiveness is not the goal; the comparison is.
**Alternatives rejected:** secrets scan, pip-audit, import allowlist — deferred to
future work to protect focus and timeline.

## Day 0 — Reliability score fit from data, not hand-weighted
**Decision:** Fit a logistic regression (signals → P(correct)) on RunBugRun;
report correlation, calibration, AUC, ablation. Hard safety gates stay outside
the regression.
**Why:** A score is only meaningful if it predicts a real outcome; fitted weights
are defensible where hand-picked ones (the old 0.4/0.3/0.3) are not.
**Alternatives rejected:** Pre-declared fixed weights — kept as a fallback if the
dataset proves too small, but the large dataset makes fitting sound.

<!-- Claude Code: append new decisions below -->
