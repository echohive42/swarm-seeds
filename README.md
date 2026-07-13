# Swarm Seeds

Open experiments for learning how AI agents should reason, vote, review, and coordinate.

This repository preserves the actual experiment, not a simplified demo. Each numbered folder contains one reusable `SKILL.md` seed beside the complete run that produced it: protocol, prompts, benchmark, raw agent outputs, failed attempts, scoring, audits, charts, and limitations.

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
```

Future seeds will follow the same pattern: one numbered folder, one reusable skill, and the complete evidence used to evaluate it.

## From Echohive

Swarm Seeds is part of [Echohive](https://www.echohive.ai/), a living laboratory for testing what one person can build with better AI systems and better judgment.

- [Get Amplified](https://www.echohive.ai/get-amplified) is a practical field guide to AI models, agents, harnesses, markets, and methods of mind.
- [1000x Lab](https://www.echohive.ai/1000x-lab) is the live Sunday session where new models, research, workflows, and experiments are examined together.

The links are here for readers who want to continue. The experiment itself remains fully open in this repository.
