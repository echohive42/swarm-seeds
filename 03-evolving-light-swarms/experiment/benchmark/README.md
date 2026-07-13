# RuleWeave-5 evolutionary benchmark

This benchmark contains fresh procedurally generated integer-sequence tasks for Experiment 03. Each public case provides 12 to 14 terms and asks for the next five. Every value is a decimal string, every rule is deterministic, and all reference arithmetic uses Python integers.

## Layout

- `public/training_block.json`: 12 cases used during evolution
- `public/validation_B01.json` and `validation_B02.json`: 24 fresh policy-selection cases
- `public/final_B01.json` through `final_B04.json`: 48 untouched comparison cases
- `hidden/*_answers.jsonl`: programs and exact next-five answers
- `hidden/recognizer_audit.json`: cross-family ambiguity and bounds audit
- `manifest.json`: design invariants and SHA-256 checksums
- `overlap_with_experiment_02.json`: exact cross-experiment overlap audit

Do not provide `hidden/`, the generator seed, or answers to subject agents. Each model call receives one complete 12-case public block. All workers are GPT-5.6 Luna at Light reasoning and may not use tools, code, Python, web search, files, or other agents.

Validation has one case in every family and tier cell. The final set has exactly two cases in every family and tier cell.

Experiment 03 keeps Experiment 02's 12-case block format but does not reuse its cases. The standard-library overlap audit compares all public prefixes, hidden generator programs, and next-five targets. It found zero overlap between Experiment 02's 72 cases and Experiment 03's 84 cases, and zero duplicates within Experiment 03.
