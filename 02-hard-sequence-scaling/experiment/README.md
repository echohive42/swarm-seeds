# Experiment 02: Hard Sequence Scaling

This directory preserves the complete, reproducible run behind Swarm Seed 02.

## Collection sequence

1. Generate development, calibration, and final RuleWeave-5 cases from fixed seeds.
2. Verify registered-grammar uniqueness, value bounds, family balance, and tier balance.
3. Run development cases to test only the machinery.
4. Freeze benchmark hashes, prompts, routing, schemas, retry rules, and analysis rules.
5. Run four final blocks without inspecting correctness.
6. Restart infrastructure failures with the identical frozen prompt.
7. Close collection before revealing the hidden final answer manifest.
8. Score, audit, analyze uncertainty, create charts, and write the reusable seed.

## Final result

Collection closed with all 400 planned GPT-5.6 Luna calls. Medium Tournament20 had the highest point estimate at 91.67% exact accuracy. Its +6.25-point difference over Medium Vote20 was inconclusive under the preregistered paired test.

The main finding was broader: the average Medium-over-Light reasoning lift was +34.38 points, while the average structured-over-vote routing lift was +1.04 points.

Read [`REPORT.md`](REPORT.md) for the complete result, exact sequence mathematics, uncertainty, cost, limitations, and protocol deviations.

## Evidence

```text
PROTOCOL.md
ANALYSIS_PLAN.md
freeze_manifest.json
benchmark/
prompts/
raw/
packets/
results/
scripts/
plots/
```

Raw attempts, including failures, remain part of the public record. Internal task identifiers will be replaced with stable experiment labels before release.

Four completed Light Tournament20 verifier responses were malformed. They remain in the attempt log and were not rerun. A documented packet-limit amendment completed five unopened final judges without changing their prompt contents. See [`PROTOCOL_AMENDMENT_01.md`](PROTOCOL_AMENDMENT_01.md).

The experiment uses only Python standard-library scripts. The post-collection scorer and audit overlays preserve the frozen base files and record both hashes in provenance.
