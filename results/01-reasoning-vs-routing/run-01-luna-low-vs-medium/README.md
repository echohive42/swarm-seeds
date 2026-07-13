# Run 01 — GPT-5.6 Luna: low versus medium reasoning

This experiment asked a simple question:

> Is it better to spend compute on deeper reasoning, more independent answers, or agents that critique and verify one another?

It tested one model, `gpt-5.6-luna`, at low and medium reasoning on 12 untouched finite-sequence problems.

## The three methods

**Direct**

One solver answers alone. Ten separate calls were run to estimate how often one deployed call would succeed.

**Independent ensemble**

Ten solvers answer separately. A fixed voting rule selects the most supported answer.

**Structured collaboration**

Five agents propose answers, two criticize them, two independently verify them, and one judge makes the final decision. This also uses ten calls.

The ensemble and collaboration therefore have the same call budget.

## Main result

| Reasoning | Direct | Ensemble | Collaboration |
|---|---:|---:|---:|
| Low | 15.8% | 33.3% | 58.3% |
| Medium | 55.8% | 91.7% | 91.7% |

Accuracy means the complete next-three-number prediction was exactly correct.

![Exact next-three accuracy for the low and medium reasoning arms](plots/final-exact-accuracy.svg)

## What this means

Medium reasoning produced the largest improvement.

At medium reasoning, the simple independent ensemble matched structured collaboration at 91.7% accuracy. Collaboration took about 2.43 times as long on the parallel critical path and used about 3.35 times the visible-token proxy.

At low reasoning, collaboration performed much better than the ensemble in this run. However, the final benchmark had only 12 cases. The descriptive bootstrap interval for collaboration minus ensemble was wide and crossed zero, so the result is promising rather than conclusive.

The practical winner for this benchmark was the **medium-reasoning independent ensemble**: it tied for best accuracy and was substantially more efficient than collaboration.

## Reliability notes

- Two low-reasoning independent calls failed the strict output schema.
- One completed response returned four values where exactly three were required.
- One response was not valid JSON.
- Both failures were preserved and penalized rather than silently repaired.
- One separate low-reasoning task stalled, was archived, and was restarted with the identical prompt.
- All frozen-file and isolation checks passed.

## Important limitation

This was a small, curated finite-sequence benchmark. Finite sequences are inherently underdetermined, and some patterns may have appeared in model training. These results do not prove that the same method will win on coding, research, forecasting, or other kinds of work.

## Read next

- [Reusable seed](../../../skills/01-reasoning-vs-routing/SKILL.md)
- [Full report](REPORT.md)
- [Frozen protocol](PROTOCOL.md)
- [Summary table](results/final_summary.csv)
- [Paired comparisons](results/final_comparisons.csv)
- [Case-level matrix](results/final_case_matrix.csv)
- [Final integrity audit](final_audit.json)
- [Static result chart](plots/final-exact-accuracy.svg)

## File guide

| Path | Contents |
|---|---|
| `benchmark/` | Development and untouched-final cases with expected answers |
| `prompts/` | Exact subject-role and output-schema prompts |
| `raw/` | Preserved model outputs, durations, confidence, and failures |
| `packets/` | Anonymous same-arm information passed between collaboration stages |
| `results/` | Case scores, summaries, costs, ensemble outputs, and comparisons |
| `scripts/` | Benchmark verification, scoring, comparison, and audit code |
| `plots/` | A compact accuracy chart |

Internal Codex task UUIDs were replaced with readable public task labels. No prompt, prediction, confidence value, timing, score, or failure record was changed.
