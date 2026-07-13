# Experiment 03 protocol: Evolving Light Swarms

## Question

Can a small evolutionary search discover a 10-call GPT-5.6 Luna Light orchestration policy that outperforms a fixed 10-agent vote on fresh RuleWeave-5 sequence problems?

The workers never become stronger. Every experimental call uses GPT-5.6 Luna with the provider setting `low`, reported publicly as Light reasoning. The only thing allowed to improve is how those workers are organized.

## Policy genome

A genome contains symbols, not freely rewritten prompt prose:

- one 10-call topology;
- frozen role-lens identifiers for proposers and reviewers;
- one final decision policy;
- a deterministic lineage and genome hash.

The four founding species are:

1. Consensus: nine proposals followed by one final selector.
2. Falsification: seven proposals, two critics, and one final selector.
3. Specialization: seven mechanism-focused proposals, two verifiers, and one final selector.
4. Paired revision: five proposals, two revisers, two verifiers, and one final selector.

Every legal genome uses exactly 10 planned model calls for each 12-case block. Packet format, schemas, tool restrictions, model, reasoning level, timeout, retry rules, and prompt components remain fixed.

## Evolution

- Population: 6 distinct genomes.
- Generations: 3.
- Generation 0: six diverse frozen founders.
- Selection: best two genomes seen so far.
- Reproduction: four deterministic one-gene mutations and two crossovers.
- Duplicate genomes are rejected.
- Stop after Generation 2 regardless of the observed score.

Training fitness is ordered by:

1. exact next-five case accuracy;
2. fewer harmful overrides of a correct proposer plurality;
3. total correct answer terms;
4. format-valid cases;
5. canonical genome hash.

No model writes mutations. A standard-library Python program performs selection, crossover, and mutation with one frozen PRNG seed.

## Data

RuleWeave-5 uses eight registered mathematical mechanism families and three difficulty tiers. Every case shows 12 to 14 terms and asks for the next five terms exactly.

- Training: 12 cases used for all three generations.
- Validation: 24 fresh cases, one per family and tier cell.
- Final: 48 untouched cases, two per family and tier cell.

All three splits are generated and hashed before the first search call. Validation answers may be opened only after all three finalist policies finish both validation blocks. Final answers may be opened only after every final method finishes all four final blocks.

## Call budget

| Phase | Calculation | Planned calls |
|---|---:|---:|
| Evolution | 6 genomes x 3 generations x 10 calls | 180 |
| Validation | 3 finalists x 2 blocks x 10 calls | 60 |
| Final | 4 methods x 4 blocks x 10 calls | 160 |
| Total | | 400 |

Retries remain attached to the original call identity and do not create a new planned call.

## Final methods

1. Evolved champion: chosen once from fresh validation.
2. Best founder: the highest-scoring Generation 0 genome.
3. Vote10: ten independent generalist solvers combined by deterministic plurality.
4. Fixed Swarm10: five proposers, two critics, two verifiers, and one judge.

The primary comparison is the evolved champion against Vote10 at the same 10-call budget. Champion against the best founder measures evolutionary gain. The fixed Swarm10 comparison shows whether evolution adds value beyond a hand-designed workflow.

## Scoring

A case is correct only when all five ordered canonical decimal strings exactly equal the reference answer. Missing or terminal malformed output scores zero. Per-term accuracy is secondary.

For Vote10, exact tuples are ranked by:

1. vote count;
2. mean reported confidence among voters;
3. canonical lexicographic tuple order.

The primary effect is the paired accuracy difference between champion and Vote10. The report includes a paired bootstrap interval, exact McNemar test, both-correct and both-wrong counts, policy-only wins, vote-only wins, calls, tokens, latency, malformed outputs, and retries.

## Failure and retry policy

- Infrastructure failures receive up to two identical fresh-process retries.
- One completed schema-invalid response receives exactly one identical-prompt retry.
- Every attempt is preserved.
- A second schema-invalid response is terminal and scores zero.
- No retry depends on mathematical correctness.
- Up to 50 Codex CLI processes may run concurrently. Concurrency changes wall-clock execution only and does not change prompts, genomes, call identities, or scores.

## Subject isolation

Workers receive only the public task block, their frozen role instructions, and any anonymized prior-stage candidates required by their topology. They receive no answers, family labels, difficulty tiers, parameters, seeds, filesystem access, tools, Python, browsing, or communication with other workers.

## Interpretation boundary

This experiment tests one model, one reasoning level, one benchmark family, and one small evolutionary grammar. A positive result would show that symbolic optimization improved this Light-only system on fresh cases. It would not prove that evolution always improves agent orchestration.
