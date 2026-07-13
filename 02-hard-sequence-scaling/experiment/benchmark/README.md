# RuleWeave-5 benchmark

RuleWeave-5 contains procedurally generated integer-sequence tasks. Each public case provides 12 to 14 terms and asks for the next five. Every value is a decimal string, every rule is deterministic, and all reference arithmetic uses Python integers.

## Layout

- `public/development_cases.jsonl`: 12 development cases
- `public/calibration_cases.jsonl`: 12 calibration cases
- `public/final_cases.jsonl`: 48 untouched final cases
- `public/development_block.json`: the development call block
- `public/calibration_block.json`: the calibration call block
- `public/final_B01.json` through `public/final_B04.json`: four final call blocks
- `public/final_blocks.json`: answer-free final block manifest
- `hidden/*_answers.jsonl`: programs and exact next-five answers
- `hidden/recognizer_audit.json`: cross-family ambiguity and bounds audit
- `manifest.json`: design invariants and SHA-256 checksums

Do not provide `hidden/`, the generator seed, or generated answers to subject agents during the run. Each model call receives one complete 12-case block assembled from the public cases. Subjects may not use tools, code, Python, web search, or files.

`manifest.json` uses benchmark-manifest schema `1.0`. Experimental prompts, task blocks, packets, and model outputs use the separate experiment schema `2.0`.

The final set has exactly two cases in every family and tier cell. Each family occurs six times, each tier occurs sixteen times, and every consecutive 12-case block contains four cases from each tier.
