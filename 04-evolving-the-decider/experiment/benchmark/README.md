# RuleWeave-5 decider benchmark

This is the frozen Experiment 04 RuleWeave-5 benchmark. It reuses Experiment
03's generator and recognizer through a thin import adapter while changing the
seed, cases, split sizes, and Experiment 04 block schema.

## Layout

- `public/search_cases.jsonl` and `search_B01.json` through `search_B16.json`:
  192 search cases, two fresh blocks for each of eight evolutionary rounds
- `public/validation_cases.jsonl` and `validation_B01.json` through
  `validation_B06.json`: 72 champion-selection cases
- `public/final_cases.jsonl` and `final_B01.json` through `final_B08.json`:
  96 untouched comparison cases
- `hidden/*_answers.jsonl`: exact programs and next-five answers
- `hidden/search_R01_answers.jsonl` through `search_R08_answers.jsonl`:
  round-scoped answer-release units matching consecutive search block pairs
- `hidden/recognizer_audit.json`: ambiguity, bounds, program-hash, and target-hash audit
- `hidden/generation_receipt.json`: seed and generator provenance
- `manifest.json`: balance invariants and SHA-256 checksums
- `overlap_with_experiments_02_03.json`: separately generated exact-overlap audit

Never provide `hidden/`, the generator seed, or answers to subject agents. Each
model call receives one complete 12-case public block. Search answers are opened
only after all 240 calls for that round are terminal; validation and final
answers follow the release gates registered in `PROTOCOL.md`.

Every block has four hard, four very-hard, and four stress cases. Every pair of
consecutive blocks covers all 24 family-tier cells exactly once. Search,
validation, and final contain respectively 8, 3, and 4 cases per cell.
