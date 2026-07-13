# Swarm Seeds

Small, tested patterns for growing more capable agent systems.

A **seed** is one self-contained `SKILL.md` file. It explains an orchestration pattern clearly enough to reuse, adapt, and test. Each seed has a matching results folder containing the experiment that motivated it—including prompts, benchmarks, outputs, scoring, audits, and limitations.

Swarm Seeds comes from [Echohive](https://www.echohive.ai/), a living laboratory for learning what becomes possible when AI systems, better tools, and human judgment work together.

If you want to go further:

- [Get Amplified](https://www.echohive.ai/get-amplified) is an evolving field guide to using AI systems, agents, markets, and methods of mind more effectively.
- [1000x Lab](https://www.echohive.ai/1000x-lab) is the live Sunday room where new models, research, workflows, and experiments are put on the board and tested together.

## Seeds

| Seed | Simple description | Evidence |
|---|---|---|
| [01 — Reasoning vs. Routing](skills/01-reasoning-vs-routing/SKILL.md) | Tests when deeper reasoning, independent voting, or structured collaboration produces better answers. | [Luna low-vs-medium run](results/01-reasoning-vs-routing/run-01-luna-low-vs-medium/README.md) |

## How the repository is organized

```text
skills/
  01-reasoning-vs-routing/
    SKILL.md

results/
  01-reasoning-vs-routing/
    run-01-luna-low-vs-medium/
      README.md
      REPORT.md
      PROTOCOL.md
      benchmark/
      prompts/
      raw/
      results/
      scripts/
      plots/
```

The number is permanent. A seed can improve without changing its identity. New experimental runs are added beneath the matching results folder instead of overwriting old evidence.

## How to use a seed

1. Open its `SKILL.md`.
2. Read the purpose and non-negotiable safeguards.
3. Adapt the task-specific parts while preserving the experimental controls.
4. Run a development split before an untouched final split.
5. Keep the raw outputs—including failures—and report uncertainty honestly.

These seeds are starting points, not universal claims. A pattern that works on one benchmark may fail on another. The results are included so each idea can be judged by its evidence rather than its name.
