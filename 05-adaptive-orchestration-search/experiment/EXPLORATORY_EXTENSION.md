# Exploratory extension

Status: 80%-or-higher target reached on fresh gate 03; unrelated transfer confirmation not run

## Why the experiment changed

The original search used 1,722 logical Luna Light calls. Validation used 990.
The planned hidden final required another 1,440. That would spend 2,430 calls
on confirmation, 41% more than the complete discovery search.

At the user's direction, hidden-final replicate 1 was stopped after 684 of 720
valid jobs. Replicate 2 never started. The hidden answer key remains sealed and
the partial run will never be scored or used for selection.

The original protocol and artifacts remain unchanged. This extension continues
inside Experiment 05 as exploratory research. It is not confirmatory evidence.

## Objective

The initial objective was to search aggressively for a Luna Light system near
60% to 70% exact accuracy before paying for another large validation. The user
later raised the objective to at least 80% on a fresh preregistered gate.

This objective was reached on July 14, 2026. The frozen 11-prompt plurality
scored 16 of 24, or 66.7%, on untouched exploratory cases. The result record is
`registrations/exploration-gate-01-result.json`.

The higher objective was reached later that day. A visible-holdout system with
public-suffix-length-weighted selection scored 22 of 24, or 91.7%, on fresh
gate 03. Its architecture was frozen before those cases were generated, and
their answers remained sealed until all 268 jobs were terminal. The result is
`registrations/fresh-80-gate-03-result.json`.

## Call-efficient research loop

1. Build one shared answer bank from paid-for search and validation calls.
2. Measure oracle coverage: how often any saved hypothesis is exactly correct.
3. If oracle coverage is low, spend new calls on hypothesis generation.
4. If oracle coverage is high, evolve the selector without new model calls.
5. Reuse every shared solver answer across all selector candidates.
6. Race selectors on small rotating panels, dropping weak systems early.
7. Use stratified cross-validation across the 144 known research cases.
8. Add new Luna calls only for unresolved cases or missing reasoning lenses.

New Luna batches may run at up to 60 calls in parallel. They remain requested
GPT-5.6 Luna with provider effort `low`, publicly called Light reasoning, with
tools and external communication disabled.

## Minimal fresh gate

A candidate becomes eligible for a fresh gate only if it has:

- at least 58% stratified cross-validated exact accuracy;
- at least a 5 percentage-point lead over the shared control;
- gains that are not confined to one family or tier; and
- enough oracle coverage to make the target plausible.

The first fresh gate contains 24 balanced unseen cases. One candidate and one
control use at most 60 logical calls in total. Continue only if the candidate:

- solves at least 14 of 24 cases;
- beats the control by at least two cases; and
- does not collapse across mechanism families.

A second disjoint 24-case gate may follow under the same rule. These gates are
research checks, not a publishable final.

### Gate actually run

The extension remained exploratory and the user prioritized absolute accuracy
and call efficiency over another control-heavy comparison. The registered gate
therefore ran one frozen candidate on 24 fresh cases for 44 logical jobs. It did
not run a same-panel control, so it supports an absolute 66.7% fresh score but
does not establish a paired improvement over the earlier control.

The candidate was frozen from prompt-frequency stability across the top 100
balanced depth-cycle subsets, not from the single highest fitted subset. Its
registered selector scored 16/24. A post-hoc four-prompt subset scored 18/24,
but that number is diagnostic only.

Accuracy was heterogeneous. The two complementary 12-case panels scored 11/12
and 5/12. The full 24 cases still contained all eight mechanism families and
all three difficulty tiers exactly once per family-tier cell, but the system
failed all modular and all growing-block cases. This limits any claim of broad
mechanism robustness.

The six-case depth cycle is also not a controlled packet-size experiment. It
changed prompt population and cases along with packet size. A causal packaging
comparison would need identical prompts and fresh cases under both layouts.

## Continuation to the 80% objective

The first 80%-target gate tested a deep-override design and scored 13/24. The
second replaced subjective judging with visible self-verification and scored
19/24, missing the target by one case.

Gate 02 revealed a simple evidence error. The selector counted a candidate
that reconstructed one removed public term the same as a candidate that
reconstructed three. Weighting each verified vote by the number of public terms
it reconstructed changed the open Gate 02 replay from 19/24 to 21/24 and left
the prior 24-case development panel unchanged. Because this was discovered
after Gate 02 was opened, it remained development evidence.

The weighted rule was then frozen before generating fresh Gate 03. It scored
22/24, with six useful overrides and zero harmful overrides. The complete
progression is recorded in `results/fresh-gate-progress.csv` and
`results/fresh-gate-progress.svg`.

## Final-validation boundary

No additional hidden final or unrelated transfer benchmark will run
automatically. The requested 80%-or-higher sequence objective is complete.
Further work should begin only as a separately approved replication or transfer
experiment.
