# Experiment 04: Evolving the Decider

The evolved champion differed from diversified Vote10 by +4.2 pp, but the paired 95% interval [-2.1 pp, +10.4 pp] included zero, so superiority was not established.

## What was tested

Six decision systems competed under the same budget: ten Luna Light calls per 12-case block. The genome could change the worker lenses, judge policy, and whether the group used plain voting, one judge, gated criticism, two judges, verification, or deliberation. The search ran all eight registered rounds with no early stopping.

The registered budget was 1,920 logical call identities for search, 360 for validation, and 320 for the hidden final, for 2,600 logical call identities total. Registered retries are counted separately as model attempts.

## Eight-round search

| Round | Best exact | Candidate mean | Children accepted | Survivor decision systems |
|---:|---:|---:|---:|---|
| 1 | 12/24 (50.0%) | 9.67/24 (40.3%) | 2/6 | Vote 10P x1, Judge 9P+1J x1, Gated 7P+2C+1J x1, Dual 8P+2J x1, Deliberative 6P+2C+2J x2 |
| 2 | 12/24 (50.0%) | 9.58/24 (39.9%) | 0/6 | Vote 10P x1, Judge 9P+1J x1, Gated 7P+2C+1J x1, Dual 8P+2J x1, Deliberative 6P+2C+2J x2 |
| 3 | 16/24 (66.7%) | 12.25/24 (51.0%) | 3/6 | Judge 9P+1J x1, Gated 7P+2C+1J x1, Dual 8P+2J x2, Deliberative 6P+2C+2J x2 |
| 4 | 11/24 (45.8%) | 8.25/24 (34.4%) | 3/6 | Dual 8P+2J x3, Deliberative 6P+2C+2J x3 |
| 5 | 9/24 (37.5%) | 7.58/24 (31.6%) | 3/6 | Dual 8P+2J x3, Deliberative 6P+2C+2J x3 |
| 6 | 13/24 (54.2%) | 11.33/24 (47.2%) | 1/6 | Dual 8P+2J x3, Deliberative 6P+2C+2J x3 |
| 7 | 14/24 (58.3%) | 12.42/24 (51.7%) | 3/6 | Dual 8P+2J x3, Verified 7P+2V+1J x1, Deliberative 6P+2C+2J x2 |
| 8 | 15/24 (62.5%) | 12.67/24 (52.8%) | 3/6 | Dual 8P+2J x3, Verified 7P+2V+1J x1, Deliberative 6P+2C+2J x2 |

Each round used a different balanced 24-case sample. The trajectory shows the observed search process, not repeated measurement on one fixed benchmark. Validation alone selected the champion.

Across all rounds, 18 of 48 child challenges replaced their parents.

## Validation selection

Validation selected `G-A20DBD76963B` with 33/72 exact (45.8%). Its decision system was `verified_7p2v1j` with judge policy `minority_aware`.

The frozen best initial founder was `G-0025CFC9EF2E`, using `vote_10p`.

## Hidden final

All four methods used the same ten-call budget on the same 96 hidden cases.

| Method | Exact | 95% interval | Proposer plurality | Overrides | Useful | Harmful | Calls | Tokens in/out | Latency | Malformed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Generalist Vote10 | 41/96 (42.7%) | 34.4% to 52.1% | 41/96 (42.7%) | 0 | 0 | 0 | 80 | 957,370/235,873 | 4779.5s | 0 |
| Diversified Vote10 | 37/96 (38.5%) | 29.2% to 47.9% | 37/96 (38.5%) | 0 | 0 | 0 | 80 | 957,754/230,173 | 4711.1s | 0 |
| Best initial founder | 43/96 (44.8%) | 35.4% to 54.2% | 43/96 (44.8%) | 0 | 0 | 0 | 80 | 958,330/234,870 | 4816.8s | 0 |
| Evolved champion | 41/96 (42.7%) | 33.3% to 52.1% | 38/96 (39.6%) | 11 | 3 | 0 | 80 | 1,089,820/203,525 | 4420.0s | 0 |

## Paired comparisons

| Contrast | Difference | 95% interval | Only-left / only-right | McNemar p | Conclusion |
|---|---:|---:|---:|---:|---|
| evolved_champion minus diversified_vote10 | +4.2 pp | -2.1 pp to +10.4 pp | 7 / 3 | 0.3438 | superiority not established |
| evolved_champion minus best_initial_founder | -2.1 pp | -9.4 pp to +4.2 pp | 5 / 7 | 0.7744 | superiority not established |
| evolved_champion minus generalist_vote10 | +0.0 pp | -6.2 pp to +6.2 pp | 5 / 5 | 1.0000 | superiority not established |

## Operational record

The ledger contains 2,600 logical call identities and 2,604 actual model attempts. It records 4 retry attempts across 4 jobs, 4 malformed attempts, 0 infrastructure-failure attempts, 0 schema-invalid exhausted jobs, and 0 protocol-violation jobs. Across all attempts, the runner recorded 34,692,166 input tokens, 6,849,421 output tokens, and 145422.1 seconds of summed call latency.

## Artifact note

Generated score summaries retain an obsolete four-part convenience field from Experiment 03. The authoritative five-part protocol_fitness_key, genome_scores, freezes, and selection receipts are internally consistent and drove every selection, so this label defect does not change results.

## Interpretation

The evolved champion differed from diversified Vote10 by +4.2 pp, but the paired 95% interval [-2.1 pp, +10.4 pp] included zero, so superiority was not established.

The evolutionary trajectory is evidence that the controller explored and retained different decision systems. It is not, by itself, evidence that evolution generalized. The hidden paired comparison is the relevant test.

This is one Luna Light condition, one synthetic sequence grammar, six bounded decision systems, and one deterministic evolutionary schedule. It does not establish a universal orchestration rule.

## Charts

- `../../images/final-exact-accuracy.svg`
- `../../images/eight-round-trajectory.svg`
- `../../images/decision-system-evolution.svg`
