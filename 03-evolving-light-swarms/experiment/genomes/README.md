# Symbolic genome artifacts

Experiment 03 evolves small symbolic policies. A genome has only three gene
classes:

- one frozen 10-call topology ID;
- nine universal worker lens IDs, one for each worker slot;
- one final judge policy ID.

The catalog in `GENOME_CATALOG.json` is the source of truth. Prompt prose stays
in `../prompts/LENSES.json` and is never rewritten by evolution.

## Controller commands

```text
python3 ../scripts/evolve.py init --output generation-00.json

python3 ../scripts/evolve.py next-generation \
  --population generation-00.json \
  --scores generation-00-summary.json \
  --output generation-01.json

python3 ../scripts/evolve.py next-generation \
  --population generation-01.json \
  --scores generation-01-summary.json \
  --output generation-02.json

python3 ../scripts/evolve.py select-validation \
  --population generation-02.json \
  --scores generation-02-summary.json \
  --output validation-selection.json

python3 ../scripts/evolve.py freeze-champion \
  --selection validation-selection.json \
  --scores validation-summary.json \
  --output champion-freeze.json
```

`score.py` summary JSON is accepted directly. A compact score file with a
`scores` array is also accepted when each row contains `genome_id`,
`exact_cases`, `harmful_overrides`, `term_correct`, `format_valid`, and
`case_count`, `calls`, and `completed_calls`. Compact files must declare
`schema_version` as `experiment-03-compact-score-v1`, the correct `phase`, the
frozen split's `answers_sha256`, and the scored `predictions_sha256`.

Every controller artifact has a canonical SHA-256 hash. Every child records
its parents and either its one changed locus or its crossover source map.
The controller fixes the PRNG seed, binds scores to the pre-generated split
hashes and planned call identities, and uses the lexicographically larger
genome hash as the last deterministic fitness tie-break. The validation
selection carries the complete 18-genome scored archive so its top three and
best founder can be independently reconstructed before champion freeze.
