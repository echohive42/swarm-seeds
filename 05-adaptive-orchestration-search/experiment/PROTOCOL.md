# Experiment 05 protocol

Status: registered before subject collection

## Question

Can a Codex research director use case-level evidence from three completed search
batches to design a Luna Light orchestration that exceeds 50% exact accuracy and
reliably beats the strongest fixed control on a much larger hidden final?

## Fixed subject condition

- Requested model: `gpt-5.6-luna`
- Provider reasoning effort: `low`
- Public label: Light reasoning
- Service tier: Standard
- Tools, Python, code execution, browsing, files, skills, plugins, other agents,
  and external communication: disabled for every subject call
- Maximum concurrency: 60
- Implementation dependencies: Python standard library only

The provider may not report the resolved model identity in telemetry. Public
claims will therefore say requested GPT-5.6 Luna unless provider evidence becomes
available.

## Flex preflight and fallback

Codex CLI 0.144.3 accepted `service_tier = "flex"` as configuration but reported:

> Configured service tier `flex` is not advertised as supported for model
> `gpt-5.6-luna` and will be omitted from requests.

The completed smoke call therefore did not test Luna on Flex. The experiment is
registered on Standard before benchmark collection. The tier will not change
mid-experiment. The sanitized preflight record is in
`preflight/flex-preflight.json`.

## Benchmark

Freeze 336 new RuleWeave-5 cases with zero exact overlap against Experiments 02,
03, and 04:

| Split | Cases | 24-case panels | Purpose |
|---|---:|---:|---|
| Search | 72 | 3 | One fresh panel per adaptive batch |
| Validation | 72 | 3 | Select finalists after all search design ends |
| Hidden final | 192 | 8 | Primary comparison and replication |

Every 24-case panel contains exactly one case from each of the eight mechanism
families at each of the three difficulty tiers. Each model request receives at
most one 12-case block. Validation and final answers remain sealed until their
registered calls are terminal.

## Search

Run exactly three search batches. Each batch contains 20 strategy slots and one
fresh 24-case panel:

- 4 fixed controls
- 4 refinements of strong prior systems
- 4 hybrids of promising components
- 4 strategies aimed at observed failure modes
- 4 genuinely new approaches

Each strategy may use at most 15 logical calls on each 12-case block, or 30 calls
per batch. It may use fewer when its frozen routing rule finds no cases requiring
escalation. Every strategy has the same maximum allowance. The maximum search
cost is `3 x 20 x 30 = 1,800` logical calls.

The four Batch 1 controls are:

1. fifteen independent generalist solvers with deterministic plurality;
2. fifteen independently prompted diverse solvers with deterministic plurality;
3. the Experiment 04 7-proposer, 2-verifier, 1-judge agreement gate;
4. the Experiment 04 seven-proposer pool with its decision layer removed.

Codex is the sole adaptive research director. It may inspect search answers and
case-level outcomes only after every strategy in that batch is terminal. It may
then design the next 20 frozen strategies. It may not edit a strategy during its
batch, rerun a valid answer selectively, access validation or final answers, or
use hidden outcomes to revise the experiment.

Each strategy is an auditable declarative graph containing sequential stages,
agent roles, prompts, evidence inputs, per-case routing, maximum calls, and a
deterministic final selector. Strategies may use arbitrary combinations of
independent solvers, critics, verifiers, juries, judges, or no judge within the
registered call and packet limits.

## Search measurement and promotion

Primary search objective: exact five-term case accuracy.

Registered tie-breakers, in order:

1. stronger weakest 12-case block;
2. fewer harmful changes from the strategy's own initial solver plurality;
3. fewer actual logical calls;
4. more correct individual terms;
5. canonical strategy hash.

Do not compare raw scores across batches as though they used the same cases.
Promotion uses paired performance against the repeated controls within the same
panel. Advance two non-control strategies from each batch, producing six
validation finalists. Search results remain exploratory.

Record accuracy, family and tier performance, raw plurality, final answer,
useful and harmful interventions, calls, attempts, tokens, latency, invalid
outputs, stage-level marginal value, and all strategy provenance.

## Validation

Run the six frozen search finalists plus the strongest fixed control on all 72
validation cases. Then repeat the strongest three candidates plus that control
in fresh sessions on the same 72 cases. The maximum validation cost is
`7 x 3 x 30 + 4 x 3 x 30 = 990` logical calls.

Validation may select two systems for the hidden final but may not inspire new
prompt or logic changes. Selection uses pooled exact evidence, followed by the
registered tie-breakers.

## Hidden final

Run the two selected systems and the frozen strongest control on all 192 final
cases, with two independently registered executions of each configuration.
Maximum hidden-final cost is `3 x 8 x 30 x 2 = 1,440` logical calls.

The primary comparison is the validation-selected champion versus the
predeclared strongest control. Repeated executions are repeated measurements,
not additional independent sequence cases. Report per-run results plus a paired
sequence-level interval stratified by family and tier.

## Interpretation

Call the experiment successful only if the champion:

- averages more than 50% exact accuracy on the hidden final;
- exceeds the strongest control by at least 5 percentage points;
- has a paired 95% interval whose lower bound is above zero;
- has no material collapse in either independent execution; and
- completes without a serious protocol failure.

If the point estimate improves but the interval crosses zero, call the result
promising rather than successful. If systems are effectively tied, report the
accuracy and call-cost Pareto set rather than forcing a winner.

## Retry and terminal rules

- A completed schema-invalid response receives one identical-prompt retry.
- Infrastructure failures receive up to three identical-request attempts with
  bounded backoff.
- Every attempt is append-only and preserved.
- A valid completed response is never selectively rerun.
- Failed or malformed terminal calls remain in scoring under the registered
  format and accuracy rules.
- No answer key opens until every registered identity in that release unit is
  terminal.

After the hidden final opens, no prompt, routing, selector, or retry rule may be
changed. Any revision becomes a new experiment with a new hidden final.

