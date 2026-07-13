---
name: 03-evolving-light-swarms
description: Design, run, and audit lean evolutionary searches over fixed-budget AI-agent orchestration policies. Use when testing whether symbolic mutation and crossover can improve a swarm, comparing evolved policies with equal-call voting and hand-designed baselines, or separating training gains from validation and hidden-test generalization.
---

# Evolving Light Swarms

## Keep the genome symbolic

Freeze model capability and evolve only orchestration.

Represent each policy with a small grammar:

- one legal call topology;
- frozen role or reasoning-lens identifiers;
- one terminal decision policy;
- deterministic lineage and a canonical genome hash.

Do not let models rewrite prompts, invent tools, change call budgets, or mutate evaluation rules. Use a standard-library program for selection, mutation, crossover, duplicate rejection, and lineage recording.

## Separate search from proof

Create three independently generated splits before the first call:

1. Use training cases for evolutionary fitness.
2. Send only a frozen shortlist to fresh validation cases.
3. Freeze one champion before opening an untouched final answer key.

Hash the benchmark, hidden answers, genome catalog, prompts, schemas, runner, scorer, PRNG seed, retry rules, call budgets, and primary comparison.

Expect search optimism when many genomes reuse a small training set. Prefer several independent training blocks or resampled fitness across frozen generation seeds. Make validation large enough to distinguish finalists, and reserve the largest split for the final comparison.

Define the accounting unit explicitly. If one model call answers a complete case block, compute cost as `policies x blocks x calls per policy-block`, not `policies x cases x calls`. Keep cases as the statistical units even when calls process them in batches.

Size validation and final splits around the smallest improvement worth claiming. Simulate or calculate the paired uncertainty expected under plausible discordant-case rates before collection. If the available budget cannot resolve that margin, register the study as exploratory instead of shrinking the hidden set until a noisy point estimate looks decisive.

## Preserve a fair baseline

Compare every evolved final policy with a deterministic equal-call independent vote. Also retain the best unevolved founder and one fixed hand-designed workflow.

Define independent voting completely: use fresh isolated calls with no shared candidate packet, vote over exact answer tuples, and freeze the tie-break order before collection. A useful deterministic order is vote count, then mean confidence among voters for that tuple, then canonical lexicographic tuple order.

Hold constant:

- model and reasoning setting;
- cases and visible information;
- calls per block;
- output schema;
- tool restrictions;
- timeout and retry policy.

Treat extra search calls as development cost, not deployment calls. Report both.

## Run in dependency-safe waves

Launch independent roles concurrently. Wait for their exact prerequisites before launching critics, verifiers, revisers, or judges. Increasing process concurrency may reduce wall time, but it must not change prompts, identities, genomes, or scores.

Use fresh isolated sessions. Disable tools, code, Python, browsing, files, and inter-agent communication for subject workers. Preserve exact rendered prompts and model outputs.

Retry only under a frozen rule:

- retry infrastructure failures with the identical request;
- allow at most the predefined schema-invalid retry;
- never rerun an answer because it is mathematically wrong;
- preserve every attempt and retry relationship.

## Select without moving the target

Rank training policies by a frozen lexicographic fitness, such as:

1. exact full-case accuracy;
2. fewer harmful overrides of a correct proposer plurality;
3. correct individual terms;
4. format-valid cases;
5. canonical genome hash.

Stop after the frozen number of generations even if another generation appears tempting. Choose finalists from the complete evaluated archive, not only the last population. Freeze the validation winner once.

## Score paired final cases

Require the entire ordered continuation to match exactly. Treat cases, not calls, as the statistical units.

Report:

- exact accuracy and per-term accuracy;
- paired champion-minus-vote difference;
- deterministic paired bootstrap intervals;
- exact McNemar test and discordant counts;
- useful and harmful judge overrides;
- calls, retries, malformed outputs, tokens, and latency;
- post-hoc oracle coverage only as an unattainable diagnostic ceiling.

Do not call a higher point estimate a win when paired uncertainty is inconclusive. Do not claim practical equivalence unless a predefined equivalence interval is contained inside the margin.

## Audit the release

Verify planned identities, split coverage, equal call budgets, lineage, freeze hashes, closure, retries, deterministic rescoring, chart regeneration, and absence of local paths or ephemeral thread identifiers.

Publish exact prompts, genomes, public and hidden benchmark data, raw last messages, attempt ledgers, scoring outputs, limitations, and deterministic charts. Exclude incidental local CLI diagnostics when they contain machine paths or ephemeral session identifiers, and state that exclusion clearly.

The complete reference run is in [`experiment/`](experiment/README.md): 400 registered calls plus the 40-call Amendment 01 correction. Start with [`experiment/REPORT.md`](experiment/REPORT.md), then reuse its standard-library scripts instead of rebuilding the harness.
