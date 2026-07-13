# Protocol Amendment 01: Packet Ceiling

## Decision point

This amendment was recorded after 395 of 400 planned calls had closed and before any final correctness key was opened. The append-only attempt-log prefix had SHA-256 `328753328a20c6ca4abe62ed0f85d79fe98171e74428820b6d66426e5ad3fa91` across 2,375,976 bytes.

The original runner stopped before opening five Tournament20 judge calls. Two of their anonymous evidence packets remained above the frozen 60,000-character ceiling after all allowed prose fields had been reduced to zero characters:

- `final-b02-light-tournament20-j01`: 61,255 characters
- `final-b04-light-tournament20-j01`: 62,622 characters

The other three unopened judge packets measured 55,717, 57,201, and 56,994 characters. All five used the exact same deterministic compaction path: 120, 80, 40, then 0 characters for prose fields.

## Amendment

The packet acceptance ceiling is raised uniformly from 60,000 to 65,000 characters for all five unopened judge calls. The five calls use fresh ephemeral Luna sessions and retain their frozen call IDs, reasoning settings, dependencies, schemas, timeout, concurrency, and schedule.

No packet content is rewritten. No candidate ID, answer, confidence value, score, verdict, case, prompt, model setting, routing rule, or analysis rule changes. The original freeze remains intact. A small wrapper verifies the original freeze and attempt-log prefix, changes only the runtime ceiling, then invokes the original frozen runner.

## Interpretation

This is a pre-correctness operational deviation, not a model retry. The five calls had never reached Luna. Results will be reported as a completed experiment with a disclosed protocol deviation.

The main analysis uses all completed calls. A sensitivity analysis will separately identify comparisons that depend on recovered judge calls. The primary Medium Tournament20 comparison depends on recovered block B03. Light Tournament20 depends on recovered judges in all four blocks. No missing judge is scored as an incorrect model response because no model attempt occurred before this amendment.
