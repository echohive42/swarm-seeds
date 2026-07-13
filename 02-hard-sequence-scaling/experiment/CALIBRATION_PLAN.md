# Experiment 02 Calibration Plan

## Purpose

This plan defines the small pre-final gate for Experiment 02. It uses only the 12 development cases and 12 calibration cases.

The gate has two jobs:

1. confirm that the live execution pipeline can carry a complete 12-case block through the frozen schemas and at least one complete structured route;
2. confirm that RuleWeave-5 is neither an obvious floor nor an obvious ceiling before spending 400 Luna calls on the untouched final set.

Calibration is not a miniature final experiment. It must not be used to choose a winning method, prove the main hypothesis, or tune a result until it looks favorable.

## Public terminology

Use these public labels in every table and report:

- **Light reasoning**, implemented by the provider/API setting `low`;
- **Medium reasoning**, implemented by the provider/API setting `medium`.

Do not expose `low` as the public arm name.

## Two freeze points

### Candidate freeze

Before the first calibration call, freeze a candidate version containing:

- all 12 calibration case IDs and hidden answers;
- family and tier labels;
- the independent solver prompt and schema;
- model and reasoning settings;
- independent slot labels S01 through S20;
- Vote10 and Vote20 derivation rules;
- the vote tie rule;
- the gate thresholds in this file;
- the random execution schedule;
- parser and scoring versions;
- the exact installed Codex CLI version;
- the exact requested model ID and local catalog verification record;
- all CLI feature-disable settings;
- the Python runner hash;
- the fresh-empty-directory rule;
- the candidate default and maximum concurrency of 20;
- the monitored 20-process load-gate decision rule;
- the symmetric 300-second hard timeout;
- every stage JSON output schema hash.

No item in the candidate version may change while its calibration calls are running.

### Final freeze

If every required gate passes, hash the complete benchmark, prompts, schemas, routing, execution schedule, retry rules, scoring code, analysis plan, and calibration result into the final freeze manifest.

No experimental content may change after the final freeze.

## Minimal live call plan

Every Luna call receives one complete 12-case block.

### Development pipeline smoke test

Use 22 planned Luna calls:

| Check | Reasoning | Calls |
|---|---|---:|
| Independent solver | Light | 1 |
| Independent solver | Medium | 1 |
| Complete Tournament20 path | Medium | 20 |
| Total |  | 22 |

Tournament20 is the live structured smoke path because it is the most complex final architecture and the primary matched-budget method. It exercises:

- 8 explorers;
- 4 breakers;
- 4 verifiers;
- 2 synthesizers;
- 1 red-team agent;
- 1 judge.

Swarm10 packet construction and stage transitions must also pass deterministic fixture tests before the candidate freeze. A separate live Swarm10 development run is not required by the minimal gate. If its prompt transport or parser uses machinery not exercised by Tournament20, run one complete Light Swarm10 path and record the additional 10 calls as a declared pipeline-validation extension.

### Calibration difficulty gate

Use 40 planned Luna calls:

| Pool | Calls | Derived checks |
|---|---:|---|
| Light independent S01 through S20 | 20 | Direct, Vote10, Vote20 |
| Medium independent S01 through S20 | 20 | Direct, Vote10, Vote20 |
| Total | 40 |  |

The minimum pre-final live budget is therefore:

```text
22 development calls + 40 calibration calls = 62 Luna calls
```

This is 15.5% of the 400-call final budget. Infrastructure retry attempts are logged separately and do not create new planned slots.

## CLI preflight gate

Run this gate before counting any development Luna call.

- `codex --version` reports the candidate-frozen installed version. The local machine reported `codex-cli 0.144.3` during planning; the final manifest must record the version actually used.
- The local Codex model catalog contains the exact requested ID `gpt-5.6-luna`.
- One non-model runner fixture confirms that prompts are supplied through standard input.
- `--ignore-user-config`, `--ephemeral`, read-only sandboxing, and a fresh empty working directory are active.
- Shell, unified execution, browsers, computer use, apps, MCP apps, plugins, and multi-agent fanout are disabled.
- The stage-specific JSON output schema is passed through `--output-schema`.
- Standard output is captured as unmodified JSONL, with standard error and exit status stored separately.
- The Python standard-library runner enforces the candidate maximum of 20 active processes.
- The runner enforces a 300-second process timeout with the same code path for every condition.
- No code path calls `codex exec resume` or reuses a session ID.
- The retry classifier permits a retry only when no substantive final `agent_message` exists and the attempt has an infrastructure classification.

Catalog verification establishes that the requested model identifier is locally advertised. It does not prove the exact backend snapshot. Preserve any backend telemetry returned by the service, and explicitly record snapshot telemetry as unavailable when it is not exposed.

## Monitored 20-process load gate

Use one already planned 20-call independent development or calibration pool as the load gate. Do not add model calls solely for this test. Freeze which pool will serve as the gate before launching it.

Launch all 20 calls subject to the candidate concurrency cap of 20. Capture only operational signals during the gate:

- process start and completion time;
- exit status;
- JSONL integrity;
- presence of a substantive final `agent_message`;
- initial rate-limit, transport, spawn, process, and timeout failures;
- retry classification and resolution;
- process or runner crash;
- operating-system kill or resource-exhaustion signal;
- latency distribution;
- system resource warnings available to the standard-library runner.

Do not inspect answers, vote results, term accuracy, case accuracy, family accuracy, or any other correctness signal while making the concurrency decision.

An initial infrastructure failure is a planned call's first attempt that has no substantive final `agent_message` and receives an infrastructure classification. Rate-limit and transport failures count even when a retry later succeeds. Retry them with the identical frozen prompt, model, reasoning level, role, timeout, sandbox, and session-independence policy.

The load gate has these mandatory pass conditions:

- zero unresolved infrastructure failures after the frozen retry policy;
- zero process, runner, or system crashes;
- zero operating-system kills or resource-exhaustion failures;
- zero lost or corrupted JSONL event streams;
- zero session resumes;
- no more than 1 initial infrastructure failure among 20 calls, which is at most 5%;
- fewer than 2 calls crossing 240 seconds or reaching the 300-second hard timeout;
- no runner deadlock, sustained critical resource warning, or inability to start a planned process.

If every condition passes, recommend freezing final concurrency at 20. If any condition fails, freeze final concurrency at 10. There is no intermediate concurrency, discretionary override, or repeated 20-process test until it passes.

Record the raw operational evidence, the pass or fail value for every condition, and the selected final concurrency. The choice changes elapsed time only. It does not change model calls, prompts, blocks, methods, scores, or the 400-call final budget.

After the final freeze, the selected concurrency applies to every final condition. If the frozen concurrency becomes unstable during final collection, pause the whole run. Do not lower concurrency for only one method, reasoning level, stage, or block, and do not change the frozen value without declaring a protocol deviation before correctness inspection.

## Development pipeline gate

All conditions below must pass.

### Call and identity integrity

- All 22 planned call slots have a terminal recorded outcome under the retry policy.
- Every call carries the expected split, block, reasoning, method, role, slot, and attempt identifiers.
- The two reasoning settings are correctly applied and remain isolated.
- No structured role receives independent-pool outputs or answers from another reasoning arm.
- Every call is a new ephemeral `codex exec` process with the frozen CLI version and exact requested model.
- Public Light calls carry `model_reasoning_effort=low`; Medium calls carry `model_reasoning_effort=medium`.
- Every call uses the frozen empty working directory, read-only sandbox, disabled-tool settings, stage schema, stdin prompt path, and JSONL capture.
- Active process count never exceeds the candidate maximum of 20 and, after the final freeze, never exceeds the selected value of 20 or 10.
- No process exceeds 300 seconds without receiving the frozen timeout classification.
- No call resumes or reuses a CLI session.

### Independent path

- The Light independent call returns each of the 12 development case IDs exactly once.
- The Medium independent call returns each of the 12 development case IDs exactly once.
- Every returned answer field satisfies the frozen decimal-string schema or is preserved as an explicit model failure.
- The parser never silently repairs, reorders, or numerically coerces a continuation.

### Complete Tournament20 path

- Exactly 8 explorer, 4 breaker, 4 verifier, 2 synthesizer, 1 red-team, and 1 judge call are present.
- Every stage receives only the packets allowed by the frozen routing graph.
- All 12 case IDs survive every required stage without collision or substitution.
- The final judge produces one uniquely keyed record for each development case.
- Every judge continuation contains exactly five decimal strings or is explicitly retained as a model failure.
- At least 11 of the 12 final judge continuations satisfy the frozen five-string schema.
- No packet exceeds the input limit and no response is silently truncated by the runner.
- The raw-attempt manifest, retry lineage, packet manifest, and derived judge output can be regenerated deterministically.

### Auditability

- A clean-room replay of parsing and packet assembly produces identical derived records.
- Deliberately malformed fixture outputs are rejected according to the frozen rule.
- A simulated infrastructure retry preserves the original planned call identity.
- No answer key is needed to verify any pipeline condition above.
- Raw JSONL reproduces the final `agent_message`, event order, and any available usage values without relying on rewritten console text.
- Standard error and exit status can be joined to the correct call lineage.

Development accuracy has no pass threshold. Development cases exist to test the machinery, not to estimate the final effect.

## Calibration reliability gate

Calibration uses the 40-call independent pools. All conditions below must pass separately for Light and Medium reasoning unless a pooled threshold is stated.

### Planned slots

- S01 through S20 are present exactly once.
- Vote10 uses only S01 through S10.
- Vote20 uses S01 through S20.
- Direct uses all 20 slots to estimate expected one-call accuracy.
- The frozen confidence-based vote tie rule reproduces deterministically.

### Schema reliability

Each reasoning pool contains 240 required case records:

```text
20 calls x 12 calibration cases = 240 records
```

Require:

- at least 228 of 240 records, or 95%, to contain a valid five-string continuation;
- no completed call to be entirely unmappable to the 12 frozen case IDs;
- no duplicate case ID within a call;
- no unknown case ID;
- every malformed record to remain visible and score as a Direct failure.

This gate checks whether the format is usable. It does not repair model failures or remove them from accuracy.

## Calibration difficulty gate

Calculate only the preregistered aggregate measures below. Do not inspect case-level failures to hand-edit individual sequences.

### Direct ranges

Across the 240 independent case responses at each reasoning level, require:

- Direct expected exact accuracy between 5% and 70%, inclusive.

The same range applies to both reasoning levels. The gate does not require Medium reasoning to beat Light reasoning.

### Vote10 ranges

Across the 12 calibration cases, require both Light Vote10 and Medium Vote10 to solve at least 1 case and at most 10 cases exactly.

```text
1/12 to 10/12 = 8.33% to 83.33%
```

This broad check rejects only a clear floor or ceiling.

### Vote20 ranges

Across the 12 calibration cases, require both Light Vote20 and Medium Vote20 to solve at least 2 cases and at most 10 cases exactly.

```text
2/12 to 10/12 = 16.67% to 83.33%
```

Vote20 is the closest inexpensive calibration proxy for the final primary comparison. The upper threshold leaves room for Tournament20 to improve, while the lower threshold confirms that the task is solvable. Identical Light and Medium bounds prevent the gate from forcing the expected reasoning effect into the benchmark.

### Tier coverage

The 12-case calibration manifest must contain four cases from each difficulty tier. Pool Light and Medium Vote20 only for these checks, giving eight method-case outcomes per tier.

Require:

- at least 2 of 8 easiest-tier outcomes to be exactly correct;
- at least 2 of 8 hardest-tier outcomes to be incorrect;
- pooled easiest-tier Vote20 accuracy to be at least pooled hardest-tier Vote20 accuracy.

These checks reject a tier system that is clearly inverted, an easiest tier that is still a floor, or a hardest tier that has become a ceiling.

### Forbidden calibration selection

Do not use any of these as a pass condition:

- Medium minus Light accuracy;
- Vote20 minus Vote10 accuracy;
- any method ranking;
- any result from Swarm10 or Tournament20;
- the primary Tournament20 minus Vote20 contrast;
- whether the observed pattern matches Experiment 01;
- whether a p-value or confidence interval looks favorable.

The gate selects for usable difficulty and pipeline stability, not for the desired conclusion.

## Calibration visibility

The first calibration report should expose only:

- schema counts;
- the preregistered Direct, Vote10, Vote20, and tier aggregate values;
- pass or fail for each threshold;
- call and retry integrity;
- CLI version, requested model, reasoning configuration, timeout, concurrency, session-independence, JSONL, and usage-telemetry status;
- no case-level answer or error listing.

Case-level calibration records remain preserved for audit, but they must not be used to remove, rewrite, or replace individual benchmark cases.

Final cases and final answers remain completely hidden throughout development and calibration.

## What may change before the candidate freeze

Using development evidence only, the team may change:

- wording inside role prompts and the common constraint prefix;
- JSON field layout and schema wording;
- packet serialization and stage handoffs;
- parser behavior that rejects invalid output, provided it never repairs answers;
- task-runner logging, retry bookkeeping, and manifest generation;
- global generator coefficient ranges and tier parameter ranges;
- case-generation code that fixes a rule or uniqueness bug globally;
- deterministic fixtures and operational audits;
- the randomized execution schedule;
- runner implementation details that do not alter the frozen independence, sandbox, timeout, concurrency, or retry rules.

Every change must apply by rule to the complete relevant split. Development evidence cannot justify editing a single calibration or final case.

## What cannot change within Experiment 02

The following are fixed design commitments and cannot be changed to rescue calibration:

- 12 development, 12 calibration, and 48 final cases;
- four 12-case final blocks;
- exactly five requested decimal-string terms;
- the eight registered rule families and three difficulty tiers;
- two final cases in every family by tier cell;
- GPT-5.6 Luna;
- Light and Medium reasoning settings;
- Direct estimated from 20 independent slots;
- Vote10 fixed to S01 through S10;
- Vote20 fixed to S01 through S20;
- the frozen vote and confidence tie rule;
- Swarm10 with the 5-2-2-1 call graph;
- Tournament20 with the 8-4-4-2-1-1 call graph;
- arm isolation and the no-tools constraint;
- the 400-call final design;
- exact five-term accuracy as the primary endpoint;
- Medium Tournament20 minus Medium Vote20 as the primary contrast;
- the plus or minus 10 percentage-point equivalence margin;
- the confirmatory secondary family and Holm correction;
- bootstrap, retry, correctness-firewall, and fixed-stopping rules;
- exact requested model `gpt-5.6-luna`;
- ephemeral independent `codex exec` sessions;
- `--ignore-user-config` and fresh empty working directories;
- read-only sandboxing with shell, browser, app, plugin, and multi-agent tools disabled;
- prompt delivery through standard input and stage-specific JSON output schemas;
- raw JSONL event and usage capture;
- Python standard-library execution;
- a monitored pre-freeze choice between concurrency 20 and 10, followed by one fixed final value;
- the symmetric 300-second hard timeout;
- no CLI session resume.

No final case, answer, seed, family label, tier label, or block assignment may be changed after its frozen manifest is hashed.

## If a gate fails

Do not proceed to final collection.

Classify the failure before making any change:

### Pipeline or schema failure

The team may return to development and change only the affected prompt, schema, packet, parser, or runner machinery. It may not weaken the sandbox, enable tools, change the timeout asymmetrically, exceed the candidate concurrency maximum of 20, resume a session, or substitute a model. Rerun the affected development smoke path. If the Tournament20 path changes, rerun the complete 20-call path.

### Difficulty failure

The team may change only global generator coefficient ranges or tier parameter ranges. It may not change prompts, method definitions, endpoints, analysis, or individual observed cases to obtain a preferred result.

### Reliability failure

The team may change schema wording, response-size controls, packet formatting, or transport machinery. A completed malformed model response must still remain a model failure.

After any calibration failure, the failed candidate version and all its calls remain in the record. This protocol defines no reserve calibration set and permits no replacement candidate. Stop Experiment 02 and redesign it under a new protocol version. Do not change cases or continue cycling until a favorable benchmark appears.

## Gate decision

Proceed to the final freeze only when:

1. the development pipeline gate passes;
2. the calibration reliability gate passes;
3. every calibration difficulty threshold passes;
4. the monitored load gate selects and records final concurrency of 20 or 10;
5. all retries and deviations are resolved and documented;
6. CLI version, exact requested model, reasoning mapping, tool disables, timeout, selected concurrency, session independence, and JSONL capture all match the candidate freeze;
7. the candidate manifests and aggregate gate report reproduce from raw records;
8. no final correctness has been inspected.

The gate decision is binary. There is no discretionary override for a near miss.
