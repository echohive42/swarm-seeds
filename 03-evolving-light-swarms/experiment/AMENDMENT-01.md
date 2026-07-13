# Amendment 01: restore the registered generalist Vote10 baseline

## What the release audit found

The frozen protocol defines Vote10 as ten independent **generalist** solvers. The original `orchestrate.py vote` implementation instead assigned ten independent solvers a fixed mixture of generalist, differences, recurrences, streams, modular, simplicity, diversifier, and audit lenses.

The original pool was still independent and used the correct ten-call budget, but it was not the generalist baseline named in the protocol. This mismatch was discovered during the final adversarial release review, after the hidden final answers had been opened and scored.

## Correction

The correction ran one additional 40-call baseline over the same four untouched final input blocks:

- ten fresh isolated calls per block;
- the frozen `gpt-5.6-luna` and `low` reasoning request;
- the frozen common prefix and generalist worker lens;
- the frozen schema, tool restrictions, and retry policy;
- deterministic Vote10 aggregation from the frozen scorer.

No hidden answer, score, case family, tier, or prior model output is provided to these calls. The correction has one protocol-determined prompt and introduces no tuned choice.

## Execution-timeout deviation

The registered 400-call runner used a 300-second subprocess ceiling. The correction helper inherited a 600-second default, so all 40 correction calls were launched with a 600-second ceiling rather than the registered 300-second ceiling. The timeout is included in each request identity hash; the release audit verifies the 300-second identities for all registered calls and the 600-second identities for all correction calls.

No correction call timed out, and the longest took 82.308 seconds. Therefore, no correction output depended on the extra execution time. This remains an execution-contract deviation and is part of the post-unblinding interpretation boundary. The calls were not rerun again after discovery because another post-unblinding collection would add no useful evidence.

The original diversified independent pool remains preserved under `runs/final/vote10/` and is reported as a superseded exploratory baseline. The corrected generalist pool is stored under `runs/final/vote10-generalist/` and replaces it in the primary final comparison.

## Interpretation boundary

This is a post-unblinding implementation correction. It restores the baseline that the protocol already specified, but it was collected after the original final scores were known. The chronology must remain visible in every report.

The registered run used 400 calls. The correction adds 40 calls, bringing total recorded experimental execution to 440 calls. Deployment comparisons still use exactly ten calls per block for every method.

## Amended result

The corrected generalist Vote10 solved 18/48 cases. The evolved champion solved 21/48, for a paired difference of +6.25 percentage points. The stratified paired 95% interval was -4.17 to +16.67 points, champion-only and Vote10-only wins were 5 and 2, and exact McNemar p was 0.453125. Superiority was not established.

The original diversified pool solved 21/48 and tied the champion. It remains useful as a sensitivity result about lens allocation, but it is not the protocol-registered baseline.

- Corrected primary score: `results/final/`
- Superseded diversified sensitivity score: `results/final-diversified-vote/`
- Corrected raw pool: `runs/final/vote10-generalist/`
- Original diversified raw pool: `runs/final/vote10/`
