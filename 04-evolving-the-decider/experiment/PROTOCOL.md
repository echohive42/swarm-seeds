# Experiment 04 protocol: Evolving the Decider

## Question

Can symbolic evolution discover when ten GPT-5.6 Luna Light calls should vote, criticize, verify, judge, or refuse to override the group?

Experiment 03 evolved worker organization but forced every searched topology to end with one judge. Its champion judge changed ten hidden-final answers, helping three and harming three for zero net exact gain. Experiment 04 makes the decision mechanism itself evolvable.

Every experimental call requests `gpt-5.6-luna` with provider effort `low`, labeled publicly as **Light reasoning**, on the default Standard service tier. Fast/priority and undocumented Flex processing are not used. Subject agents cannot use tools, code, Python, files, browsing, skills, plugins, or other agents. A standard-library Python controller performs all mutation, crossover, gating, aggregation, and scoring.

## Bounded genome

A genome contains symbols, never freely generated prompt prose:

- one decision-system identifier;
- ten frozen worker-lens identifiers;
- one frozen judge-policy identifier;
- deterministic lineage and a canonical genome hash.

The six legal decision systems each use exactly ten model calls per 12-case block:

| Decision system | Calls | Deterministic final rule |
|---|---|---|
| `vote_10p` | 10 proposers | Proposal plurality |
| `judge_9p1j` | 9 proposers, 1 judge | Judge answer |
| `gated_7p2c1j` | 7 proposers, 2 critics, 1 judge | Override plurality only when both critics and the judge agree |
| `dual_8p2j` | 8 proposers, 2 independent judges | Use the judges only when they agree; otherwise plurality |
| `verified_7p2v1j` | 7 proposers, 2 verifiers, 1 judge | Override plurality only when both verifiers and the judge agree |
| `deliberative_6p2c2j` | 6 proposers, 2 critics, 2 independent judges | Override only when both judges and at least one critic agree |

Tuple equality is exact. Invalid intermediate answers abstain. When a gate does not open, the deterministic proposal plurality wins. Plurality ties use vote count, then mean reported confidence, then canonical tuple order.

The grammar deliberately excludes arbitrary prompt mutation, arbitrary code, memory systems, and variable call budgets. It is flexible at the decision layer while remaining auditable.

## Eight fixed evolutionary rounds

There are six persistent parent slots and exactly eight rounds. There is no early stopping.

In every round:

1. The controller deterministically creates six children from the six current parents: four one-gene mutations and two crossovers.
2. The six parents and six children all receive the same two fresh 12-case blocks.
3. Every candidate uses ten calls per block, for 20 calls and 24 cases per candidate.
4. Each child challenges its designated parent on the paired fresh evidence.
5. A strictly better child replaces its parent. Exact ties keep the parent.

The paired fitness order is:

1. more exact next-five cases across both blocks;
2. more exact cases on the weaker block;
3. fewer harmful overrides of a correct proposer plurality;
4. more individually correct terms;
5. more format-valid cases.

The frozen evolution seed is `swarm-seeds-04-evolution-v1`. In round `r`, the four mutation challenges target parent slots `((r - 1) + 0..3) mod 6`; the remaining two slots receive crossover challenges. A crossover challenges its first source parent, and mate candidates are inspected in fixed cyclic slot order beginning `r` positions ahead until the first unique legal recombination is found. Every symbolic choice is derived from SHA-256 over the frozen seed, a domain label, and a counter modulo the frozen symbol order. Python's version-dependent random module is not used. Global genome-history uniqueness is enforced, and exact fitness ties keep the parent.

Each round costs `12 candidates x 2 blocks x 10 calls = 240 calls`. Eight rounds cost 1,920 calls and expose the search to 192 different cases rather than repeatedly using one training block.

## Data

RuleWeave-5 retains the eight mechanism families and three difficulty tiers used by Experiment 03. Experiment 04 changes the seed and cases, not the underlying task grammar. The frozen benchmark seed is `swarm-seeds-04-evolving-the-decider-2026-07-13-a`.

| Split | Cases | Blocks | Cases per family-tier cell | Use |
|---|---:|---:|---:|---|
| Search | 192 | 16 | 8 | Two fresh blocks per evolutionary round |
| Validation | 72 | 6 | 3 | Select one champion from all six final survivors |
| Hidden final | 96 | 8 | 4 | Compare the frozen methods |

Every adjacent block pair covers all 24 family-tier cells exactly once. Every block contains four hard, four very-hard, and four stress cases. All cases and answer hashes are generated before the first model call.

The benchmark must have zero exact overlap with Experiments 02 and 03 in public prefixes, hidden canonical generator programs, and next-five targets. It must also have no internal duplicates by those definitions.

Search answers for a round may be opened only after all 240 calls in that round are terminal. Validation answers may be opened only after all 360 survivor-validation calls are terminal. Final answers may be opened only after all 320 final calls are terminal.

## Validation and final comparison

All six survivors receive all six validation blocks. The same ordered fitness rule selects one champion. The best initial founder is frozen from the founders' first-round results and is not reselected using validation or final answers.

The hidden final comparison contains four methods at the same ten-call-per-block budget:

1. evolved validation champion;
2. frozen best initial founder;
3. ten independent generalist solvers with deterministic Vote10;
4. ten independent diversified solvers with deterministic Vote10.

The generalist baseline uses the `generalist` lens in all ten slots. The diversified baseline uses this frozen order: `generalist`, `differences`, `recurrences`, `streams`, `modular`, `simplicity`, `diversifier`, `audit`, `generalist`, `audit`.

The primary comparison is champion minus diversified Vote10, the stronger simple independent-pool condition observed in Experiment 03. Champion minus best founder measures evolutionary gain. Champion minus generalist Vote10 preserves continuity with the earlier registered baseline.

The report must include paired block-stratified bootstrap intervals, exact McNemar tests, method-only wins, both-correct and both-wrong counts, proposal-plurality accuracy, useful and harmful overrides, calls, tokens, latency, malformed outputs, and retries. No superiority claim is allowed when the paired interval includes zero.

## Registered call budget

| Phase | Calculation | Calls |
|---|---:|---:|
| Eight-round search | 12 candidates x 2 blocks x 10 calls x 8 | 1,920 |
| Validation | 6 survivors x 6 blocks x 10 calls | 360 |
| Hidden final | 4 methods x 8 blocks x 10 calls | 320 |
| **Total** | | **2,600** |

Retries remain attached to the original planned call identity. Infrastructure failures receive at most two identical fresh-process retries. One schema-invalid response receives exactly one identical retry. No retry depends on mathematical correctness.

Up to 60 Codex CLI processes may run concurrently. Concurrency changes elapsed time only, never prompts, genomes, call identities, aggregation, or scores.

## Interpretation boundary

This experiment tests one model condition, one synthetic task grammar, six decision systems, and one deterministic evolutionary schedule. A positive result would show that this bounded search found a better Light-only decision policy on fresh RuleWeave cases. It would not show that evolution or judging is universally beneficial.
