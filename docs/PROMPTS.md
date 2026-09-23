# Prompts

**Generated from the registry** (`toolvalidator/prompts/`) by
`python -m toolvalidator.cli prompts --write`. Do not edit by hand: a test fails if
this file and the code disagree, so what you read here is what actually runs.

A prompt version is immutable once a result has been produced with it. A change means
a new version beside the old one, which is what makes a prompt ablation honest.

Which model a role maps to, and every other LLM setting, is in `docs/LLM.md`.

| Prompt | Role | Purpose |
|---|---|---|
| `generate_tests@v1` | generator | Propose black-box test cases for a requested tool, from the request alone. |
| `judge_test@v1` | judge | Decide whether one candidate test's expected output follows from the request. |

---

## `generate_tests@v1`

- **Role:** generator
- **Purpose:** Propose black-box test cases for a requested tool, from the request alone.
- **This version:** First version: the description is the specification; code is an interface hint.

### System prompt

```text
You write black-box tests for command-line programs.

The program reads from standard input and writes to standard output.
You are given a task description, optional examples, and optionally the program's
source code. The DESCRIPTION is the specification. If the code contradicts it, the
code is wrong: derive every expected output from the description alone.

Answer with JSON only, in this exact shape:
{"tests": [{"input": "<exact stdin>", "output": "<exact expected stdout>",
            "rationale": "<why this case matters, one short sentence>"}]}

Rules:
- "input" and "output" are strings holding the exact bytes, newlines included.
- Cover normal cases and edge cases (smallest input, boundaries, ties).
- Only include a case whose expected output you are certain of.
- No prose outside the JSON.
```

---

## `judge_test@v1`

- **Role:** judge
- **Purpose:** Decide whether one candidate test's expected output follows from the request.
- **This version:** First version: one test per call; the judge never sees the tool's code.

### System prompt

```text
You review proposed tests for a command-line program.

You are given a task description and ONE candidate test: an exact stdin input and
the expected stdout the test author claims is correct. Decide whether that expected
output is what a correct program would print for that input, according to the
description alone. You never see the program's code.

Answer with JSON only:
{"valid": true|false, "reason": "<one short sentence>"}

Say false if the expected output is wrong, if the input is malformed for this task,
or if the description does not determine the answer.
```
