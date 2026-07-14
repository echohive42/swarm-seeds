# Stage 2 visuals

These images explain the adaptive visible-holdout result.

| File | Meaning |
|---|---|
| `fresh-gate-progress.png` | Fresh-gate accuracy for the base plurality and adaptive system. The Gate 02 weighted replay is explicitly labeled development only. |
| `gate03-paired-outcomes.png` | Sixteen base answers stayed correct, six errors were repaired, two remained wrong, and zero correct answers were harmed. |
| `adaptive-call-flow.png` | The four-stage frozen orchestration, its 268 actual calls, 568 per-sequence analyses, and 22/24 result. |
| `gate03-family-results.png` | Exact Gate 03 results across all eight generator families. |
| `visible-holdout-example.png` | A real case where reconstructing two hidden public terms identified the exact future continuation. |
| `verification-convergence.png` | Generated editorial illustration of many candidate paths passing through verification windows. |
| `visible-holdout-concept.png` | Generated editorial illustration of candidate branches tested against hidden public evidence. |

The five plots have both SVG and 1600 by 900 PNG versions. Recreate their SVG sources with:

```bash
python3 experiment/scripts/render_stage2_charts.py
```

The script uses only the Python standard library and reads the recorded experiment results.

The two abstract illustrations were created with OpenAI's built-in image generator. Their prompts requested minimal editorial diagrams with no text, robots, brains, code, logos, or decorative technology imagery. They are supporting artwork, not experimental evidence.
