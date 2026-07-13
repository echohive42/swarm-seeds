# Seed catalog

## 01: Reasoning vs Routing

**Question:** When solving a hard pattern task, should compute go toward deeper reasoning, more independent agents, or a structured agent swarm?

**Simple answer:** Medium reasoning was the largest improvement. At medium reasoning, a 10-agent vote matched the exact accuracy of the more complex 5→2→2→1 swarm while using much less visible-token proxy and latency.

**Open the complete seed:** [01-reasoning-vs-routing](01-reasoning-vs-routing/README.md)

Inside the folder:

- [Reusable `SKILL.md`](01-reasoning-vs-routing/SKILL.md)
- [Actual experiment](01-reasoning-vs-routing/experiment/README.md)
- [Technical report](01-reasoning-vs-routing/experiment/REPORT.md)
- [Raw outputs](01-reasoning-vs-routing/experiment/raw/)
- [Result images](01-reasoning-vs-routing/images/)

## 02: Hard Sequence Scaling

**Question:** On a harder 48-case benchmark, does extra compute work best as stronger reasoning, more independent votes, or a structured 10-call or 20-call team?

**Simple answer:** Medium reasoning was the dominant improvement. Medium Tournament20 had the highest score at 91.67%, but its +6.25-point edge over Medium Vote20 was inconclusive. Across equal budgets, routing added far less than stronger reasoning.

**Open the complete seed:** [02-hard-sequence-scaling](02-hard-sequence-scaling/README.md)

Inside the folder:

- [Reusable `SKILL.md`](02-hard-sequence-scaling/SKILL.md)
- [Actual experiment](02-hard-sequence-scaling/experiment/README.md)
- [Technical report](02-hard-sequence-scaling/experiment/REPORT.md)
- [Raw final attempts](02-hard-sequence-scaling/experiment/raw/final/attempts.jsonl)
- [Result charts](02-hard-sequence-scaling/plots/)

## 03: Evolving Light Swarms

**Question:** Can a deterministic evolutionary search discover a 10-call GPT-5.6 Luna Light orchestration policy that beats an equal-call independent vote?

**Simple answer:** The evolved champion scored 21/48 and the corrected ten-generalist Vote10 scored 18/48, a promising but inconclusive +6.25-point estimate. The best unevolved founder scored 22/48. An audit found that the original independent pool used mixed lenses; it scored 21/48 and is preserved as a superseded sensitivity result. The run exposes selection noise and the value of implementation audits.

**Open the complete seed:** [03-evolving-light-swarms](03-evolving-light-swarms/README.md)

Inside the folder:

- [Reusable `SKILL.md`](03-evolving-light-swarms/SKILL.md)
- [Actual experiment](03-evolving-light-swarms/experiment/README.md)
- [Technical report](03-evolving-light-swarms/experiment/REPORT.md)
- [Baseline correction and chronology](03-evolving-light-swarms/experiment/AMENDMENT-01.md)
- [Symbolic genomes and lineage](03-evolving-light-swarms/experiment/genomes/)
- [Run records and raw last messages](03-evolving-light-swarms/experiment/runs/)
- [Result charts](03-evolving-light-swarms/images/)

## 04: Evolving the Decider

**Question:** Can an eight-generation symbolic search improve how ten calls using the requested GPT-5.6 Luna Light configuration decide together when the decision mechanism itself can evolve?

**Simple answer:** The evolved 7-proposer, 2-verifier, 1-judge champion scored 41/96 versus 37/96 for diversified Vote10, but the paired interval crossed zero. It tied a fresh generalist Vote10 run and trailed an independent run of the same founder configuration. Its strongest signal was narrower: the agreement gate applied 11 overrides, added 3 correct cases, and harmed none in this sample.

**Open the complete seed:** [04-evolving-the-decider](04-evolving-the-decider/README.md)

Inside the folder:

- [Reusable `SKILL.md`](04-evolving-the-decider/SKILL.md)
- [Actual experiment](04-evolving-the-decider/experiment/README.md)
- [Technical report](04-evolving-the-decider/experiment/REPORT.md)
- [Fresh benchmark](04-evolving-the-decider/experiment/benchmark/README.md)
- [Symbolic genomes and lineage](04-evolving-the-decider/experiment/genomes/)
- [Run records and attempt ledgers](04-evolving-the-decider/experiment/runs/)
- [Result charts](04-evolving-the-decider/images/)
