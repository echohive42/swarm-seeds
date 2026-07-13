# Symbolic genome and selection artifacts

Experiment 04 evolves a bounded decision policy for ten Light-reasoning calls. Prompt prose never enters the genome.

## Genome grammar

Every canonical genome has three gene classes:

```json
{
  "decision_system_id": "verified_7p2v1j",
  "worker_lens_ids": ["generalist", "recurrences", "... 8 more ..."],
  "judge_policy_id": "minority_aware"
}
```

- `decision_system_id` chooses one of six fixed ten-call systems.
- `worker_lens_ids` assigns one frozen Experiment 03 lens to each of ten call positions.
- `judge_policy_id` chooses one of four fixed policies used by judge roles.

`GENOME_CATALOG.json` is the source of truth for the legal symbols, six founders, fixed evolution seed, eight-round schedule, and call budgets. The matching prompt text lives in `../prompts/LENSES.json` and is never mutated.

The six decision systems are:

| ID | Calls | Final rule |
|---|---|---|
| `vote_10p` | 10 proposers | Plurality |
| `judge_9p1j` | 9 proposers, 1 judge | Judge answer |
| `gated_7p2c1j` | 7 proposers, 2 critics, 1 judge | Critics and judge must agree to override |
| `dual_8p2j` | 8 proposers, 2 judges | Judges must agree to override |
| `verified_7p2v1j` | 7 proposers, 2 verifiers, 1 judge | Verifiers and judge must agree to override |
| `deliberative_6p2c2j` | 6 proposers, 2 critics, 2 judges | Judges and at least one critic must agree to override |

## Artifact lifecycle

| Files | Contents |
|---|---|
| `round-00-parents.json` | Six founders, one for each legal decision system |
| `round-NN-candidates.json` | Six parents, six unique children, and six explicit challenge pairs |
| `round-NN-survivors.json` | Six paired winners and complete comparison receipts |
| `best-founder-freeze.json` | Best original founder using round-1 evidence only |
| `champion-freeze.json` | All six validation fitness records and the frozen validation winner |
| `final-champion.json` | One-genome packet for hidden-final execution |
| `final-founder.json` | One-genome packet for the founder replication |

Every genome ID is the first 12 hexadecimal characters of the SHA-256 of its canonical genes, prefixed by `G-`. Lineage records the round, operation, designated parent slot, parent IDs, and either the changed mutation locus or the crossover source map.

All six current parents remain in fixed slots `S01` through `S06`. In each round, the controller creates four one-gene mutations and two crossovers. Every child challenges its designated parent on the same fresh 24 cases. Only a strictly better child replaces the parent; an exact tie keeps the parent.

## Controller workflow

Run from the experiment directory. The checked-in artifacts already preserve the completed run, so these commands are documentation for the deterministic lifecycle.

```bash
python3 -B scripts/evolve.py init \
  --output genomes/round-00-parents.json

python3 -B scripts/evolve.py make-round \
  --round 1 \
  --parents genomes/round-00-parents.json \
  --output genomes/round-01-candidates.json

python3 -B scripts/evolve.py select-round \
  --round 1 \
  --candidates genomes/round-01-candidates.json \
  --summary results/search/round-01/summary.json \
  --case-matrix results/search/round-01/case_matrix.csv \
  --answers benchmark/hidden/search_R01_answers.jsonl \
  --predictions runs/search/round-01/predictions.json \
  --best-founder-output genomes/best-founder-freeze.json \
  --output genomes/round-01-survivors.json
```

Repeat `make-round` and `select-round` through round 8, using the prior survivor file as the next parent file. Do not stop early.

After all eight rounds:

```bash
python3 -B scripts/evolve.py select-validation \
  --population genomes/round-08-survivors.json \
  --summary results/validation/summary.json \
  --case-matrix results/validation/case_matrix.csv \
  --answers benchmark/hidden/validation_answers.jsonl \
  --predictions runs/validation/predictions.json \
  --best-founder genomes/best-founder-freeze.json \
  --output genomes/champion-freeze.json
```

Use `python3 -B scripts/evolve.py self-test` to exercise all eight schedules, canonical uniqueness, paired replacement, tie behavior, founder freeze, validation selection, and score-hash rejection without model calls.

## Authoritative fitness

Experiment 04 selection uses this five-part lexicographic key:

```text
[exact cases, weakest-block exact, -harmful overrides, correct terms, format-valid cases]
```

Use `protocol_fitness_key`, case matrices, comparison receipts, and the freezes to reconstruct selection.

Do not use the inherited `methods.*.fitness_key_without_hash` field in generated score summaries. That convenience field retains the older four-part order and omits weakest-block exact accuracy. `genome_scores`, the authoritative protocol keys, and every actual selection use the correct five-part order. The frozen summary files remain unchanged for audit integrity.

## Completed search

All eight rounds ran. Eighteen of 48 children replaced their designated parents. The final population contained:

- three `dual_8p2j` genomes;
- two `deliberative_6p2c2j` genomes;
- one `verified_7p2v1j` genome.

The verified founder had been eliminated earlier. Verification was rediscovered in round 7 when `G-A20DBD76963B` mutated only the decision-system locus of dual-judge parent `G-3373FE74E208`.

Validation selected `G-A20DBD76963B` at 33/72 exact, one case ahead of three survivors at 32/72. Its frozen genes are:

```text
system:  verified_7p2v1j
lenses: generalist, recurrences, recurrences, modular, simplicity,
        generalist, generalist, generalist, audit, generalist
policy:  minority_aware
```

The best initial founder was `G-0025CFC9EF2E`, a `vote_10p` genome with ten generalist lenses. It is symbolically identical to the separately executed Generalist Vote10 baseline. Their final scores, 43/96 and 41/96, are independent replication outcomes, not evidence for different architectures.
