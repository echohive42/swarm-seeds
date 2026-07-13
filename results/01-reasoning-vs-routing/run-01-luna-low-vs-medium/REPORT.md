# Luna low-vs-medium agent orchestration experiment

## Bottom line

On the untouched 12-case final benchmark, medium reasoning was the dominant improvement. At medium reasoning, the 10-call independent ensemble and the 10-call 5–2–2–1 collaboration pipeline both reached 91.7% exact-triplet accuracy. Collaboration added no exact-accuracy benefit over the equal-budget ensemble at medium reasoning, while costing about 2.43× the parallel latency and 3.35× the visible-token proxy.

At low reasoning, structured collaboration reached 58.3%, versus 33.3% for the equal-budget ensemble and an estimated 15.8% for one direct call. The +25.0 percentage-point collaboration-versus-ensemble difference is promising but uncertain on only 12 cases: its descriptive case-bootstrap 95% interval spans -16.7 to +66.7 points.

The practical winner in this experiment is therefore the medium-reasoning independent ensemble: it tied the most accurate method and was materially more efficient than collaboration.

## Untouched-final accuracy

| Reasoning | Method | Exact triplets | Term accuracy | Calibration | Rule proxy |
|---|---|---:|---:|---:|---:|
| Low | Direct, expected one call | 15.8% | 16.9% | 0.860 | 5.8% |
| Low | 10-call independent ensemble | 33.3% | 33.3% | 0.548 | 16.7% |
| Low | 10-call collaboration | 58.3% | 58.3% | 0.766 | 50.0% |
| Medium | Direct, expected one call | 55.8% | 60.6% | 0.747 | 33.3% |
| Medium | 10-call independent ensemble | 91.7% | 91.7% | 0.915 | 50.0% |
| Medium | 10-call collaboration | 91.7% | 91.7% | 0.995 | 50.0% |

Direct performance is the mean of ten independent calls over 12 cases, or 120 triplet observations per arm. Each aggregate method produces one result for each of the 12 cases.

## Paired comparisons

| Comparison | Difference | Descriptive 95% case-bootstrap interval | Case wins–losses–ties |
|---|---:|---:|---:|
| Low collaboration − ensemble | +25.0 pp | -16.7 to +66.7 pp | 5–2–5 |
| Low collaboration − direct | +42.5 pp | +8.3 to +75.0 pp | 7–3–2 |
| Low ensemble − direct | +17.5 pp | +1.7 to +37.5 pp | 4–1–7 |
| Medium collaboration − ensemble | 0.0 pp | 0.0 to 0.0 pp | 0–0–12 |
| Medium collaboration − direct | +35.8 pp | +23.3 to +47.5 pp | 11–1–0 |
| Medium ensemble − direct | +35.8 pp | +23.3 to +47.5 pp | 11–1–0 |
| Medium − low direct | +40.0 pp | +25.8 to +53.3 pp | 11–1–0 |
| Medium − low ensemble | +58.3 pp | +33.3 to +83.3 pp | 7–0–5 |
| Medium − low collaboration | +33.3 pp | +8.3 to +58.3 pp | 4–0–8 |

The zero-width medium collaboration-versus-ensemble interval occurs because the two methods had the same correct/incorrect outcome on every one of the 12 cases; both missed F03.

## Cost and reliability

| Reasoning | Method | Deployed calls | Parallel latency | Visible-token proxy | Format compliance |
|---|---|---:|---:|---:|---:|
| Low | Direct | 1 | 48.7 s | 1,191 | 80% |
| Low | Ensemble | 10 | 55.3 s | 11,913 | 80% |
| Low | Collaboration | 10 | 185.8 s | 40,038 | 100% |
| Medium | Direct | 1 | 137.6 s | 1,219 | 100% |
| Medium | Ensemble | 10 | 147.7 s | 12,191 | 100% |
| Medium | Collaboration | 10 | 359.1 s | 40,818 | 100% |

For direct, latency and the visible-token proxy are per-call means; ten experimental replications were run. Ensemble latency is the slowest of ten parallel calls. Collaboration latency is the sum of the slowest call in each sequential stage. Character-derived visible-token counts are proxies, not billed or hidden reasoning tokens; actual hidden reasoning-token usage was not exposed.

The low independent arm had two strict schema failures. Replicate 3 supplied four values for F07, so that otherwise numerically correct prediction was scored wrong. Replicate 9 was unparseable and all 12 of its cases were scored wrong. Excluding only the unparseable call raises low direct accuracy from 15.8% to 17.6%; it does not change the conclusion. The ensemble ignored invalid triples when voting.

## What the experiment supports

1. Medium reasoning substantially improved every method on this benchmark.
2. Collaboration can rescue weak low-reasoning agents, but the low collaboration-versus-ensemble advantage is not stable enough to call conclusive with 12 cases.
3. At medium reasoning, diversity plus deterministic plurality captured all observed accuracy benefit from spending ten calls. The more elaborate collaboration pipeline improved confidence calibration, not exact accuracy.
4. If the objective is accuracy per latency or visible-token proxy, use the medium independent ensemble. If constrained to low reasoning, collaboration was the best observed method, with considerable uncertainty.

## Integrity and reproducibility

- Protocol, benchmark, prompt templates, and schemas were frozen before final evaluation; all 20 frozen hashes remained unchanged.
- The final raw directory was empty at freeze time, and the development audit passed before final execution.
- Low and medium used distinct, fresh, projectless tasks. Every task was explicitly created with `gpt-5.6-luna` and its assigned reasoning setting; low outputs were passed only through low packets and medium outputs only through medium packets.
- Same-arm packet contents exactly match their source raw responses and contain no arm, reasoning, model, stage, archive, or task identifiers.
- The final used 40 successful tasks: ten independent and ten collaborative calls per reasoning arm. Across development and final there were 80 successful tasks plus one stalled final attempt.
- The stalled attempt was archived, identically restarted, recorded separately, and excluded. All 81 tasks were re-archived after execution.
- Every successful raw record is preserved; malformed responses were not silently repaired or rerun.
- Benchmark generation independently reproduced all 16 expected prefixes and continuations.

## Limits

This is a small, curated finite-sequence benchmark. Sequence continuation is inherently underdetermined, and known combinatorial forms may overlap model pretraining. The 12 cases are the statistical units, so bootstrap intervals are descriptive and often wide. Results do not establish a general advantage for orchestration on research, coding, forecasting, or other task types. Model inference can also vary across runs. Finally, the records prove the model and reasoning settings requested at task creation; separate backend `modelUsage` telemetry was not exposed for an additional identity check.

## Artifacts

- `PROTOCOL.md`: frozen design and scoring rules
- `freeze_manifest.json`: immutable-file hashes
- `final_audit.json`: machine-readable integrity audit
- `results/final_summary.csv`: headline metrics
- `results/final_comparisons.csv`: paired differences and bootstrap intervals
- `results/final_case_matrix.csv`: case-level success matrix
- `results/final_cases.csv`: every scored observation
- `results/final_costs.csv`: calls, latency, characters, proxies, and compliance
- `results/final_ensemble.json`: deterministic vote outputs
- `raw/final/`: all final task outputs and failed-attempt metadata
- `packets/final/`: anonymized same-arm stage-transfer packets
- `plots/final-exact-accuracy.svg`: static accuracy chart
