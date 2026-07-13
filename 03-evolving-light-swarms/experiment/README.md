# Experiment 03: complete run

This directory contains the frozen design, fresh benchmark, exact prompts, symbolic genomes, orchestration code, 400 registered calls, a 40-call post-unblinding baseline correction, hidden scoring, analysis, and release audit for **Evolving Light Swarms**.

Start with the [technical report](REPORT.md) for the result and interpretation. Read [PROTOCOL.md](PROTOCOL.md) for the design that was frozen before collection.

## Result

The evolved validation champion solved 21/48 untouched final cases and the corrected ten-generalist Vote10 solved 18/48. The +6.25 percentage-point paired estimate favored the champion, but its 95% interval, -4.17 to +16.67 points, included zero and exact McNemar p was 0.453. The best original founder solved 22/48 and fixed Swarm10 solved 20/48. No paired comparison supported superiority.

The frozen protocol specified ten independent generalist solvers, but the original implementation used a mixture of specialized lenses. That mismatch was discovered after final unblinding. [AMENDMENT-01.md](AMENDMENT-01.md) records the correction, chronology, and one execution-timeout deviation: the correction used a 600-second ceiling rather than 300 seconds, although every call completed within 82.308 seconds. The original diversified pool scored 21/48 and remains a separately labeled exploratory sensitivity result.

## Directory map

```text
benchmark/        fresh public cases, hidden answers, generator receipt, audit
genomes/          search catalog, all three populations, selection, champion freeze
prompts/          common restriction prefix, role lenses, output schema
runs/             exact rendered prompts, manifests, ledgers, raw last messages
results/          training, validation, final scoring, analysis, release audit
scripts/          benchmark, evolution, orchestration, execution, scoring, charts
PROTOCOL.md       frozen experimental contract
AMENDMENT-01.md   post-unblinding correction and interpretation boundary
REPORT.md         methods, results, limitations, interpretation
freeze_manifest.json
```

The run folders retain the exact prompts, append-only attempt ledgers, raw `last_message.txt` responses, and parsed `result.json` documents. Incidental CLI event streams and stderr diagnostics are excluded from the public Git release because they contain ephemeral local thread identifiers or machine paths. They are not required to reproduce model answers or scores.

## Reproduce deterministic checks

Run from this directory with Python 3.11 or newer. The experiment scripts use only the Python standard library.

```bash
python3 -B scripts/freeze.py verify
python3 -B scripts/evolve.py self-test
python3 -B scripts/orchestrate.py --self-test
python3 -B scripts/run_jobs.py --self-test
python3 -B scripts/score.py --self-test
python3 -B scripts/audit_benchmark_overlap.py
python3 -B scripts/render_charts.py --check
python3 -B scripts/audit_release.py
```

The benchmark generator is deterministic:

```bash
python3 -B scripts/generate_benchmark.py
python3 -B scripts/freeze.py verify
```

The second command proves the regenerated frozen benchmark is byte-identical.

## Recompute final scoring

The four amended primary methods are already merged into `runs/final/predictions.json`. Recompute the corrected primary analysis with:

```bash
python3 -B scripts/score.py \
  --answers benchmark/hidden/final_answers.jsonl \
  --predictions runs/final/predictions.json \
  --out-dir results/final \
  --final-genome G-1407BDDB752D \
  --baseline Vote10 \
  --baseline G-498E470E7808 \
  --baseline FIXED-SWARM10 \
  --bootstrap-replicates 50000

python3 -B scripts/render_charts.py
python3 -B scripts/render_charts.py --check
python3 -B scripts/audit_release.py
```

The original diversified independent pool is preserved in `runs/final/predictions-diversified-vote.json`. Recompute its separately labeled sensitivity result by changing `--predictions` to that file and `--out-dir` to `results/final-diversified-vote`.

## Model execution contract

Every experimental command requested:

- model `gpt-5.6-luna`;
- provider reasoning effort `low`, labeled publicly as Light reasoning;
- a fresh ephemeral Codex CLI process;
- read-only empty workspace;
- disabled shell, Python, tools, browsing, plugins, skills, images, apps, and multi-agent features.

The exact sanitized command is preserved in each attempt's `command.json`. The response ledger did not expose an independent provider-reported model identity, so the release can attest the requested configuration and command, not a separate provider-side model field.

## Collection accounting

| Run | Planned calls | Valid first attempts |
|---|---:|---:|
| Search Generation 0 | 60 | 60 |
| Search Generation 1 | 60 | 60 |
| Search Generation 2 | 60 | 60 |
| Validation | 60 | 60 |
| Final structured methods | 120 | 120 |
| Original diversified independent pool | 40 | 40 |
| **Registered total** | **400** | **400** |
| Amendment 01 generalist Vote10 correction | 40 | 40 |
| **Total recorded execution** | **440** | **440** |

No experimental call required a retry. Separate pre-run smoke tests are outside the registered 400-call budget and are not published with the scored run. The correction restores the protocol-determined baseline, but because it was collected after unblinding, that chronology remains explicit throughout the release.

The request-identity audit confirms a 300-second ceiling for all 400 registered calls and a 600-second ceiling for the 40 correction calls. No correction call timed out; the longest completed in 82.308 seconds. This did not rescue or censor any correction output, but it remains a disclosed deviation from the registered execution contract.

See [results/release-audit.json](results/release-audit.json) for machine-checked identities, closure, concurrency, freeze integrity, and release privacy.
