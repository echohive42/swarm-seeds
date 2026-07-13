# Experiment 04 postprocessing

`build_report.py` creates the release analysis only after all eight search rounds, validation, and the 96-case hidden final are complete.

It writes the following paths relative to the Experiment 04 `experiment/` directory:

- `results/analysis.json`
- `results/analysis.md`
- `../images/final-exact-accuracy.svg`
- `../images/eight-round-trajectory.svg`
- `../images/decision-system-evolution.svg`

The tool uses only the Python standard library. It derives the eight-round trajectory from scored results and replacement receipts, reads decision-system composition from the sealed survivor genomes, and treats the hidden paired comparison as the test of generalization. It reconciles final summary, matrix, and comparison counts and aggregates retries, malformed attempts, tokens, and latency from every append-only attempt ledger.

Run it from the repository root:

```bash
python3 04-evolving-the-decider/experiment/postprocessing/build_report.py
python3 04-evolving-the-decider/experiment/postprocessing/build_report.py --check
```

`--check` reconstructs every report and chart in memory, validates each SVG as XML, and requires byte-for-byte equality with the checked-in outputs.

`audit_release.py` performs the final standard-library release audit and writes `results/release-audit.json`, also relative to the Experiment 04 `experiment/` directory. It checks the freeze, benchmark, evolution receipts, collection accounting, scoring, documentation links, intended release files, and privacy exclusions. Run it from the repository root:

```bash
python3 04-evolving-the-decider/experiment/postprocessing/audit_release.py
```
