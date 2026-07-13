---
name: 04-evolving-the-decider
description: Design, run, and audit fixed-budget symbolic evolution of multi-agent decision policies. Use when Codex needs to test voting, judging, criticism, verification, gated overrides, or deliberation under equal model-call budgets while separating adaptive search, validation selection, hidden-final evidence, and stochastic run variation.
---

# Evolve the Decider

## Freeze a bounded question

Hold model capability, reasoning effort, task, visible information, output schema, and calls per block constant. Evolve only symbolic decision policy.

Represent each genome with:

- one legal decision-system identifier;
- one frozen lens identifier for every call slot;
- one frozen judge-policy identifier;
- deterministic lineage and a canonical genome hash.

Keep prompt prose, tools, memory, call count, mutation code, aggregation, and scoring outside the mutable genome. Use deterministic controller code, not model-generated code, for mutation, crossover, duplicate rejection, pairing, and selection.

## Make the decision systems explicit

Define each system as a fixed call graph and deterministic final rule. Include a simple independent vote and only a small number of inspectable alternatives, such as:

- one terminal judge;
- criticism plus a strict override gate;
- two independent judges with agreement fallback;
- verification plus a strict override gate;
- two judges plus critic support.

Specify how invalid intermediate answers abstain. Freeze plurality ties by vote count, then mean reported confidence, then canonical tuple order. Never let a downstream role average incompatible answers or invent an unregistered compromise.

## Generate all evidence before collection

Create search, validation, and hidden-final cases before the first model call. Hash public inputs, hidden programs, targets, answer files, prompt catalogs, schemas, controller code, runner code, scorer code, retry rules, and the evolution seed.

Use round-scoped search answer files. Keep future search, validation, and final answers closed. Verify terminal call identities before opening only the answer file needed for the current selection step.

Audit internal duplicates and overlap with prior benchmarks across visible inputs, hidden programs, and exact targets.

## Run paired fresh-block evolution

Maintain fixed parent slots for a fixed number of rounds. Do not stop early.

For every round:

1. Create the registered number of one-gene mutations and crossovers.
2. Reject any genome already seen.
3. Give all parents and children the same fresh blocks.
4. Wait until every planned call identity is terminal.
5. Open only that round's answer file.
6. Compare each child only with its designated parent.
7. Replace the parent only when the child is strictly better.
8. Keep the parent on an exact fitness tie.

Rank paired fitness lexicographically. Prefer total exact cases, then exact cases on the weakest block, fewer harmful overrides of a correct proposal plurality, more correct terms, and more format-valid cases.

Treat `protocol_fitness_key` and selection receipts as authoritative. Do not reconstruct selection from inherited or convenience score fields that omit a registered component.

## Separate search from confirmation

Freeze the best initial founder using only the registered early search evidence. After the final search round, evaluate all survivors on fresh validation cases and freeze one champion before opening final answers.

Use the untouched final set for four equal-call methods:

- the validation-selected champion;
- the frozen best initial founder;
- an independent generalist vote;
- an independent diversified vote.

If two methods have identical symbolic configurations but fresh executions, label them as independent replications. Compare their prompt and response hashes. Treat score differences as run variation, not architecture effects.

## Inspect the decision mechanism

Report proposal-plurality accuracy beside final accuracy. Classify every override as useful, harmful, or neutral. For a gated system, also compute the judge-only counterfactual and the changes blocked by the gate.

Do not credit a gate merely because the final system is accurate. Show whether the gate added net exact cases, prevented net harm, or only changed neutral answers.

## Preserve operational truth

Count registered logical call identities separately from actual attempts. Preserve every malformed response and retry relationship. Retry only under the frozen rules with the identical request. Never retry because an answer is mathematically wrong.

Report calls, actual attempts, malformed attempts, tokens, latency, and exhausted failures. State that equal calls need not mean equal tokens when later roles receive evidence packets.

## Score paired final cases

Treat cases, not calls, as statistical units. Require the complete ordered continuation to match exactly.

Report:

- exact and per-term accuracy;
- paired point differences;
- block-stratified bootstrap intervals;
- exact McNemar tests;
- method-only wins, both-correct, and both-wrong counts;
- proposal plurality and override value;
- calls, attempts, tokens, latency, and malformed outputs.

Do not claim superiority when the paired interval includes zero. Do not call identical point estimates equivalent without a registered equivalence margin.

## Audit and release

Verify frozen hashes, terminal call closure, per-block budgets, score-to-prediction and score-to-answer bindings, genome lineage, pairwise replacement, validation selection, deterministic rescoring, and privacy.

Publish the protocol, benchmark, overlap audit, genome catalog, every round population, prompts, predictions, ledgers, score matrices, comparisons, champion freeze, analysis, limitations, and known artifact caveats. Do not silently rewrite frozen result artifacts after finding a harmless legacy field or presentation inconsistency. Document which field is authoritative and why the result is unchanged.

Use the complete reference run in [`experiment/`](experiment/README.md). Read [`experiment/REPORT.md`](experiment/REPORT.md) before reusing the standard-library harness.
