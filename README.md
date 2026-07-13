# Swarm Seeds

Open experiments for learning how AI agents should reason, vote, review, and coordinate.

This repository preserves the actual experiment, not a simplified demo. Each numbered folder contains one reusable `SKILL.md` seed beside the complete run that produced it: protocol, prompts, benchmark, raw agent outputs, failed attempts, scoring, audits, charts, and limitations.

## From Echohive

Swarm Seeds is part of [Echohive](https://www.echohive.ai/), a living laboratory for testing what one person can build with better AI systems and better judgment.

- [Get Amplified](https://www.echohive.ai/get-amplified) is a practical field guide to AI models, agents, harnesses, markets, and methods of mind.
- [1000x Lab](https://www.echohive.ai/1000x-lab) is the live Sunday session where new models, research, workflows, and experiments are examined together.

The links are here for readers who want to continue. The experiment itself remains fully open in this repository.

## 01: Reasoning vs Routing

We gave GPT-5.6 Luna the first 10 integers from mathematical sequences and asked it to predict the next 3 exactly.

The experiment compared:

- one direct AI solver;
- 10 independent AI solvers combined by a deterministic vote;
- a 10-call swarm with 5 proposers, 2 critics, 2 verifiers, and 1 judge;
- low reasoning versus medium reasoning.

On 12 untouched final cases, the medium vote and medium swarm both reached 91.7% exact accuracy. The vote used about 3.3x less visible-token proxy and had about 2.4x lower latency. At low reasoning, the structured swarm performed best, but its advantage over voting remained uncertain on this small benchmark.

[Enter the complete experiment](01-reasoning-vs-routing/README.md)

Direct links:

- [Reusable skill seed](01-reasoning-vs-routing/SKILL.md)
- [Full technical report](01-reasoning-vs-routing/experiment/REPORT.md)
- [Frozen benchmark](01-reasoning-vs-routing/experiment/benchmark/manifest.json)
- [Raw agent outputs](01-reasoning-vs-routing/experiment/raw/)
- [Result images](01-reasoning-vs-routing/images/)

## 02: Hard Sequence Scaling

We made the benchmark harder, increased the hidden final set to 48 RuleWeave-5 cases, and compared 1, 10, and 20-call methods using GPT-5.6 Luna at Light and Medium reasoning.

The best point estimate was 91.67% from a 20-call Medium tournament. A 20-call Medium vote reached 85.42%, but the paired difference was inconclusive. The stronger result was that moving from Light to Medium reasoning added 34.38 percentage points on average, while structured routing added only 1.04 points over equal-call voting.

[Enter the complete experiment](02-hard-sequence-scaling/README.md)

Direct links:

- [Reusable skill seed](02-hard-sequence-scaling/SKILL.md)
- [Full technical report](02-hard-sequence-scaling/experiment/REPORT.md)
- [RuleWeave-5 benchmark](02-hard-sequence-scaling/experiment/benchmark/README.md)
- [Authoritative attempt log](02-hard-sequence-scaling/experiment/raw/final/attempts.jsonl)
- [Result charts](02-hard-sequence-scaling/plots/)

## Repository shape

```text
01-reasoning-vs-routing/
  README.md
  SKILL.md
  experiment/
    PROTOCOL.md
    REPORT.md
    benchmark/
    prompts/
    raw/
    packets/
    results/
    scripts/
    plots/
  images/
02-hard-sequence-scaling/
  README.md
  SKILL.md
  experiment/
    PROTOCOL.md
    REPORT.md
    benchmark/
    prompts/
    raw/
    results/
    scripts/
  plots/
```

Future seeds will follow the same pattern: one numbered folder, one reusable skill, and the complete evidence used to evaluate it.
