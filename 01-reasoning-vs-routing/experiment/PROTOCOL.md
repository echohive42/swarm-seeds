# Frozen protocol 1.0.0

## Question

For gpt-5.6-luna, does medium reasoning outperform low reasoning, and does a structured collaborative pipeline outperform both the expected direct solver and a same-budget independent ensemble on finite-sequence continuation?

## Experimental arms

For each reasoning level, low and medium:

- **Direct:** ten identical independent calls estimate expected one-call performance. Cost reported per deployed prediction is one call; the ten calls are experimental replications.
- **Independent ensemble:** deterministic aggregation of the same ten direct outputs. Deployment cost is ten calls.
- **Collaboration:** ten calls in four sequential stages: five independent specialized proposers, two parallel critics, two parallel verifiers, and one judge. Deployment cost is ten calls.

The ensemble and collaboration therefore have identical call budgets.

## Isolation

- Every subject is a new, non-forked, projectless thread.
- Every subject is explicitly gpt-5.6-luna with its assigned reasoning level.
- All prompts include the immutable no-tools/no-files/no-other-agents prefix.
- Low outputs are passed only to low critics, verifiers, and judges. Medium outputs are passed only to medium equivalents.
- Subjects never see arm labels, other-arm scores, benchmark answers, filesystem paths, or previous experiment results.
- Templates are byte-identical across reasoning arms. Only the API reasoning setting differs.
- Stage packets use anonymous proposer labels A-E.
- Successful threads are archived immediately after capture. Interrupted attempts are recorded and identically restarted.

## Deterministic ensemble

For each case:

1. Group the ten predicted triples by exact numeric identity.
2. Select the triple with the largest vote count.
3. Break a vote-count tie by the largest sum of voter confidence.
4. Break any remaining tie by lexicographically smallest numeric triple.
5. Ensemble confidence is the mean confidence of voters supporting the selected triple.
6. Use the rule text from the highest-confidence supporting voter, breaking ties by lower replicate number.

## Scoring

Primary outcome: exact-triplet accuracy.

Secondary outcomes:

- individual-term accuracy;
- rule identification score;
- Brier-style confidence calibration, 1 - (confidence - exact)^2;
- format compliance;
- call count;
- per-call duration and parallel wall-clock latency;
- input/output character counts and approximate visible-token counts.

Actual hidden reasoning-token usage is reported only if exposed by thread metadata. Character and visible-token counts are explicitly labeled proxies, not billed-token measurements.

## Development and final split

- Development has four cases and is used only to confirm parsing, stage transfer, archiving, and scoring.
- Development results cannot alter case answers, scoring weights, aggregation, roles, or reasoning settings.
- A schema-only repair requires a documented protocol patch before the final split.
- The twelve-case final split is untouched until development integrity checks pass and the freeze manifest is written.

## Statistical interpretation

Cases are the primary paired units. Report exact rates and paired method differences. Use a case-resampling bootstrap for descriptive 95% intervals. Because the benchmark is small and finite sequences are underdetermined, results apply only to this curated benchmark and configuration.
