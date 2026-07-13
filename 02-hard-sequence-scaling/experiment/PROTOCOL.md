# Experiment 02 Protocol: Hard Sequence Scaling

## Status

This document defines the frozen design for Experiment 02. Development and calibration may occur only under the rules below. Before the first final call, the benchmark, prompts, schemas, execution schedule, retry rules, scoring code, and analysis plan must be hashed into the freeze manifest.

No final rule may be changed after collection begins.

## Research question

Experiment 02 asks how one fixed AI model should spend additional inference compute on substantially harder mathematical sequences.

The design separates three possible sources of improvement:

1. stronger reasoning inside each model call;
2. more independent attempts followed by a vote;
3. structured communication among specialized agents.

The cleanest comparison is Medium Tournament20 versus Medium Vote20. Both use 20 calls, so the comparison changes routing while holding the call budget and reasoning setting fixed.

## Model and reasoning settings

Every experimental subject uses GPT-5.6 Luna.

The public reasoning labels are:

- **Light reasoning**, implemented with the provider/API setting `low`;
- **Medium reasoning**, implemented with the provider/API setting `medium`.

The two reasoning arms remain isolated. An output, summary, vote, critique, or intermediate artifact from one arm must never enter the other arm.

## Codex CLI execution contract

Every Luna call runs through `codex exec` as a new ephemeral independent session.

The reference execution layer is Codex CLI 0.144.0. The local preflight on July 13, 2026 reported `codex-cli 0.144.3`. Before the candidate freeze, record the exact installed version returned by `codex --version`. Use that same recorded version for development, calibration, and final collection. A CLI version change after the freeze requires a pause and protocol-deviation review.

Every invocation must include the equivalent of these frozen settings:

```text
codex exec
--ephemeral
--ignore-user-config
--skip-git-repo-check
--cd <fresh-empty-working-directory>
--sandbox read-only
--model gpt-5.6-luna
--output-schema <frozen-stage-schema.json>
--json
-
```

Light calls add `--config 'model_reasoning_effort="low"'`. Medium calls add `--config 'model_reasoning_effort="medium"'`. The final `-` means that the complete prompt is supplied through standard input. The prompt must not be supplied as a positional command-line argument.

The runner must also apply this frozen feature-disable set:

```text
--disable apps
--disable browser_use
--disable browser_use_external
--disable browser_use_full_cdp_access
--disable computer_use
--disable enable_mcp_apps
--disable goals
--disable hooks
--disable image_generation
--disable in_app_browser
--disable multi_agent
--disable multi_agent_v2
--disable plugin_sharing
--disable plugins
--disable remote_plugin
--disable shell_tool
--disable skill_mcp_dependency_install
--disable standalone_web_search
--disable tool_suggest
--disable unified_exec
--disable workspace_dependencies
```

The read-only sandbox is defense in depth and does not authorize tool use. No experimental prompt may request a shell, browser, app, file, network, or external tool.

Each call receives a newly created empty working directory. It must not contain a Git repository, skill file, project instruction, benchmark file, prior output, or artifact from another call. `--ignore-user-config` prevents user configuration from changing the experiment. Authentication may still use the configured Codex credential store.

Every role uses its frozen stage-specific JSON output schema through `--output-schema`. Standard output is captured verbatim as JSONL events. Standard error, process exit status, wall time, and any usage data in the JSONL stream are captured separately without rewriting the event stream.

The runner is Python standard library only. The candidate default and maximum before the final freeze is 20 active `codex exec` processes. A monitored development or calibration load gate must choose either 20 or 10 as the final concurrency. Stage dependencies remain binding, so a critic, verifier, synthesizer, red-team agent, or judge cannot start until its frozen input packet is complete.

The 20-process gate must use development or calibration calls only and must not inspect correctness. Keep concurrency at 20 only when initial infrastructure failures are at most 5%, all retries resolve, and no severe latency or resource instability occurs. Otherwise freeze concurrency at 10. The chosen value applies symmetrically to every final block, method, role, and reasoning level. Concurrency cannot change after the final freeze.

Every process has the same 300-second hard timeout measured from process start, excluding queue time. The timeout applies symmetrically to every role, method, block, and reasoning level. It cannot be increased for a difficult arm after collection begins.

The runner must never call `codex exec resume`, reuse a CLI session ID, or append a new stage to an earlier CLI session. Intermediate communication occurs only through the frozen text packets placed into a new invocation's standard-input prompt.

Before collection, verify from the local Codex model catalog that the exact requested model ID `gpt-5.6-luna` is available. Record the catalog verification time and available model identifier. If the exact ID is unavailable or rejected, stop rather than silently substitute another model.

The requested model ID, CLI version, reasoning configuration, and any model metadata exposed in JSONL must be preserved. The service may not expose the exact backend snapshot behind the requested model alias. If snapshot telemetry is unavailable, record it as unavailable and do not infer or claim a backend snapshot identity.

## Benchmark

The benchmark is RuleWeave-5. Every case contains 12 to 14 integer terms and requests the next **five** terms.

The scored continuation is an ordered array of exactly five canonical decimal strings. Exact scoring compares the five strings with the hidden reference continuation in order. A response with fewer or more than five terms is invalid. Numeric rounding, approximate values, reordered terms, repaired syntax, and post hoc interpretation are not allowed.

The subjects may not use tools, code, calculators, browsing, files, external communication, or outputs from another experimental condition.

## Data splits

The splits are disjoint:

| Split | Cases | Purpose |
|---|---:|---|
| Development | 12 | Test prompts, schemas, routing, logging, and execution machinery |
| Calibration | 12 | Check difficulty and operational stability before the freeze |
| Final | 48 | Untouched confirmatory evaluation |

Development and calibration cases, outputs, and scores must never be pooled with final evidence.

Development correctness may be inspected while the system is being built. Calibration correctness may be used only to decide whether the frozen benchmark and machinery are ready. After the final freeze, no calibration-driven prompt or scoring change is permitted.

## Final balance and blocking

The 48 final cases contain:

- 8 registered rule families;
- 3 difficulty tiers;
- exactly 2 cases in every family by tier cell;
- 6 cases from each rule family;
- 16 cases from each difficulty tier.

The final set is divided into four frozen 12-case blocks, labeled B01 through B04. Every block contains exactly four cases from each difficulty tier. Family placement follows the frozen benchmark manifest, while the complete 48-case set preserves the exact family by tier balance above.

Each Luna call receives one complete 12-case block. The call must return case-keyed outputs so each record remains traceable to its frozen case ID.

## Derived methods

Each reasoning level produces the following five reported methods.

### Direct

Direct represents expected one-call performance. It is estimated from the 20 independent solver slots for each block and reasoning level.

For an individual case, Direct accuracy is the mean correctness of its 20 independent outputs. Its deployment budget is one call even though the experiment uses 20 repetitions to estimate that one-call expectation precisely.

### Vote10

Vote10 uses the preregistered independent solver slots S01 through S10. These slots cannot be selected or replaced after outputs are observed.

### Vote20

Vote20 uses all independent solver slots S01 through S20.

Direct, Vote10, and Vote20 reuse the same independent pool. They require no additional model calls beyond S01 through S20.

Voting uses deterministic plurality over valid exact five-string tuples. A malformed independent output remains a Direct failure and casts no vote. Ties are resolved in this frozen order:

1. largest exact-answer count;
2. largest sum of supporting confidence;
3. largest median supporting confidence;
4. numerically lexicographically smallest five-integer tuple.

The earliest supporting slot may select a representative rationale only after the winning tuple is fixed. It never decides the winning answer. If no solver produces a valid tuple, the vote method is incorrect for that case.

### Swarm10

Swarm10 uses exactly 10 calls per block and reasoning level:

- 5 proposers;
- 2 critics;
- 2 verifiers;
- 1 judge.

The judge produces the only scored Swarm10 continuation. The structured arm uses fresh calls and never receives independent-pool outputs.

### Tournament20

Tournament20 uses exactly 20 calls per block and reasoning level:

- 8 explorers;
- 4 breakers;
- 4 verifiers;
- 2 synthesizers;
- 1 red-team agent;
- 1 judge.

The judge produces the only scored Tournament20 continuation. The tournament uses fresh calls and never receives independent-pool or Swarm10 outputs.

## Final call accounting

For one block at one reasoning level:

| Source | Calls |
|---|---:|
| Independent solver pool | 20 |
| Swarm10 | 10 |
| Tournament20 | 20 |
| Total | 50 |

The frozen final run therefore contains:

```text
4 blocks x 2 reasoning levels x 50 calls = 400 Luna calls
```

Every call handles 12 cases, so the run produces:

```text
400 calls x 12 case records = 4,800 case-level model responses
```

The five derived methods at two reasoning levels produce 480 final case by method by reasoning scores. These numbers describe different units and must not be used interchangeably.

Infrastructure retry attempts are logged separately and do not change the 400 planned call slots.

## Execution controls

Before final collection:

- freeze all case IDs, block assignments, prompts, schemas, roles, solver slots, and tie rules;
- freeze the model name, reasoning settings, common constraints, and output contract;
- freeze the execution order with a recorded randomization seed;
- freeze scoring and analysis code;
- hash the hidden final case and answer manifests;
- verify that no experimental prompt contains final answers or outputs from another arm.
- freeze the exact Codex CLI version, feature-disable list, empty-directory policy, selected 20-process or 10-process concurrency cap, and 300-second timeout;
- freeze the Python runner hash and every stage JSON Schema hash.

Final calls follow the frozen schedule. The schedule should interleave reasoning settings and methods so a chronological provider change cannot align perfectly with one condition. Each raw attempt receives a stable experiment ID, block ID, reasoning label, architecture role, slot ID, attempt number, timestamp, latency, and provider-reported model metadata.

## Failure and retry policy

A retry is allowed only when both conditions are true:

1. no substantive final `agent_message` event was captured;
2. the attempt is classified as an infrastructure failure.

Examples include a transport failure, provider 5xx response, process crash, or the frozen 300-second timeout with no substantive final `agent_message`.

Rules:

1. Retry the identical frozen prompt, case block, reasoning setting, method, role, and slot.
2. Allow at most two infrastructure retries after the initial attempt.
3. Preserve every failed and superseded attempt in the raw record.
4. Keep one call lineage under the original planned call ID.
5. Do not replace the block, case, role, or solver slot.
6. Do not retry a completed model response because it is malformed, incomplete, incorrect, or undesirable.
7. Start every retry with a new ephemeral `codex exec` invocation. Never resume the failed CLI session.

A captured substantive final `agent_message` makes the call a completed model attempt even when the process later exits nonzero or reaches the timeout. A completed malformed response is a model failure. A missing case record invalidates that record, while other unambiguously keyed case records from the same response remain preserved. An entirely unmappable completed response supplies no valid records for that call.

If an infrastructure failure remains unresolved after the retry limit, pause collection and record a protocol deviation. Do not add a replacement case or a new call slot.

If a task runner stalls, restart the runner with the same frozen call identity and prompt. Restarting execution does not authorize changing the experimental content.

## Correctness firewall

Final answer keys remain unavailable to the execution layer during collection.

Before all planned final call slots close, the team may inspect only operational information such as:

- call completion;
- transport failures;
- retry status;
- timestamps and latency;
- provider metadata;
- raw JSONL event presence, usage presence, and process exit status;
- mechanically detected schema presence without answer-key comparison.

The team must not inspect final accuracy, term accuracy, correct answers, per-case wins, vote correctness, method rankings, or block-level correctness. No live chart may expose those values.

After all final outputs are closed, the raw-output manifest is hashed. Only then may the hidden answer manifest be revealed to the scoring process.

## Fixed stopping rule

The final sample is fixed at 48 cases in four blocks and 400 planned Luna call slots.

Collection ends only when every planned slot has a terminal recorded outcome under the retry policy. There is:

- no outcome-based early stopping;
- no sample-size extension because a result is close;
- no removal of difficult cases;
- no substitution of failed cases;
- no prompt, architecture, vote, or scoring change after final collection starts.

If the CLI version changes, the requested model becomes unavailable, provider identity changes, the correctness firewall is breached, or unresolved infrastructure failures prevent protocol completion, pause the experiment before scoring. Any decision to resume must be documented as a protocol deviation without inspecting correctness.

## Deviations and audit

Every departure from this protocol must record:

- what happened;
- when it happened;
- which planned calls were affected;
- whether correctness had been inspected;
- the corrective action;
- whether the confirmatory interpretation remains valid.

All raw outputs, malformed responses, retries, manifests, hashes, derived scores, and audit findings remain part of the experiment record.
