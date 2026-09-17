# Project D — Research Plan (Full Scope, 2-Week Sprint)

**Author:** Sohaib Ashraf
**Project:** Progressive Validation of Agent-Generated Tools
**Deliverable:** Final written report + working system + experimental results
**Timeline:** 2 weeks. Experiments complete by ~Day 10; writing Days 10–14.
**Status:** For supervisor confirmation.

---

## 0. TL;DR — what this project is

We take tools that Project C synthesizes (with Project B's Capability Request)
and **validate them** through a pipeline of increasingly expensive checks. The
research contribution is empirical:

1. **Static vs. dynamic** — do dynamic checks (running the tool + generated
   tests + mutation testing) catch failures that static checks alone miss? By
   how much, at what cost, for which bug categories?
2. **Test generation** — can useful tests be generated automatically from the
   Capability Request, with no human annotation? Which generation strategy is
   best (this is where mutation testing's two arms and the rubber-duck comparison
   live)?
3. **Reliability score** — can we define a score that provably **correlates**
   with a tool's true correctness, with the weights *fit from data* on a large
   labelled dataset (not hand-picked)?

Three real components are built and measured: **mutation testing (two arms)**,
**rubber-duck semantic checking**, and **MCP schema generation**.

---

## 1. Scope decision (why this is the full version, not the trim)

An earlier plan proposed cutting mutation testing, rubber-duck, and MCP to fit
the timeline. **Decision: keep all three**, because this is a *research* project
and each is an experimental arm that produces a comparative result — not
decoration. The scope is controlled instead by:

- **One dataset**, reused for every experiment (not three).
- **Fitting the score on a large existing labelled dataset** (removes the
  overfitting risk and the dataset-construction step).
- **Reusing the already-built S0–S3 pipeline** as the spine.
- A **strict day-by-day schedule** (Section 8) with the dataset on the critical
  path.

Accepted risk: this is aggressive. Mitigation is sequencing and reuse, not
cutting.

---

## 2. The pipeline (what runs, in order)

| Stage | What it does | Static / Dynamic | Built? |
|-------|--------------|------------------|--------|
| S0 provision | disposable Docker container, network off, caps dropped | — | ✅ |
| S1 parse | AST parse; `SyntaxError` → reject | static | ✅ |
| S2 static | **minimal**: bandit (dangerous calls) + mypy (types) | static | ✅ (trim) |
| S3 test-gen | generate tests from Capability Request (generator + judge) | — | ✅ core |
| S4 execute | run the tool against generated tests in the sandbox | dynamic | 🔨 build |
| S5 mutation | mutation testing, **two arms** (see §4) | dynamic | 🔨 build |
| S5b rubber-duck | LLM explains code; compare to description → semantics | dynamic | 🔨 build |
| S6 score | reliability score, weights fit from data (§5) | — | 🔨 build |
| S7 MCP schema | generate MCP-compliant JSON schema from code + request | — | 🔨 build |

Terminals: **ACCEPT / REJECT / NEEDS_REVIEW**. Hard failures (dangerous call,
crash on example) short-circuit to REJECT before scoring.

**Static checks are deliberately minimal** (bandit + mypy only). Their job is to
be the *cheap baseline* the dynamic checks are compared against — not to be
comprehensive. Dropped from earlier scope: secrets scan, pip-audit, import
allowlist. (These are noted as trivial future extensions, not part of the study.)

---

## 3. Research questions (final, supervisor-approved wording)

- **RQ1 — Slip rate.** How many functionally broken or unsafe tools pass naive
  validation (no sandbox) vs. sandboxed validation?
- **RQ2 — Necessary/sufficient checking.** Is static analysis alone enough, or
  must dynamic execution run? *(Headline experiment, §6.1.)*
- **RQ3 — Automatic test generation.** Can tests be generated automatically from
  the Capability Request without human annotation — and which strategy is best?
  *(§6.2; mutation arms + rubber-duck compared here.)*
- **RQ4 — Reliability score.** Can a score from test pass rate, static results,
  and synthesis metadata be defined to **correlate** with true correctness?
  *(§5, §6.3.)*
- **RQ5 — MCP schema accuracy.** Can MCP-compliant JSON schemas be generated
  automatically and accurately from the code and Capability Request? *(§6.4.)*

All five kept. Each maps to a concrete measured result.

---

## 4. The three research components (built for real)

### 4.1 Mutation testing — TWO arms (this is a core comparison, RQ3)

Mutation testing measures **how good the generated tests are**: inject small bugs
("mutants") into the tool, and see whether the generated tests *catch* them. A
test that catches no mutant is worthless.

- **Arm A — real mutation testing (`mutmut`/`cosmic-ray`).** Systematic,
  operator-based code mutants. The reference method.
- **Arm B — LLM-invented mutants.** Ask an LLM to produce plausible buggy
  variants of the tool. Cheaper, semantically richer, but unproven.

**The experiment:** do the two arms agree on which tests are strong? Does Arm B
(cheap) approximate Arm A (rigorous)? This is a genuine, current research
question — the answer is a result either way.

Output: a **test-quality signal** (mutation kill rate) that feeds the score.

### 4.2 Rubber-duck semantic checking (a dynamic correctness signal)

Execution checks *outputs*. Rubber-duck checks *meaning*: an LLM reads the tool's
code and explains, in plain language, what it actually does. We compare that
explanation to the Capability Request's description. A mismatch (code says
"returns strings", task says "return integers") produces:

- a **semantics signal** for the score, and
- a **repair signal** describing the gap.

**Tuned, not one-shot:** we iterate the prompt on a dev split so the
explanations are reliable, and report inter-run agreement so we know how noisy
the signal is.

**The experiment:** does the semantic signal catch tools that *pass their tests
but are still wrong* — the failures execution alone misses? Measured as extra
recall over execution-only.

### 4.3 MCP schema generation (RQ5)

For each ACCEPTED tool, generate an **MCP-compliant JSON schema** (typed inputs,
typed outputs, description) from the code + Capability Request.

**The experiment:** accuracy against a reference schema. For each tool we derive
a ground-truth schema (from the function signature + types + the Capability
Request's declared I/O) and score the generated schema on:
- structural validity (is it valid MCP JSON?),
- field accuracy (do input/output names + types match?),
- completeness (all params present?).

Report accuracy %, and whether accuracy correlates with tool complexity.

---

## 5. Reliability score — research-backed, fit from data (RQ4)

The old 0.4/0.3/0.3 weights were arbitrary. The new score is a **validated
predictor**: it is defined so that it demonstrably correlates with a tool's true
correctness, and the weights are **learned**, not chosen.

### 5.1 Ground-truth outcome (what the score predicts)
The dataset gives a **true correctness label** per tool (buggy vs. fixed, and
whether it passes its held-out tests). This label is the *target* — the score
must NOT be computed from it.

### 5.2 Predictor signals (score inputs)
- `test_pass_rate` — fraction of generated tests passed (from S4)
- `mutation_score` — kill rate (from S5)
- `semantics_score` — rubber-duck alignment (from S5b)
- `static_clean` — bandit/mypy result (from S2)
- `synthesis_metadata` — if Project C provides confidence / retry count

### 5.3 Fitting (weights from data, not taste)
- Fit a **logistic regression**: signals → P(tool is correct).
- Learned coefficients = the weights, justified by data.
- Train/test split (or k-fold cross-validation) so we never report on training
  data. The large dataset (§7) makes this sound — this is the reason we fit on a
  big existing set rather than ~30 hand-made tools.

### 5.4 What we report
- **Correlation** (Spearman ρ) between score and true correctness on held-out data.
- **Calibration curve** — does score 0.8 ≈ 80% correct?
- **AUC** for the accept/reject decision.
- **Ablation** — how much does each signal contribute (drop-one-out)? This
  directly answers "does the dynamic signal add predictive power over static?"

### 5.5 Guardrails (honesty)
- Hard gates (dangerous call, crash-on-example) stay **outside** the regression —
  safety is a veto, not a term.
- Report only held-out numbers.
- If any signal turns out non-predictive, that is a finding, not a failure.

---

## 6. The experiments (each produces a number/figure)

### 6.1 Static vs. dynamic (RQ1, RQ2) — the headline
Run every dataset tool through two configurations:
- **Static-only:** S1 + S2 → verdict.
- **Static + dynamic:** S1 + S2 + S4 + S5 + S5b → verdict.

Report, per configuration: **slip rate**, **false-rejection rate**,
**per-category recall** (which bug types each catches), **cost** (ms/tool).
Expected story: static catches syntax/security/type bugs; dynamic additionally
catches *logic* bugs static is blind to — quantified.

### 6.2 Test-generation strategies (RQ3)
Compare test sets from: (a) LLM generator + judge, filtered by (b) Arm-A mutation,
(c) Arm-B mutation, and the (d) rubber-duck semantic layer. Metric: bugs caught /
mutants killed per strategy. Output: which strategy wins, and whether cheap Arm B
≈ rigorous Arm A.

### 6.3 Reliability score validity (RQ4)
As §5.4: correlation, calibration, AUC, signal ablation, on a held-out split.

### 6.4 MCP schema accuracy (RQ5)
As §4.3: structural validity, field accuracy, completeness, vs. reference schemas.

### 6.5 (Optional) Judge independence
If time: does an independent judge (different model family) catch more generator
errors than a same-family judge? Small, current, results-backed.

---

## 7. Dataset  ⚠️ DECISION POINT (confirm after inspection)

**Requirement (why most datasets fail):** each entry must be (1) a self-contained
function/program (NOT a whole project), (2) executable, (3) bundled with tests,
(4) have a buggy AND a fixed version, (5) number in the hundreds+ (to fit the
score regression).

**Recommended default (pending your inspection):**
- **Spine: RunBugRun** — large (thousands), executable, each entry has a problem
  statement (≈ Capability Request) + buggy code + unit tests + human fix. Matches
  all five requirements. *Caveat:* competitive-programming style reads stdin →
  the S4 harness feeds stdin rather than calling a function (small wrapper).
- **Smoke test: QuixBugs** — 40 single-line-bug programs with tests. Too small to
  fit a regression, but trivial to set up → use on Day 2 to get the pipeline green
  before RunBugRun's harness is ready.
- **Considered and skipped: BugsInPy** — real project-level bugs with a 9-category
  taxonomy, but each bug needs a full repo checkout + dependency install. Setup
  cost too high for 2 weeks. (We may borrow its bug taxonomy for our category
  labels without using the dataset.)

**Framing note (agreed):** these are **human-written** bugs, not LLM-synthesized
tools. We state this explicitly: bug benchmarks are a proxy for synthesized-tool
errors — both are code that may be silently wrong, and the validator's job is the
same. One sentence in the report; supervisor to sign off.

**What changes based on your inspection:**
- If entries are **function-call style** (like EvalPlus/QuixBugs) → S4 harness
  calls the function (already how S3 works, no change).
- If **stdin style** (RunBugRun) → S4 harness pipes stdin, reads stdout (small
  addition on Day 3).
- Final dataset + style to be confirmed by you before Day 3.

---

## 8. Day-by-day schedule (critical path in **bold**)

Experiments must finish ~Day 10; Days 11–14 are writing.

**Week 1 — build + get data flowing**

- **Day 1 — Dataset locked + downloaded.** Confirm choice, download, write the
  loader that turns each entry into `(CapabilityRequest, tool_code, tests,
  correct_version, label)`. *Critical path — everything waits on this.*
- **Day 2 — Pipeline green on QuixBugs (smoke test).** Wire the existing S0–S3 to
  the loader; run end-to-end on the 40 easy programs. Proves the spine works
  before scaling.
- **Day 3 — S4 execute + harness for the real dataset.** Build S4 (run tool vs.
  generated tests in sandbox); add stdin-harness if the dataset needs it. Run
  static-only config on the full dataset → **first RQ1/RQ2 numbers**.
- **Day 4 — S5 mutation, Arm A (`mutmut`).** Real mutation testing; produce
  kill-rate per tool.
- **Day 5 — S5 mutation, Arm B (LLM mutants) + rubber-duck (S5b) first pass.**
  Both dynamic signals producing numbers. *(Self-check: is dynamic config
  running end-to-end on the full set? If not, this is the day to notice.)*

**Week 2 — measure + write**

- **Day 6 — Tune rubber-duck + finish dynamic config.** Iterate the prompt on a
  dev split; lock the semantic signal. Run full **static+dynamic** config → the
  headline comparison numbers (6.1).
- **Day 7 — S6 reliability score.** Assemble all signals into a table; fit the
  logistic regression; produce correlation, calibration, AUC, ablation (6.3).
- **Day 8 — S7 MCP schema generation + accuracy experiment (6.4).**
- **Day 9 — Test-generation strategy comparison (6.2) + optional judge study
  (6.5). Freeze all results.** Re-run anything flaky; lock every number/figure.
- **Day 10 — Buffer / re-runs.** Absorb whatever slipped. **All experiments done
  by end of today.**
- **Days 11–13 — Write the report.** Intro, related work (your 5 papers),
  method (the pipeline + 3 components), each experiment + result, limitations,
  conclusion. Figures from Days 6–9.
- **Day 14 — Polish, proofread, submit.**

**Slack:** Day 10 is buffer; rubber-duck tuning (Day 6) and the score fit (Day 7)
are the likeliest to overrun — if so, the optional judge study (6.5) is the first
thing dropped, then Arm B detail.

---

## 9. What "done" looks like (report contents)

1. Pipeline description (S0–S7, the 3 components).
2. **RQ1/RQ2:** static-vs-dynamic table — slip rate, false-rejection,
   per-category recall, cost. *The headline result.*
3. **RQ3:** test-generation strategy comparison; Arm A vs. Arm B.
4. **RQ4:** reliability-score correlation + calibration + ablation.
5. **RQ5:** MCP schema accuracy.
6. Limitations (incl. the human-vs-synthesized framing; small static set;
   dataset provenance).
7. Conclusion + future work (the cut items: rubber-duck at scale, API tools,
   dependency/secret scanning, MCP registry integration).

---

## 10. Open questions for supervisor

1. **Dataset:** is RunBugRun acceptable as the spine, and is the
   "human-bugs-as-proxy-for-synthesized-tools" framing OK?
2. **Score:** is a fitted logistic regression the right approach, or does he
   prefer a pre-declared score whose correlation we just measure?
3. **Headline:** is static-vs-dynamic (RQ2) the main contribution, or the
   reliability score (RQ4)?
4. **MCP reference schemas:** is deriving ground-truth schemas from
   signature+types+request rigorous enough, or does he want hand-annotated ones?
5. **Two-week realism:** does he agree the full scope (3 components + 5 RQs) fits,
   or would he rather we bank RQ1/RQ2 solidly and treat RQ4/RQ5 as stretch?
