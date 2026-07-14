# 05: Adaptive Orchestration Search

![Fresh-gate progression](images/stage-2/fresh-gate-progress.png)

Can a Codex research director discover a substantially better way for GPT-5.6
Luna Light calls to solve difficult mathematical sequences?

## Result

Yes, on this benchmark.

The final frozen system solved **22 of 24 fresh sequences, or 91.7% exact**.
It also predicted **112 of 120 individual continuation terms, or 93.3%**.
The preregistered objective was at least 20 of 24, the first attainable score
at or above 80%.

The selector and orchestration were frozen before the Gate 03 cases were
generated. The answer file stayed sealed until all 268 Luna Light calls were
terminal. Every call returned a valid result, so there were no retries.

This is a real fresh-gate result, but it is still one small sequence benchmark.
It does not mean the system has 91.7% accuracy on arbitrary reasoning tasks.

## The key idea

The breakthrough was to replace weak judge opinions with **visible
self-verification**.

For a difficult sequence, an agent receives a shortened version of the public
prefix. It must predict both:

1. the one to three public terms removed from the end; and
2. the five genuinely unknown continuation terms.

Only candidates that exactly reconstruct their removed public terms survive.
The final selector then gives each candidate one vote unit for every public
term it reconstructed. A candidate that recovered three withheld terms carries
three times the evidence of one that recovered a single term.

The deterministic selection order is:

1. total reconstructed public terms;
2. deepest reconstructed suffix;
3. number of distinct suffix depths;
4. number of distinct generation stages;
5. raw supporting responses;
6. canonical tuple order.

Self-reported confidence is not used. No model sees a benchmark answer, family
label, generator program, or another model's correctness.

## Final orchestration

The system begins with 15 independent prompt lenses over all 24 sequences.
It spends additional calls only where agreement or public reconstruction is
weak.

```text
15-prompt base panel
        |
        | base plurality support <= 5
        v
8 deep visible-holdout solvers, hiding 2 or 3 public terms
        |
        | at most 3 verified survivors
        v
8 recovery solvers, hiding 1 or 2 public terms
        |
        | maximum verified answer support <= 3
        v
8 structural worksheets, hiding 1 public term
        |
        v
holdout-length-weighted deterministic selection
```

Gate 03 used 60 base calls, 88 first-stage calls, 64 recovery calls, and 56
worksheet calls. Total: **268 Luna Light calls**.

## Exact sequence families

Every fresh gate contains one case from each of eight generator families at
each of three difficulty tiers. That gives 8 × 3 = 24 cases.

- **POLY:** a polynomial in the term index, represented with finite-difference
  or binomial-basis coefficients.
- **PDELTA:** the sequence changes by periodic phase-specific differences, and
  each phase's difference can itself vary polynomially across cycles.
- **AFFINE:** `x[n] = a[phase] * x[n-1] + b[phase]`, with phase-dependent
  multipliers and biases.
- **LIN2:** `x[n] = u*x[n-1] + v*x[n-2] + b[phase]`, a second-order recurrence
  with periodic bias.
- **LAGPOLY:** `x[n]` is derived from `x[n-L]` plus a phase-specific polynomial
  step.
- **INTERLEAVE:** two or three independent polynomial or affine streams are
  woven together by position.
- **GROWBLOCK:** consecutive arithmetic blocks grow in length, while block
  starts and within-block steps follow polynomial rules.
- **MODAFFINE:** a phase-dependent affine recurrence evaluated modulo a prime.

Public prefixes contain 12 to 14 integer terms. The task is always to predict
the next five exactly. The benchmark generator also checks that all recognized
programs matching a prefix agree on one next-five tuple.

## Progression

| Gate | Frozen system | Base only | Calls | Status |
|---|---:|---:|---:|---|
| Fresh Gate 01 | 13/24, 54.2% | 14/24, 58.3% | 78 logical, 101 attempts | Missed |
| Fresh Gate 02 | 19/24, 79.2% | 15/24, 62.5% | 340 | Missed by one |
| Gate 02 weighted replay | 21/24, 87.5% | 15/24, 62.5% | No new calls | Post-hoc development only |
| Fresh Gate 03 | **22/24, 91.7%** | 16/24, 66.7% | 268 | **Target reached** |

Gate 02 showed why equal voting was wrong. Two correct continuations had fewer
responses but reconstructed longer public suffixes. Length weighting corrected
both cases and left the earlier 24-case development panel unchanged. Because
that rule was discovered after Gate 02 was opened, its 21/24 replay was not
treated as validation. The rule was frozen first and then tested on newly
generated Gate 03.

On Gate 03, visible self-verification corrected six base errors and introduced
zero harmful overrides. The final system exactly matched its available
candidate oracle at 22/24.

## Honest interpretation

- The requested 80%-or-higher fresh-gate objective was reached.
- The primary result is the preregistered **22/24 Gate 03 score**.
- The adaptive research path and both earlier misses remain part of the record.
- Repeated research and fresh gates mean this is a discovered benchmark system,
  not an untouched estimate of arbitrary Luna Light capability.
- The next scientifically stronger step would be transfer to unrelated hard
  reasoning tasks or a larger final replication. It should be a separate,
  explicitly approved experiment.

## Records

- [Full technical report](experiment/REPORT.md)
- [Reusable skill seed](SKILL.md)
- [Stage 2 charts and illustrations](images/stage-2/)
- [Gate 03 architecture freeze](experiment/registrations/fresh-80-gate-03-generation-registration.json)
- [Gate 03 subject registration](experiment/registrations/fresh-80-gate-03-registration.json)
- [Gate 03 pre-unseal record](experiment/registrations/fresh-80-gate-03-unseal-registration.json)
- [Gate 03 registered result](experiment/registrations/fresh-80-gate-03-result.json)
- [Gate 03 full score](experiment/results/fresh-80-gate-03/score.json)
- [Progress data](experiment/results/fresh-gate-progress.csv)
- [Progress chart](experiment/results/fresh-gate-progress.svg)
- [Original registered protocol](experiment/PROTOCOL.md)
