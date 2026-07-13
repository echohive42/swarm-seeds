# Experiment 02 Analysis Plan

## Scope

This plan applies only to the 48 untouched RuleWeave-5 final cases. Development and calibration data are excluded from all final point estimates, confidence intervals, tests, and charts.

The primary unit is the sequence case. Every case contributes its complete paired outcome vector across reasoning settings and methods.

## Labels and notation

Let:

- `i` index final cases 1 through 48;
- `b` index blocks B01 through B04;
- `r` be Light or Medium reasoning;
- `m` be Direct, Vote10, Vote20, Swarm10, or Tournament20.

For each binary method, let `Y(i,r,m)` equal 1 when all five requested decimal-string terms are exactly correct and 0 otherwise.

Direct is different. For each case and reasoning level:

```text
Direct(i,r) = correct independent solver outputs / 20
```

This is a case-level estimate of expected one-call correctness and ranges from 0 to 1.

## Primary endpoint

The primary endpoint is exact five-term continuation accuracy.

A case is exact only when all five ordered decimal strings match the hidden reference. Partial term correctness does not count toward this endpoint.

## Primary contrast

The primary contrast is the matched 20-call routing comparison at Medium reasoning:

```text
Delta_primary =
  mean_i [Y(i, Medium, Tournament20) - Y(i, Medium, Vote20)]
```

Equivalently:

```text
Delta_primary =
  (Tournament20-only wins - Vote20-only wins) / 48
```

This comparison holds the model, reasoning setting, final cases, and 20-call deployment budget fixed. It changes only the allocation of calls between independent voting and structured routing.

Report:

- accuracy for both methods;
- the paired difference in percentage points;
- Tournament20-only wins;
- Vote20-only wins;
- ties where both are correct or both are incorrect;
- a paired 95% bootstrap interval;
- the exact two-sided McNemar p-value as a sensitivity test.

Tournament20 superiority is supported only when the paired 95% interval is entirely above zero. A positive point estimate without that interval is not sufficient.

## Equivalence analysis

The preregistered practical equivalence margin is:

```text
-10 percentage points to +10 percentage points
```

Use two one-sided tests at alpha 0.05, represented by a paired 90% bootstrap interval.

Interpret the primary contrast in this fixed order:

1. If the 95% interval is entirely above zero, report Tournament20 superiority.
2. Otherwise, if the 90% interval lies entirely inside `[-0.10, +0.10]`, report practical equivalence.
3. Otherwise, report the comparison as inconclusive.

Do not treat a failed superiority test as evidence of equivalence. Do not widen the margin after seeing the result.

With 48 binary cases, one net discordant case changes the effect by 2.083 percentage points. Four net cases equal 8.33 points, while five equal 10.42 points. The sample may therefore be unable to establish a narrow equivalence conclusion when discordance is substantial.

## Key reasoning-versus-routing contrast

For each case, define average reasoning lift across the four matched multi-agent methods:

```text
Reasoning_lift(i) = 1/4 x [
    Y(i, Medium, Vote10)       - Y(i, Light, Vote10)
  + Y(i, Medium, Swarm10)      - Y(i, Light, Swarm10)
  + Y(i, Medium, Vote20)       - Y(i, Light, Vote20)
  + Y(i, Medium, Tournament20) - Y(i, Light, Tournament20)
]
```

Define average routing lift across both budgets and reasoning levels:

```text
Routing_lift(i) = 1/4 x [
    Y(i, Light, Swarm10)        - Y(i, Light, Vote10)
  + Y(i, Medium, Swarm10)       - Y(i, Medium, Vote10)
  + Y(i, Light, Tournament20)   - Y(i, Light, Vote20)
  + Y(i, Medium, Tournament20)  - Y(i, Medium, Vote20)
]
```

The contrast is:

```text
Reasoning_over_routing =
  mean_i [Reasoning_lift(i) - Routing_lift(i)]
```

A positive value means that increasing reasoning produced more average exact-accuracy lift than replacing independent voting with structured routing. Direct is excluded because there is no matched one-call collaborative method.

## Confirmatory secondary comparisons

The following 11 comparisons form one confirmatory secondary family.

### Light versus Medium reasoning

1. Medium Direct minus Light Direct
2. Medium Vote10 minus Light Vote10
3. Medium Vote20 minus Light Vote20
4. Medium Swarm10 minus Light Swarm10
5. Medium Tournament20 minus Light Tournament20

### Routing at matched budgets

6. Light Swarm10 minus Light Vote10
7. Medium Swarm10 minus Medium Vote10
8. Light Tournament20 minus Light Vote20

The Medium Tournament20 minus Medium Vote20 comparison is primary and is not repeated in the secondary family.

### More independent samples

9. Light Vote20 minus Light Vote10
10. Medium Vote20 minus Medium Vote10

### Main experimental lesson

11. Reasoning lift minus routing lift

For the 11 comparisons, report raw paired effects, unadjusted paired 95% intervals, raw two-sided p-values, and Holm-adjusted p-values. Control family-wise error at 0.05 with the Holm procedure across all 11 secondary p-values.

Only Holm-adjusted results may support a confirmatory secondary significance claim. Effects and uncertainty remain reportable when the adjusted result is not significant.

For binary method comparisons, use the exact two-sided McNemar p-value. For the Direct reasoning contrast and the reasoning-versus-routing composite, use a two-sided paired sign-flip permutation test with a fixed published seed and at least 100,000 random sign assignments. Zero paired differences remain zero during permutation. Apply Holm correction only after all 11 raw p-values have been produced.

## Exploratory comparisons

The following analyses are descriptive unless explicitly added to the frozen confirmatory plan before final collection:

- each structured or voting method versus Direct within a reasoning level;
- Tournament20 versus Swarm10, because both budget and architecture change;
- family-specific and tier-specific effects;
- block by method and block by reasoning interactions;
- confidence calibration and rule-summary quality;
- any ranking selected because it looked best on final data.

Report exploratory effect sizes and intervals without confirmatory language. Do not use a final-data winner to create a new primary claim.

## Secondary endpoints

### Term accuracy

For each case and method, compute the fraction of the five terms that match in their correct positions. Treat the resulting case score as one observation.

Do not analyze the 240 individual final terms as independent samples.

### Format compliance

Report the fraction of required case records that contain exactly five canonical decimal strings under the frozen schema.

Malformed, missing, reordered, or extra terms fail format compliance. Format compliance does not replace accuracy scoring.

### Operational reliability

Report planned calls, completed initial attempts, infrastructure retries, exhausted retries, substantive malformed responses, and missing case records by condition.

Also report:

- frozen Codex CLI version;
- exact requested model ID;
- reasoning configuration;
- local model-catalog verification result;
- counts of final `agent_message` events;
- exit-code counts;
- 300-second timeout counts;
- JSONL parse failures;
- missing usage telemetry;
- any CLI or model metadata drift by block;
- 20-process load-gate initial infrastructure failures, retries, latency, resource warnings, and final concurrency decision.

CLI sessions are always ephemeral and independent. Session resume counts must be zero.

### Cost and latency

Report deployment cost separately from experimental estimation cost.

Deployment calls are:

- Direct: 1;
- Vote10: 10;
- Vote20: 20;
- Swarm10: 10;
- Tournament20: 20.

Direct uses 20 repetitions only to estimate expected one-call performance. Its deployment token and latency estimate is the mean of the independent one-call observations, not their sum.

For every method and reasoning level, report:

- provider-reported input and output tokens when available;
- a clearly labeled visible-token proxy when provider tokens are unavailable;
- total model-seconds;
- critical-path latency under the actual routing graph;
- calls per exact correct case;
- tokens per exact correct case.

Use usage values captured directly from the raw `codex exec --json` JSONL events when available. Preserve the raw events and state which event fields supplied each value. Do not reconstruct unavailable provider usage from reasoning text. If provider usage is absent, report it as unavailable and use only the separately labeled visible-token proxy.

Record requested model ID `gpt-5.6-luna` separately from backend snapshot metadata. If the JSONL stream does not expose an exact backend snapshot, report that field as unavailable. Do not treat the requested alias as proof of an undisclosed snapshot.

Use paired case bootstraps for cost differences and log cost ratios. Present the accuracy and cost Pareto frontier rather than creating an arbitrary combined score.

## Primary bootstrap

Use a paired, block-stratified case bootstrap with a fixed published random seed and at least 50,000 replicates.

For each replicate:

1. Sample 12 cases with replacement from B01.
2. Repeat independently for B02, B03, and B04.
3. Join the four resampled blocks into one 48-case replicate.
4. Carry every selected case's complete outcome vector across all methods and reasoning levels.
5. Recalculate every endpoint and contrast from that vector.

This preserves pairing across methods, pairing across reasoning levels, the dependence between Vote10 and Vote20, and equal representation of the four planned blocks.

Use percentile intervals for the preregistered analysis. Store the bootstrap seed, replicate count, and resulting quantiles in the analysis output.

## Block sensitivity

Because each model call handles an entire 12-case block, responses within a block can share prompt-level and chronological effects. Run all of the following sensitivity checks:

1. Report the primary contrast separately in B01, B02, B03, and B04.
2. Recalculate the primary contrast four times, leaving out one complete block each time.
3. Run an unstratified paired case bootstrap over all 48 cases.
4. Run a whole-block bootstrap by sampling four complete blocks with replacement.

The whole-block bootstrap is descriptive because four blocks are too few for strong cluster-level inference.

Let `N(b)` be Tournament20-only wins minus Vote20-only wins in block `b`. Flag the primary result as block-sensitive when any of these preregistered checks is met:

- its direction changes in a leave-one-block-out run;
- one block contributes at least 75% of `sum_b abs(N(b))`, when that sum is nonzero;
- the primary and whole-block intervals lead to different superiority, equivalence, or inconclusive classifications;
- the largest and smallest block-specific effects differ by at least 30 percentage points.

If block sensitivity is present, report it prominently and narrow the conclusion. Do not select the more favorable interval.

## Exact sample interpretation

The final run contains three distinct counts:

```text
48 independent benchmark cases
400 planned block-level Luna calls
4,800 case-level model responses
```

It also produces:

```text
48 cases x 5 methods x 2 reasoning levels = 480 derived scores
```

The inferential sample is not 4,800 or 480. It is 48 paired sequence cases, with possible shared block-level effects because one call answers all 12 cases in its block.

Each of the 400 planned model calls is a separate ephemeral `codex exec` session. The pre-frozen runner concurrency, either 20 or 10, changes elapsed collection time but does not increase the statistical sample size or alter the call budget.

For a binary method, one case changes overall accuracy by `1/48 = 2.083` percentage points. A 12-case block has 8.33-point accuracy steps.

Direct contains 20 independent responses for each case and reasoning level, or 960 solver-case outputs per reasoning level. These are repeated attempts nested within 48 cases. They improve estimation of expected one-call accuracy but do not create 960 independent sequence tasks.

Vote10 is a fixed subset of Vote20, so those methods are strongly dependent. All method comparisons must remain paired. Independent-proportion tests are invalid.

At 48 cases, a standalone binary accuracy near 50% has approximate 95% uncertainty near plus or minus 14 percentage points. Paired differences may be tighter when methods rarely disagree. The experiment can resolve large differences better than effects of only a few percentage points.

## Failure handling in analysis

A completed model response that violates the frozen schema is a model failure, not missing infrastructure data. A substantive final `agent_message` makes the attempt completed even when the CLI later exits nonzero or reaches the hard timeout.

For Direct, an invalid independent case record contributes zero correctness for that solver repetition. For Vote10 and Vote20, it casts no valid vote under the frozen voting rule. A malformed final judge record makes the corresponding Swarm10 or Tournament20 case incorrect.

Infrastructure retries are allowed only when there is no substantive final `agent_message` and the attempt has an infrastructure classification. They remain under their original planned call lineage. Use only the terminal substantive response selected by the retry policy, while preserving all JSONL, standard-error, exit, timing, and usage records for audit. A retry must be a new ephemeral invocation and must never resume a CLI session.

Never replace a failed case or call with a new benchmark item. If unresolved infrastructure failures prevent completion, report the run as protocol-incomplete and do not silently perform a complete-case analysis.

## Fixed analysis sequence

After collection closes:

1. Hash and freeze the complete raw-output manifest.
2. Reveal the hidden final answer manifest to the scoring process.
3. Validate case IDs, call IDs, slots, roles, block counts, and retry lineages.
4. Validate CLI version, exact requested model, reasoning settings, tool-disable settings, timeouts, session independence, and JSONL integrity.
5. Score schema compliance without repair.
6. Derive Direct, Vote10, Vote20, Swarm10, and Tournament20 outcomes.
7. Run the frozen primary analysis.
8. Run equivalence and confirmatory secondary analyses.
9. Apply Holm correction once to the full secondary family.
10. Run block, failure, term-accuracy, and cost sensitivities.
11. Audit all reported numbers against raw records before publication.

No alternative analysis may replace the frozen primary result. Additional analyses must be labeled exploratory or sensitivity analyses.
