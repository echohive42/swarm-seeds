# Experiment 02 charts

This directory holds deterministic SVG charts rendered from the closed Experiment 02 analysis output. The renderer does not contain or infer experimental results. Its `--self-test` mode uses conspicuously labeled synthetic data.

## Render

From the experiment directory:

```bash
python3 scripts/render_charts.py
```

By default the script reads `results/analysis.json` and, when present, `results/final_summary.csv`. Explicit inputs can be repeated and merged:

```bash
python3 scripts/render_charts.py \
  --input results/analysis.json \
  --input results/final_summary.csv \
  --output-dir plots
```

Only charts supported by fields in the supplied data are written. In particular, the cost frontier is omitted unless condition rows contain a cost field. Existing SVG files are overwritten only when their corresponding chart is rendered; the script does not delete stale files.

Run the dependency-free validation suite with:

```bash
python3 scripts/render_charts.py --self-test
```

## Canonical JSON schema

`results/analysis.json` may contain the following fields. Numbers shown here describe fields, not results.

```json
{
  "metadata": {
    "source_note": "Experiment 02 final analysis output"
  },
  "methods": [
    {
      "method": "Direct expected | Vote10 | Swarm10 | Vote20 | Tournament20",
      "reasoning": "Light reasoning | Medium reasoning",
      "exact_accuracy": {"estimate": 0.0, "ci95": [0.0, 0.0]},
      "deployment_calls": 0.0,
      "cost": {
        "provider_cost_usd": {"estimate": 0.0},
        "total_tokens": {"estimate": 0.0}
      },
      "format_rate": {"estimate": 0.0}
    }
  ],
  "comparisons": [
    {
      "left": "Vote20",
      "right": "Tournament20",
      "reasoning": "medium",
      "difference": 0.0,
      "ci95": [0.0, 0.0]
    }
  ],
  "primary": {
    "left": "Medium reasoning Vote20",
    "right": "Medium reasoning Tournament20",
    "difference": 0.0,
    "ci95": [0.0, 0.0],
    "vote20_only_wins": 0,
    "tournament20_only_wins": 0,
    "both_correct": 0,
    "both_incorrect": 0
  },
  "blocks": [
    {
      "block": "B1",
      "reasoning": "Light reasoning",
      "methods": {
        "Direct expected": {"exact_accuracy": 0.0}
      }
    }
  ],
  "operational_reliability": [
    {
      "reasoning": "Light reasoning",
      "method": "Vote10",
      "format_rate": 0.0,
      "retry_failure_rate": 0.0
    }
  ]
}
```

`operational_reliability` may also be an object containing its canonical rows under `rows`, `conditions`, `by_condition`, or `by_method`. CSV inputs use the same field names plus an optional `section` column (`conditions`, `paired`, `blocks`, or `reliability`). Common aliases such as `condition`, `strategy`, `accuracy`, `avg_calls`, `ci_low`, and `ci_high` are accepted. Reliability rows may use `retry_failure_rate`, `retry_rate`, `failure_rate`, or `infrastructure_failure_rate`. Accuracy and reliability values may be fractions or percent strings. Provider-specific effort metadata are normalized to the public label **Luna Light reasoning** in every chart.

## Outputs

- `accuracy_by_condition.svg`: Luna Light vs Luna Medium exact accuracy across all five methods.
- `equal_budget_routing.svg`: Vote10 vs Swarm10 and Vote20 vs Tournament20.
- `accuracy_vs_calls.svg`: observed accuracy/call points with a nondominated frontier guide.
- `primary_paired_outcomes.svg`: primary wins, losses, ties, estimate, and 95% interval.
- `block_sensitivity.svg`: block-level accuracy traces when at least two blocks exist.
- `format_retry_reliability.svg`: aggregate format-valid and retry/failure rates.
- `accuracy_vs_cost.svg`: optional cost frontier when a cost field exists.

Every file is a standalone, valid SVG with a title, description, direct labels, accessible high-contrast colors, and a source note. Chart creation should occur only after collection is closed and final data are scored.
