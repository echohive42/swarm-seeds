# Experiment 04: complete run

This directory contains the frozen design, fresh RuleWeave-5 benchmark, symbolic genome catalog, all eight search rounds, validation selection, hidden-final comparison, exact prompts, attempt ledgers, scores, deterministic analysis, and publication charts for **Evolving the Decider**.

Start with the [technical report](REPORT.md) for the result and interpretation. Read the [frozen protocol](PROTOCOL.md) for the design registered before collection.

## Result

The validation-selected champion solved 41/96 hidden-final cases and diversified Vote10 solved 37/96. The paired estimate was +4.2 percentage points, with a 95% interval from -2.1 to +10.4 points and exact McNemar p = 0.3438. The interval includes zero, so superiority was not established.

The best initial founder solved 43/96 and Generalist Vote10 solved 41/96. Those two methods are the exact same ten-generalist plurality configuration, run independently in fresh sessions. The final comparison therefore contains four execution arms but three unique symbolic configurations. Their different scores show ordinary execution variation rather than an architecture effect.

The evolved champion used seven proposers, two verifiers, and one judge. Proposal plurality solved 38/96. Its strict agreement gate made 11 overrides and raised the final score to 41/96: 3 overrides were useful, 0 harmful, and 8 neutral. The judge-alone counterfactual also solved 41/96, so this sample supports safe gating but not a verifier accuracy gain over the judge.

## Directory map

```text
benchmark/          360 fresh cases, hidden answers, manifest, overlap audit
genomes/            catalog, founders, 8 candidate sets, 8 survivor sets, freezes
postprocessing/     deterministic analysis and SVG builder
prompts/            frozen common prefix, lenses, judge policies, output schema
results/            8 search scores, validation scores, final scores, analysis
runs/               rendered prompts, manifests, predictions, ledgers, responses
scripts/            generation, evolution, orchestration, execution, scoring
PROTOCOL.md         frozen experimental contract
REPORT.md           methods, results, limitations, interpretation
freeze_manifest.json
```

The run folders retain rendered prompts, stage manifests, append-only attempt ledgers, parsed terminal results, and normalized predictions. Hidden answer files are public for audit now that collection is complete. Do not expose them to subject models in a replication.

## Deterministic checks

Run from this directory with Python 3.11 or newer. The experiment controller and postprocessing use only the Python standard library.

```bash
python3 -B scripts/freeze.py verify
python3 -B scripts/evolve.py self-test
python3 -B scripts/orchestrate.py --self-test
python3 -B scripts/run_jobs.py --self-test
python3 -B scripts/score.py --self-test
python3 -B scripts/audit_benchmark_overlap.py
python3 -B postprocessing/build_report.py --check
python3 -B postprocessing/audit_release.py
```

Regenerating the benchmark or analysis is deterministic:

```bash
python3 -B scripts/generate_benchmark.py
python3 -B scripts/freeze.py verify
python3 -B postprocessing/build_report.py --check
```

The freeze verification after benchmark generation proves that the regenerated files are byte-identical to the frozen benchmark.

## Recompute hidden-final scoring

The four methods are already merged in `runs/final/predictions.json`.

```bash
python3 -B scripts/score.py \
  --answers benchmark/hidden/final_answers.jsonl \
  --predictions runs/final/predictions.json \
  --out-dir results/final \
  --final-genome evolved_champion \
  --baseline diversified_vote10 \
  --baseline best_initial_founder \
  --baseline generalist_vote10 \
  --bootstrap-replicates 50000

python3 -B postprocessing/build_report.py --check
```

`scripts/run_experiment.py` is the collection driver. Running it requires a subject-model executable and can launch the complete 2,600-identity experiment, plus any registered retries, so it is not needed to verify the published evidence.

## Requested model condition

Every experimental identity requested:

- model `gpt-5.6-luna`;
- provider reasoning effort `low`, labeled publicly as Light reasoning;
- Standard service tier;
- a fresh isolated process;
- no shell, code, Python, browsing, files, tools, plugins, skills, or other agents for subject calls.

The ledger attests the requested configuration. It does not contain a separate provider-reported model-identity field.

## Collection accounting

| Phase | Logical call identities | Actual attempts |
|---|---:|---:|
| Eight-round search | 1,920 | 1,924 |
| Validation | 360 | 360 |
| Hidden final | 320 | 320 |
| **Total** | **2,600** | **2,604** |

Four first attempts were schema-invalid and received the one registered identical retry. All 2,600 logical identities ended with valid output. The release preserves the four malformed attempts. There were no infrastructure-failure attempts, exhausted jobs, or protocol violations.

Across all 2,604 attempts, the runner recorded 34,692,166 input tokens, 6,849,421 output tokens, and 145,422.086 seconds of summed call latency. These are aggregate call totals, not elapsed wall time.

## Blinding and freeze chain

All cases, hidden programs, next-five targets, answer hashes, prompts, schemas, scripts, founders, call plans, and the evolution seed were frozen before collection.

- Each search round opened only its own 24-case answer file after all 240 logical calls were terminal.
- Validation answers opened only after all 360 survivor-validation calls were terminal.
- The champion was frozen from validation before hidden-final collection.
- Final answers opened only after all 320 final calls were terminal.

The benchmark overlap audit reports zero internal duplicates and zero overlap with Experiments 02 and 03 in visible prefixes, canonical hidden programs, or next-five targets.

## Known frozen-summary field caveat

Generated score summaries retain an inherited `methods.*.fitness_key_without_hash` convenience field with the older four-part order. It omits weakest-block exact accuracy and is inconsistent with Experiment 04's declared five-part fitness.

Do not use that convenience field to reconstruct selection. The authoritative `protocol_fitness_key`, `genome_scores`, case matrices, selection receipts, and founder/champion freezes all use the correct five-part order:

```text
[exact cases, weakest-block exact, -harmful overrides, correct terms, format-valid cases]
```

The actual selections and reported outcomes are correct. The frozen summaries remain unchanged so the release does not rewrite post-run evidence.
