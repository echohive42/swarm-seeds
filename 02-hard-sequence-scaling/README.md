# 02: Hard Sequence Scaling

This folder contains the second Swarm Seeds experiment and the reusable orchestration seed it produces.

## The question

When mathematical sequence problems become substantially harder, what is the best use of extra AI compute?

- Ask one GPT-5.6 Luna agent.
- Ask 10 or 20 independent agents and combine exact answers by vote.
- Route the same call budget through specialized proposers, critics, verifiers, and judges.
- Increase Luna from Light reasoning to Medium reasoning.

The key comparison holds the budget fixed. A 20-call independent vote is compared with a 20-call tournament. This tests whether coordination adds value beyond independent sampling.

## The benchmark

The experiment uses a new procedural benchmark named RuleWeave-5. Every case shows 12 to 14 integer terms and asks for the next 5 terms exactly.

The generator combines eight registered rule families:

- polynomial sequences;
- periodic polynomial differences;
- periodic affine recurrences;
- second-order recurrences with periodic bias;
- lagged polynomial recurrences;
- interleaved subsequences;
- growing arithmetic blocks;
- modular affine recurrences.

Random coefficients and seeds create new cases that are unlikely to be memorized. All values are represented as decimal strings so the exact integers remain portable across tools.

## Frozen design

- 12 development cases
- 12 calibration cases
- 48 untouched final cases
- 4 final blocks with 12 cases each
- 8 rule families and 3 difficulty tiers
- exactly 2 final cases for every family and tier combination
- GPT-5.6 Luna Light reasoning and Medium reasoning
- no tools, code, calculators, browsing, files, or communication for experimental subjects

Each model call receives one complete 12-case block. The final run therefore uses 400 Luna calls and produces 4,800 case-level responses.

## Methods

| Method | Deployment calls | Structure |
|---|---:|---|
| Direct | 1 | One isolated solver, estimated from 20 independent repetitions |
| Vote10 | 10 | Fixed independent slots S01 through S10 |
| Swarm10 | 10 | 5 proposers, 2 critics, 2 verifiers, 1 judge |
| Vote20 | 20 | All 20 independent solver slots |
| Tournament20 | 20 | 8 explorers, 4 breakers, 4 verifiers, 2 synthesizers, 1 red team, 1 judge |

The independent pool is reused for Direct, Vote10, and Vote20. The structured arms use fresh calls and never see independent-arm outputs. Light and Medium remain isolated.

## Failure rule

Infrastructure failures are preserved and restarted with the identical frozen prompt, up to two retries. A completed malformed response is a model failure. It is preserved, scored under the frozen rule, and never repaired or rerun.

## Result

The 400-call final run is complete.

| Reasoning | Direct expected | Vote10 | Swarm10 | Vote20 | Tournament20 |
|---|---:|---:|---:|---:|---:|
| Light | 27.92% | 58.33% | 45.83% | 50.00% | 43.75% |
| Medium | 48.33% | 70.83% | 87.50% | 85.42% | **91.67%** |

Medium reasoning produced the largest gain. Averaged across the four multi-call methods, moving from Light to Medium added 34.38 percentage points. Changing from voting to structured routing at equal call budgets added only 1.04 points on average.

The highest score came from Medium Tournament20 at 44 of 48 exact cases. It beat Medium Vote20 by 3 cases, but the paired primary comparison was inconclusive: +6.25 points, exact McNemar p = 0.375, bootstrap 95% interval from -2.08 to +14.58 points.

![Final exact accuracy](plots/accuracy_by_condition.svg)

## What this means

On RuleWeave-5, stronger reasoning mattered much more than a more elaborate agent diagram. Independent voting remained a strong and simpler baseline. Structured collaboration became more promising at Medium reasoning, but this run does not prove that it beats an equal-call vote.

## Open the evidence

- [Full technical report](experiment/REPORT.md)
- [Reusable skill seed](SKILL.md)
- [Frozen protocol](experiment/PROTOCOL.md)
- [RuleWeave-5 benchmark](experiment/benchmark/README.md)
- [Exact prompts](experiment/prompts/)
- [Authoritative final attempt log](experiment/raw/final/attempts.jsonl)
- [Scored results](experiment/results/scored_results.json)
- [Statistical analysis](experiment/results/analysis.json)
- [Public-release audit](experiment/results/release_audit.json)
- [Charts](plots/)

## Continue with Echohive

This experiment is fully open here. If you want the broader work behind it:

- [Echohive](https://www.echohive.ai/) is the living lab where these systems are built and tested.
- [Get Amplified](https://www.echohive.ai/get-amplified) is the practical field guide for using current AI models, agents, and harnesses to attempt larger work.
- [1000x Lab](https://www.echohive.ai/1000x-lab) is the live Sunday session where new methods, research, and experiments are worked through together.
