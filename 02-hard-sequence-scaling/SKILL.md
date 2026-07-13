---
name: 02-hard-sequence-scaling
description: Design and run lean, reproducible agent-scaling experiments that compare reasoning depth, independent voting, and structured collaboration on objectively scored tasks. Use when testing Light versus Medium reasoning, equal-call routing strategies, or whether a larger agent group improves exact accuracy enough to justify its cost.
---

# Hard Sequence Scaling

## Keep the experiment lean

Use one benchmark generator, one standard-library Python runner, one append-only attempt log, one scorer, and one analysis script. Add machinery only when it protects blinding, repeatability, or evidence.

## Define the comparison

1. Choose one model and two reasoning settings.
2. Choose an objectively scored benchmark with development, calibration, and hidden final splits.
3. Compare a direct call, independent votes, and structured teams at equal call budgets.
4. Treat benchmark cases as the statistical units, not repeated calls on the same case.
5. Name the public conditions `Light reasoning` and `Medium reasoning`.

Use independent outputs for deterministic vote arms. Use fresh calls for structured arms. Do not mix outputs between reasoning settings.

## Freeze before final collection

Freeze and hash:

- benchmark inputs and hidden answers;
- prompts, roles, schemas, and routing;
- aggregation and tie-breaking rules;
- retry and failure rules;
- primary and secondary comparisons;
- bootstrap seed and multiplicity correction.

Preflight the largest downstream packet before freezing. Set one packet limit that admits every planned role.

For future runs, freeze one automatic retry for a schema-invalid completed response. Reuse the identical prompt, preserve both attempts, and apply the predefined scoring rule. Keep infrastructure retries separate. Never silently repair an answer.

## Run the arms

Use fresh model sessions and explicit model and reasoning settings. Disable tools for experimental subjects. Run only independent calls in parallel. Start downstream roles only after their exact prerequisites close.

Record every attempt before launching a replacement. Preserve prompt identity, call identity, role, reasoning setting, timestamps, exit status, raw response hash, parsed response, token usage, and retry lineage.

## Score without moving the goalposts

Close collection before opening hidden answers. Then:

1. Verify the benchmark and closure marker.
2. Score exact full answers and per-term accuracy.
3. Compare methods on paired cases.
4. Use deterministic case-resampling intervals.
5. Apply the frozen multiple-testing correction.
6. Report deployment calls and measured token use.
7. Preserve malformed outputs and protocol amendments.

Separate the conclusions:

- reasoning lift: Medium minus Light;
- scale lift: more independent calls versus fewer calls;
- routing lift: structured collaboration versus an equal-call vote.

Do not call a higher point estimate a win when the paired uncertainty is inconclusive.

## Audit and release

Run a public-release audit for frozen hashes, complete call closure, deterministic rescoring, analysis consistency, private identifiers, and local paths. Publish the actual prompts, benchmark, attempt log, scoring, limitations, and charts beside this skill.

The full reference implementation and its 400-call GPT-5.6 Luna run are in [`experiment/`](experiment/README.md). Start with [`experiment/REPORT.md`](experiment/REPORT.md), then reuse the standard-library scripts rather than rebuilding the harness.
