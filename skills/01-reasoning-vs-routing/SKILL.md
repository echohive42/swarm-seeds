---
name: 01-reasoning-vs-routing
description: Run a contamination-resistant comparison of direct solvers, equal-budget independent ensembles, and structured proposer-critic-verifier-judge collaboration across two reasoning-effort settings. Use when testing whether extra reasoning or multi-agent routing improves accuracy, calibration, reliability, or efficiency on a benchmark with objectively scorable answers.
---

# 01 — Reasoning vs. Routing

## Purpose

Compare three ways of spending inference compute:

1. One direct solver.
2. Several independent solvers combined by deterministic voting.
3. A structured swarm in which agents propose, criticize, verify, and judge.

Run the same comparison at two reasoning settings. Keep the arms isolated so neither can learn from the other.

This seed answers a practical question: **should the next unit of compute go into thinking harder, sampling more independent answers, or organizing agents to work together?**

## Define the experiment

Choose and record:

- one model;
- two reasoning settings;
- an objectively scored benchmark;
- a small development split;
- an untouched final split;
- an exact output schema;
- one primary metric;
- secondary accuracy, calibration, reliability, latency, and cost metrics.

Use cases as the paired statistical units. Do not treat several calls on the same case as independent benchmark cases.

## Freeze before evaluation

Before running the final split:

1. Freeze the benchmark, answers, prompts, roles, schemas, scoring rules, and aggregation rules.
2. Hash every frozen file.
3. Confirm the final raw-output directory is empty.
4. Run only the development split.
5. Audit parsing, packet transfer, archiving, scoring, and failure handling.
6. Do not change the experiment after seeing final answers.

Allow a documented schema-only repair before final evaluation. Do not use development performance to rewrite tasks, weights, roles, or answers.

## Keep the arms isolated

- Create every subject as a fresh, non-forked task.
- Set the model and reasoning level explicitly.
- Use byte-identical templates across reasoning arms.
- Pass low-reasoning outputs only to low-reasoning subjects.
- Pass medium-reasoning outputs only to medium-reasoning subjects.
- Remove task identifiers, model names, reasoning labels, scores, and provenance from stage packets.
- Never show subjects benchmark answers or other-arm results.
- Archive every finished task after capture.

If backend model-identity or reasoning-token telemetry is unavailable, record the settings requested at creation and state the telemetry limitation plainly.

## Apply the common subject prefix

Prepend this to every subject prompt:

```text
Solve entirely through your own unaided internal reasoning. Do not use Python, calculators, code execution, web browsing, search, external tools, files, databases, lookups, or information from other agents or tasks. Treat every case independently. Do not infer anything from case identifiers. Follow the required JSON format exactly.
```

The restriction applies to experimental subjects. The root orchestrator may create packets, parse outputs, score results, and run integrity checks.

## Use equal deployment budgets

Run ten calls per aggregate method.

### Direct solver

Run ten identical independent calls to estimate expected one-call performance. Report deployment cost as one call and experimental replication cost as ten calls.

Use this task instruction:

```text
Solve every case using the most conventional compact rule that exactly explains the complete input. Avoid approximate extrapolation and arbitrary exceptions. Return the requested answer, a brief rule or rationale, and an integer confidence from 0 to 100.
```

### Independent ensemble

Reuse the same ten direct outputs. Do not spend ten additional calls.

For each case:

1. Group valid answers by exact identity.
2. Choose the answer with the most votes.
3. Break a vote-count tie by the greatest sum of supporting confidence.
4. Break any remaining tie deterministically, using the lexicographically smallest answer.
5. Set ensemble confidence to the mean confidence of supporting voters.
6. Preserve the rationale from the highest-confidence supporting voter, breaking ties by lower replicate number.

Reject malformed answers from voting but preserve them in the raw records and include them in format-compliance reporting.

### Structured collaboration

Use exactly ten calls in four stages:

```text
5 proposers → 2 critics → 2 verifiers → 1 judge
```

Run subjects within a stage in parallel. Pass only anonymous, same-arm outputs to the next stage.

## Assign proposer roles

Give each proposer a different search strategy.

### Proposer A — recall

```text
First consider whether a known, conventional, or previously established pattern exactly matches the complete input. If not, derive a compact exact explanation. Return one best proposal per case.
```

### Proposer B — recurrence and mechanism

```text
Analyze differences, ratios, state transitions, recurrences, alternating corrections, and cumulative constructions. Require exact agreement with the complete input. Return one best proposal per case.
```

### Proposer C — structure

```text
Test interleaving, subsequences, index transforms, composition, powers, factorials, and other structured constructions. Require exact agreement. Return one best proposal per case.
```

### Proposer D — domain specialist

```text
Search the task's established domain patterns and compact closed forms. Reject resemblance unless the entire input matches exactly. Return one best proposal per case.
```

### Proposer E — skeptical generalist

```text
Generate several genuinely different hypotheses privately. Falsify them against the earliest conflicting observation. Return the simplest exact survivor for each case.
```

Adapt only domain-specific nouns. Preserve the diversity of search strategies.

## Assign critic roles

### Exactness critic

```text
Audit the anonymous proposals for exact coverage and internal consistency. Identify unsupported exceptions or the earliest mismatch, then rank proposals from strongest to weakest. Do not invent a new proposal unless every submitted proposal fails.
```

### Simplicity critic

```text
Audit the anonymous proposals for conventional meaning, simplicity, and overfitting. Prefer compact exact explanations over interpolation, approximate trends, or patched exceptions. Rank proposals and state the decisive reason concisely.
```

Require both critics to evaluate every anonymous proposer label.

## Assign verifier roles

### Arithmetic or execution verifier

```text
Independently recompute the result implied by the strongest exact proposals. Focus on arithmetic, indexing, signs, boundary conditions, and off-by-one errors. Report the verified answer and any disagreement with the submitted prediction.
```

### Rule or mechanism verifier

```text
Independently verify the strongest submitted explanations. Determine which proposal regenerates the complete input without exceptions, identify any failure, and compute its result. Do not defer to proposal confidence or popularity.
```

## Judge conservatively

Use this priority order:

1. Exact input coverage.
2. Independent verification.
3. Conventional simplicity.
4. Proposal popularity only as a weak tiebreaker.

Use this instruction:

```text
Return the best-supported answer for every case. If all proposals are weak, still provide the best available answer but lower confidence. Do not average incompatible predictions.
```

## Handle failures without hiding them

- Preserve malformed output exactly.
- Do not rerun a malformed completed response merely to improve the score.
- Penalize missing or schema-invalid answers under the frozen scoring rule.
- If a task stalls or is interrupted, record the attempt, archive it, and restart the identical prompt in a fresh task.
- Exclude the interrupted attempt from scoring, but retain its failure record.
- Never silently repair a prediction.

## Score and compare

Use one task-appropriate primary metric. For exact-answer tasks, use exact full-answer accuracy.

Also report:

- partial or component accuracy;
- confidence calibration, such as `1 - (confidence - exact)^2`;
- format compliance;
- deployed calls and experimental calls;
- per-call and parallel critical-path latency;
- prompt and output characters;
- visible-token estimates, clearly labeled as proxies;
- actual hidden reasoning tokens only when exposed by system metadata.

Compare methods on paired cases. Use deterministic case-resampling bootstrap intervals as descriptive uncertainty estimates. Report wins, losses, and ties. Do not claim general statistical certainty from a small benchmark.

## Preserve a complete record

Save:

- the frozen protocol and hashes;
- benchmark inputs and expected answers;
- exact prompt templates;
- raw subject outputs;
- anonymous stage packets;
- deterministic ensemble outputs;
- case-level scores;
- summary and cost tables;
- failed-attempt records;
- development and final audits;
- a short report explaining results and limits.

Pseudonymize internal task identifiers before public release without altering model outputs, prompts, metrics, or failure history.

## Interpret the result honestly

Separate three conclusions:

1. Whether greater reasoning effort helped.
2. Whether spending more calls helped relative to one direct call.
3. Whether structured collaboration beat a same-call-budget independent ensemble.

If collaboration ties the ensemble but costs more, prefer the ensemble for efficiency. If collaboration helps only in the lower-reasoning arm, describe it as a possible rescue mechanism rather than a universal advantage.

The first implementation of this seed is documented in the matching [Luna low-vs-medium result](../../results/01-reasoning-vs-routing/run-01-luna-low-vs-medium/README.md).
