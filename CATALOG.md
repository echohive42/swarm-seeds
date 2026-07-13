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
