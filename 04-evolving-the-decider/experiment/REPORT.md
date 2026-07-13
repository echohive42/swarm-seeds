# Experiment 04: Evolving the Decider

## Result in one sentence

The evolved champion solved 41/96 hidden-final cases and diversified Vote10 solved 37/96, a paired difference of +4.2 percentage points with a 95% interval from -2.1 to +10.4 points and exact McNemar p = 0.3438. The interval includes zero, so superiority was not established.

## Question

Can symbolic evolution improve how ten GPT-5.6 Luna Light calls decide together?

Experiment 03 evolved worker organization but required every searched topology to end with one judge. Its champion's judge added no net exact cases on the hidden final. Experiment 04 moved the search target to the decision layer: vote, judge, criticize, verify, deliberate, or refuse an override when the required agreement was absent.

Every experimental call requested `gpt-5.6-luna` with provider reasoning effort `low`, labeled publicly as **Light reasoning**, on the Standard service tier. Every method used ten calls per 12-case block. Subject calls could not use tools, code, Python, files, browsing, skills, plugins, or other agents.

## RuleWeave-5 benchmark

Each case shows 12 to 14 integer terms and asks for the next five terms as exact canonical decimal strings. One wrong term makes the case incorrect. Correct individual terms are a secondary metric.

The generator uses the binomial polynomial basis

\[
B_c(x)=\sum_{j=0}^{d} c_j {x \choose j}
\]

inside eight registered mechanism families:

1. **POLY:** evaluate a binomial-basis polynomial by index.
2. **PDELTA:** add periodic polynomial first differences.
3. **AFFINE:** apply a phase-cycling affine recurrence.
4. **LIN2:** apply a second-order linear recurrence with phase-dependent bias.
5. **LAGPOLY:** advance lagged subsequences by polynomial increments.
6. **INTERLEAVE:** weave two or three polynomial or affine atom streams.
7. **GROWBLOCK:** grow arithmetic blocks whose level and slope follow polynomials.
8. **MODAFFINE:** apply a phase-cycling affine recurrence modulo a fixed modulus.

Each family appears at `hard`, `very-hard`, and `stress` tiers. Every 12-case block contains four cases from each tier. Every registered adjacent block pair covers all 24 family-tier cells exactly once.

| Split | Cases | Blocks | Cases per family-tier cell | Use |
|---|---:|---:|---:|---|
| Search | 192 | 16 | 8 | Two fresh blocks in each of eight rounds |
| Validation | 72 | 6 | 3 | Select one champion from six survivors |
| Hidden final | 96 | 8 | 4 | Compare four frozen methods |

A hidden recognizer rejected ambiguous prefixes unless every registered full-prefix explanation predicted the same next-five tuple. The manifest binds the generation design and 50 public or hidden files by SHA-256. An exact audit found 360 unique visible prefixes, 360 unique hidden programs, and 360 unique targets, with no overlap on any of those representations with Experiments 02 or 03.

See [`benchmark/README.md`](benchmark/README.md), [`benchmark/manifest.json`](benchmark/manifest.json), and [`benchmark/overlap_with_experiments_02_03.json`](benchmark/overlap_with_experiments_02_03.json).

## Bounded genome

A genome contained symbols, never mutable prompt prose:

- one of six decision systems;
- ten worker-lens IDs drawn from eight frozen lenses;
- one of four judge-policy IDs;
- deterministic lineage and a canonical genome hash.

The worker lenses emphasized general search, differences, recurrences, streams, modular structure, simplicity, diversification, or arithmetic audit. The judge policies were plurality-preserving, evidence-weighted, minority-aware, or robustness-first.

| Decision system | Calls | Deterministic final rule |
|---|---|---|
| `vote_10p` | 10 proposers | Proposal plurality |
| `judge_9p1j` | 9 proposers, 1 judge | Judge answer |
| `gated_7p2c1j` | 7 proposers, 2 critics, 1 judge | Override only when both critics and the judge agree |
| `dual_8p2j` | 8 proposers, 2 judges | Use judge answer only when both judges agree |
| `verified_7p2v1j` | 7 proposers, 2 verifiers, 1 judge | Override only when both verifiers and the judge agree |
| `deliberative_6p2c2j` | 6 proposers, 2 critics, 2 judges | Override only when both judges and at least one critic agree |

Invalid intermediate answers abstained. When a gate stayed closed, proposal plurality won. Plurality ties used vote count, then mean reported confidence for the tied tuple, then canonical tuple order.

The standard-library controller could not change prompt text, model settings, tools, memory, call budget, retry rules, or fitness. The exact grammar and founders are in [`genomes/GENOME_CATALOG.json`](genomes/GENOME_CATALOG.json).

## Eight fixed search rounds

Six persistent parent slots completed all eight registered rounds. There was no early stopping.

In each round, the controller created four one-gene mutations and two crossovers. All six parents and all six children then received the same two fresh 12-case blocks, for 20 calls and 24 cases per candidate. Each child challenged only its designated parent. A strictly better child replaced its parent; an exact tie kept the parent. Duplicate canonical genomes were rejected across the run.

Fitness was a lexicographic maximum:

1. more exact next-five cases across both blocks;
2. more exact cases on the weaker block;
3. fewer harmful overrides of a correct proposer plurality;
4. more individually correct terms;
5. more format-valid cases.

The best initial founder was frozen from the founders' round-1 results. It was never reselected with validation or final evidence.

## Blinding and call plan

All cases, hidden programs, targets, answer hashes, prompts, schemas, scripts, founders, call identities, and the evolution seed were generated and frozen before the first experimental call.

Search answers were divided into eight round-scoped files. A round's answers opened only after all 240 logical calls in that round were terminal. Validation answers opened only after all 360 survivor-validation calls were terminal. The champion then froze before hidden-final collection. Final answers opened only after all 320 final logical calls were terminal.

| Phase | Calculation | Logical call identities |
|---|---:|---:|
| Search | 12 candidates x 2 blocks x 10 calls x 8 rounds | 1,920 |
| Validation | 6 survivors x 6 blocks x 10 calls | 360 |
| Hidden final | 4 methods x 8 blocks x 10 calls | 320 |
| **Total** | | **2,600** |

Retries remained attached to their original logical identity and reused the identical request. Infrastructure failures were allowed at most two retries. A schema-invalid completed response received exactly one retry. Correctness never triggered a retry.

## Search results

Every round used a different balanced 24-case sample. Round scores are therefore fresh selection evidence, not repeated measurements on one fixed test set.

| Round | Best exact | Candidate mean | Children accepted | Survivor systems |
|---:|---:|---:|---:|---|
| 1 | 12/24 | 9.67/24 | 2/6 | Vote 1, Judge 1, Gated 1, Dual 1, Deliberative 2 |
| 2 | 12/24 | 9.58/24 | 0/6 | Vote 1, Judge 1, Gated 1, Dual 1, Deliberative 2 |
| 3 | 16/24 | 12.25/24 | 3/6 | Judge 1, Gated 1, Dual 2, Deliberative 2 |
| 4 | 11/24 | 8.25/24 | 3/6 | Dual 3, Deliberative 3 |
| 5 | 9/24 | 7.58/24 | 3/6 | Dual 3, Deliberative 3 |
| 6 | 13/24 | 11.33/24 | 1/6 | Dual 3, Deliberative 3 |
| 7 | 14/24 | 12.42/24 | 3/6 | Dual 3, Verified 1, Deliberative 2 |
| 8 | 15/24 | 12.67/24 | 3/6 | Dual 3, Verified 1, Deliberative 2 |

Eighteen of 48 child challenges replaced their parents. The population moved toward dual-judge and deliberative systems, but it did not converge on one rule. Verification disappeared when the verified founder was eliminated, then reappeared independently in round 7 through a one-gene mutation from `dual_8p2j` to `verified_7p2v1j`.

![Eight-round trajectory](../images/eight-round-trajectory.svg)

## Validation selection

All six round-8 survivors received all 72 validation cases. Their exact scores were 33, 32, 32, 32, 30, and 30. Validation selected `G-A20DBD76963B` by one case over three survivors, so champion selection itself was close.

The champion's symbolic architecture was:

```text
decision system: verified_7p2v1j
worker lenses:   generalist, recurrences, recurrences, modular, simplicity,
                 generalist, generalist, generalist, audit, generalist
judge policy:    minority_aware
```

Calls 1 through 7 were proposers. Calls 8 and 9 were a generalist verifier and an audit verifier. Call 10 was a generalist judge using the minority-aware policy. Its final answer overrode proposal plurality only when both verifiers and the judge returned the same exact tuple.

The champion scored 33/72 exact, with 189/360 correct terms, 72/72 format-valid cases, no harmful override, and a weakest-block score of 3/12. Its round-7 parent was a dual-judge genome with the same lenses and judge policy. Only the decision-system gene changed.

The frozen best founder was `G-0025CFC9EF2E`, the original `vote_10p` policy with ten generalist lenses.

## Hidden-final methods

All four methods used ten calls per block on the same eight untouched blocks:

1. the evolved validation champion;
2. the frozen best initial founder;
3. ten fresh generalist solvers with deterministic Vote10;
4. ten fresh diversified solvers with deterministic Vote10.

These are four execution arms but only three unique symbolic configurations because the best founder and Generalist Vote10 are identical ten-generalist plurality policies.

The diversified pool used generalist, differences, recurrences, streams, modular, simplicity, diversifier, audit, generalist, and audit lenses. Both vote baselines used isolated calls with no evidence sharing.

## Hidden-final results

| Method | Exact | 95% interval | Terms | Plurality | Overrides, useful, harmful | Calls |
|---|---:|---:|---:|---:|---:|---:|
| Best initial founder | **43/96 (44.8%)** | 35.4% to 54.2% | **257/480** | 43/96 | 0, 0, 0 | 80 |
| Evolved champion | 41/96 (42.7%) | 33.3% to 52.1% | 243/480 | 38/96 | 11, 3, 0 | 80 |
| Generalist Vote10 | 41/96 (42.7%) | 34.4% to 52.1% | 242/480 | 41/96 | 0, 0, 0 | 80 |
| Diversified Vote10 | 37/96 (38.5%) | 29.2% to 47.9% | 219/480 | 37/96 | 0, 0, 0 | 80 |

The champion's useful override cases were `F005`, `F034`, and `F073`.

![Hidden-final exact accuracy](../images/final-exact-accuracy.svg)

## Paired comparisons

The protocol's primary comparison was champion minus diversified Vote10.

| Contrast | Difference | 95% interval | Champion-only / comparator-only | Both correct | Both wrong | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| Champion minus diversified Vote10 | +4.2 pp | -2.1 to +10.4 pp | 7 / 3 | 34 | 52 | 0.3438 |
| Champion minus best initial founder | -2.1 pp | -9.4 to +4.2 pp | 5 / 7 | 36 | 48 | 0.7744 |
| Champion minus Generalist Vote10 | +0.0 pp | -6.2 to +6.2 pp | 5 / 5 | 36 | 50 | 1.0000 |

Every paired interval includes zero. No comparison establishes superiority.

## Same-configuration replication

The best initial founder and Generalist Vote10 have identical genes and aggregation: ten generalist solvers followed by deterministic plurality. They were executed independently with fresh model sessions.

- All 80 corresponding prompt hashes matched.
- None of the 80 corresponding response hashes matched.
- The founder run solved 43/96; the generalist run solved 41/96.
- Their case outcomes differed in 16 places: 9 founder-only correct and 7 generalist-only correct.

This is a replication contrast, not an architecture contrast. It shows that one final execution can move by several cases even when the symbolic configuration and prompts are identical. The reported case bootstrap intervals condition on each observed run and do not measure between-run inference variance.

## What the verifier gate did

The champion's seven-proposer plurality solved 38/96. Its gated final answer solved 41/96.

- The gated final differed from proposal plurality on 11 cases.
- Three overrides were useful.
- No override was harmful.
- Eight overrides were neutral because both answers were wrong.

A judge-alone counterfactual also solved 41/96. The verifier gate blocked 11 proposed judge changes: one would have helped, one would have harmed, and nine were neutral. Their net exact value was zero. The supported mechanism statement is therefore narrow: the gate selected a safe set of overrides in this sample. The evidence does not show that verifiers improved accuracy over the judge.

## Operational record

Four schema-invalid first attempts received the registered identical retry. The final ledger contains:

- 2,600 registered logical call identities;
- 2,604 actual model attempts;
- 2,600 valid-output attempts;
- 4 preserved schema-invalid attempts across 4 jobs;
- 0 infrastructure-failure attempts;
- 0 exhausted or protocol-violation jobs.

Across all attempts, the runner recorded 34,692,166 input tokens, 6,849,421 output tokens, and 145,422.086 seconds of summed call latency.

Final-method resource use was:

| Method | Input tokens | Output tokens | Summed latency | Malformed terminal calls |
|---|---:|---:|---:|---:|
| Best initial founder | 958,330 | 234,870 | 4,816.8 s | 0 |
| Evolved champion | 1,089,820 | 203,525 | 4,420.0 s | 0 |
| Generalist Vote10 | 957,370 | 235,873 | 4,779.5 s | 0 |
| Diversified Vote10 | 957,754 | 230,173 | 4,711.1 s | 0 |

Equal logical calls did not produce equal token use. The champion's verifiers and judge received evidence packets, so its input-token total was about 14% higher than the independent pools.

## Frozen-summary caveat

The generated score summaries retain an inherited `methods.*.fitness_key_without_hash` convenience field with Experiment 03's four-part order. It omits weakest-block exact accuracy, so it does not match Experiment 04's registered five-part fitness.

The authoritative `protocol_fitness_key`, `genome_scores`, case matrices, selection receipts, and founder/champion freezes all use the correct order. The controller recomputed and checked fitness from the case matrix before every selection. No parent-child decision, survivor, founder freeze, champion freeze, or reported outcome changes. The frozen summaries are intentionally preserved rather than silently repaired after the run.

## Interpretation

The experiment provides three useful observations:

1. The deterministic controller explored the decision layer. Eighteen child policies replaced parents, and verification was rediscovered after its founder disappeared.
2. The selected gate converted a 38/96 proposer plurality into a 41/96 final score with no harmful override on these cases.
3. Two independent executions of the exact same ten-generalist configuration differed by two total cases and 16 paired case outcomes.

The primary hidden estimate favored the champion over diversified Vote10, but its uncertainty interval included zero. The champion tied Generalist Vote10 and trailed the independently executed copy of that same configuration. Validation selected it by only one case over three survivors.

The supported conclusion is narrow. This bounded search found an auditable verified policy with safe observed overrides, but this run does not establish that evolution or verification generally improves ten-call decision-making.

## Limitations

- **Limited final precision.** Ninety-six paired cases were not enough to exclude zero for a four-case primary difference.
- **Unmeasured between-run variance.** Each genome and final method received one stochastic execution per block. Case bootstrapping does not capture variation across repeated model executions.
- **Close validation selection.** The champion led three survivors by one of 72 cases, so selection noise remains plausible.
- **Adaptive search.** The controller made 48 parent-child decisions across 192 search cases. Fresh blocks reduce reuse, but the full search remains an adaptive selection process.
- **One requested model condition.** Only `gpt-5.6-luna` at low effort was tested. The ledger records the requested configuration, not an independent provider-side model identity.
- **One synthetic domain.** RuleWeave-5 tests exact continuation under eight procedural families. It does not establish transfer to coding, research, markets, or open-ended planning.
- **Bounded grammar.** The search covered six decision systems, eight lenses, and four judge policies. It did not evolve prompts, memory, call count, evidence compression, or adaptive per-case routing.
- **Call equality is not token equality.** Structured roles consumed larger evidence packets than independent solvers.
- **Only three distinct final configurations.** The best founder and Generalist Vote10 were independent replications of one configuration.
- **No monetary comparison.** Stored cost fields are not usable evidence of monetary cost.

## Next experiment

The most direct follow-up is a preregistered replicated decision-layer ablation, not a larger symbolic search.

1. Freeze one shared set of seven proposer outputs per block.
2. Give equal three-call decision budgets to judge-only, two-verifier-plus-judge gate, critic gate, and another registered selector.
3. Repeat every decision arm several times with fresh isolated sessions.
4. Treat repeated executions, not only cases, as sampling units in a hierarchical or two-level uncertainty analysis.
5. Use a larger fresh final set and register the smallest decision-layer gain worth detecting.
6. Report both final accuracy and net override value relative to the shared proposer plurality.

Sharing proposer outputs would isolate the value of the three-call decision layer. Repeated decision runs would estimate the inference variance exposed by the two identical generalist configurations in this experiment.

## Evidence map

- [`PROTOCOL.md`](PROTOCOL.md): frozen question, genome, schedule, budgets, and interpretation boundary
- [`freeze_manifest.json`](freeze_manifest.json): pre-call artifact and plan hashes
- [`benchmark/`](benchmark/README.md): benchmark design, hidden answers, manifest, and overlap audit
- [`genomes/GENOME_CATALOG.json`](genomes/GENOME_CATALOG.json): legal symbols and six founders
- [`genomes/round-01-candidates.json`](genomes/round-01-candidates.json) through [`genomes/round-08-survivors.json`](genomes/round-08-survivors.json): complete search lineage and paired decisions
- [`genomes/best-founder-freeze.json`](genomes/best-founder-freeze.json): founder selected from round-1 evidence
- [`genomes/champion-freeze.json`](genomes/champion-freeze.json): validation ranking and frozen champion
- [`results/search/`](results/search/): round summaries and case matrices
- [`results/validation/`](results/validation/): survivor selection evidence
- [`results/final/`](results/final/): hidden-final summary, paired comparisons, and case matrix
- [`results/analysis.md`](results/analysis.md): deterministic publication analysis
- [`postprocessing/audit_release.py`](postprocessing/audit_release.py) and [`results/release-audit.json`](results/release-audit.json): fail-closed release checks and receipt
- [`runs/`](runs/): prompts, predictions, attempt ledgers, terminal results, and telemetry
- [`postprocessing/build_report.py`](postprocessing/build_report.py): standard-library analysis and chart builder
