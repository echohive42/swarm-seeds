---
name: 05-adaptive-orchestration-search
description: Build and test adaptive multi-agent systems that replace subjective judging with visible self-verification. Use when Codex needs to search prompt and routing designs, bank candidate answers, spend extra calls only on uncertain cases, verify candidates against withheld public evidence, and freeze a deterministic selector before a fresh sealed evaluation.
---

# Search for Verifiable Orchestration

## Start with a measurable task

Define an exact task, deterministic scorer, fixed model condition, and fresh-case generator. Separate development evidence from fresh gates. Never use a post-hoc replay as validation.

Record the requested model, reasoning effort, service tier, tool access, maximum concurrency, retry rules, and output schema. Keep the answer key sealed until every registered call is terminal.

## Search broadly before validating deeply

Use small development panels to compare many prompt and routing ideas. Reuse paid-for answers when testing deterministic selectors. Track the candidate oracle, which is the number of cases where at least one generated candidate is correct.

Diagnose the bottleneck:

- If oracle coverage is low, improve candidate generation.
- If oracle coverage is high but final accuracy is low, improve selection.
- If both are low, add new reasoning lenses before adding judges.

Do not spend a large hidden final on a weak candidate. Use progressively larger fresh gates, but label them as research checks until a final system is frozen.

## Prefer visible checks to opinions

When a task contains public evidence that can be temporarily hidden, make candidates predict it before trusting their unknown answer.

For a sequence prefix:

1. Remove one to three public suffix terms.
2. Ask an agent to reconstruct those terms and predict the unknown continuation.
3. Reject the candidate unless every removed public term is exact.
4. Give more evidence weight to candidates that reconstruct longer suffixes.

For a future answer tuple `y`, use:

```text
W(y) = sum of h_i over verified candidates i that support y
```

Here `h_i` is the number of public terms candidate `i` reconstructed exactly. Break ties with frozen observable evidence, such as deepest suffix, distinct suffix depths, distinct source stages, raw support, and a canonical tuple order. Exclude self-reported confidence.

Adapt the same pattern to other domains with checkable public evidence, such as held-out tests, masked table rows, omitted facts, known code behavior, or reversible transformations.

## Route compute adaptively

Begin with a diverse independent panel. Escalate only cases with weak agreement or weak verified support.

A useful pattern is:

```text
diverse base panel
  -> visible-holdout solvers for uncertain cases
  -> recovery solvers for weakly verified cases
  -> structural worksheets for unresolved cases
  -> deterministic evidence-weighted selector
```

Freeze every threshold, stage size, prompt, and tie-break rule before generating a fresh gate. Count actual model calls separately from per-case analyses when one call handles several independent cases.

## Preserve the research trail

Keep failed systems, malformed responses, exact retries, aborted evaluations, and post-hoc analyses. Never score a partial sealed evaluation after redirecting the experiment. State why it stopped and whether its answer key remained sealed.

Report:

- exact task accuracy and term accuracy;
- base accuracy and final accuracy;
- useful, harmful, and neutral overrides;
- candidate-oracle accuracy;
- calls, attempts, retries, and invalid outputs;
- performance by task family;
- whether the selector was frozen before fresh-case generation;
- all important limitations.

Use the complete reference run in [`experiment/`](experiment/). Read [`experiment/REPORT.md`](experiment/REPORT.md) before adapting the method.
