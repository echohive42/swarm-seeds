# Swarm Seeds

Open experiments for learning how AI agents should reason, vote, review, and coordinate.

This repository preserves the actual experiment, not a simplified demo. Each numbered folder contains one reusable `SKILL.md` seed beside the complete run that produced it: protocol, prompts, benchmark, raw agent outputs, failed attempts, scoring, audits, charts, and limitations.

> [!IMPORTANT]
> ### Latest breakthrough: make agents prove their answers
>
> On a fresh, balanced 24-sequence gate, a Luna Light plurality solved **16/24 cases, or 66.7%**. An adaptive system using **visible self-verification** solved **22/24, or 91.7%**. It repaired six plurality errors and harmed none of the correct answers.
>
> The key idea was to hide known public terms and require agents to reconstruct them before trusting their unknown prediction. This is a strong sequence-domain result, not a universal accuracy claim.
>
> **[Read Experiment 05: Adaptive Orchestration Search →](05-adaptive-orchestration-search/README.md)**

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

## 03: Evolving Light Swarms

We held GPT-5.6 Luna at Light reasoning and evolved only the way ten calls were organized. Six symbolic policies ran for three generations across four topology families. A deterministic Python program made mutations and crossovers; no model rewrote its own prompt or genome.

The search improved the best observed training score from 8/12 to 9/12 and found a validation champion at 13/24. On 48 untouched final cases, that champion scored 21/48 while the corrected ten-generalist Vote10 scored 18/48. The +6.25 percentage-point estimate was promising but inconclusive: its paired 95% interval was -4.17 to +16.67 points. The best original founder scored 22/48 and fixed Swarm10 scored 20/48.

The original independent pool accidentally used a mixture of specialized lenses and scored 21/48, tying the champion. A post-unblinding amendment restored the protocol's generalist baseline and preserves both outcomes transparently. The result shows why small evolutionary gains need a large hidden comparison and why implementation audits matter.

[Enter the complete experiment](03-evolving-light-swarms/README.md)

Direct links:

- [Reusable skill seed](03-evolving-light-swarms/SKILL.md)
- [Full technical report](03-evolving-light-swarms/experiment/REPORT.md)
- [Baseline correction and chronology](03-evolving-light-swarms/experiment/AMENDMENT-01.md)
- [Fresh RuleWeave-5 benchmark](03-evolving-light-swarms/experiment/benchmark/README.md)
- [Symbolic genomes and lineage](03-evolving-light-swarms/experiment/genomes/README.md)
- [Run records](03-evolving-light-swarms/experiment/runs/)
- [Result charts](03-evolving-light-swarms/images/)

## 04: Evolving the Decider

We requested GPT-5.6 Luna at Light reasoning and let a deterministic evolutionary controller change how ten calls reached one answer. The search could choose among plain voting, judges, critics, verifiers, worker lenses, and decision policies. It ran all eight frozen generations with no early stopping, then selected one champion on 72 fresh validation cases.

The evolved champion used 7 proposers, 2 verifiers, and 1 minority-aware judge. On 96 untouched final cases it scored 41/96, compared with 37/96 for diversified Vote10. The +4.17 percentage-point estimate was encouraging but inconclusive: its paired 95% interval was -2.08 to +10.42 points. The champion tied a fresh generalist Vote10 run at 41/96 and trailed an independent run of the same all-generalist founder configuration at 43/96.

The clearest positive signal was inside the evolved system. Its agreement gate changed 11 plurality answers, improving 3 cases and harming none in this sample. Evolution discovered a promising decider, but this run did not establish that it is generally safer or that it beats simple voting overall.

[Enter the complete experiment](04-evolving-the-decider/README.md)

Direct links:

- [Reusable skill seed](04-evolving-the-decider/SKILL.md)
- [Full technical report](04-evolving-the-decider/experiment/REPORT.md)
- [Fresh benchmark](04-evolving-the-decider/experiment/benchmark/README.md)
- [Symbolic genomes and lineage](04-evolving-the-decider/experiment/genomes/README.md)
- [Run records](04-evolving-the-decider/experiment/runs/)
- [Result charts](04-evolving-the-decider/images/)

## 05: Adaptive Orchestration Search

We let the research process change prompts, roles, routing, and deterministic selection while keeping GPT-5.6 Luna at Light reasoning. The key improvement was visible self-verification: agents had to reconstruct one to three hidden public terms before their unknown continuation could influence the result.

On a fresh balanced Gate 03 set, the frozen 15-lens plurality solved 16/24 sequences, or 66.7%. The final adaptive system solved 22/24, or 91.7%, using 268 calls across the 24 cases. It corrected six plurality errors and harmed zero correct plurality answers. This is a strong sequence-domain result, not evidence of 91.7% accuracy on arbitrary reasoning tasks.

[Enter the complete experiment](05-adaptive-orchestration-search/README.md)

Direct links:

- [Reusable skill seed](05-adaptive-orchestration-search/SKILL.md)
- [Full technical report](05-adaptive-orchestration-search/experiment/REPORT.md)
- [Fresh Gate 03 score](05-adaptive-orchestration-search/experiment/results/fresh-80-gate-03/score.json)
- [Progress data](05-adaptive-orchestration-search/experiment/results/fresh-gate-progress.csv)
- [Result charts](05-adaptive-orchestration-search/images/stage-2/)

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
03-evolving-light-swarms/
  README.md
  SKILL.md
  experiment/
    PROTOCOL.md
    REPORT.md
    benchmark/
    genomes/
    prompts/
    runs/
    results/
    scripts/
  images/
04-evolving-the-decider/
  README.md
  SKILL.md
  experiment/
    PROTOCOL.md
    REPORT.md
    benchmark/
    genomes/
    postprocessing/
    prompts/
    runs/
    results/
    scripts/
  images/
05-adaptive-orchestration-search/
  README.md
  SKILL.md
  experiment/
    PROTOCOL.md
    EXPLORATORY_EXTENSION.md
    REPORT.md
    benchmark/
    prompts/
    registrations/
    results/
    runs/
    scripts/
  images/
```

Future seeds will follow the same pattern: one numbered folder, one reusable skill, and the complete evidence used to evaluate it.
