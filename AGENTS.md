# Repository instructions

## Purpose

Keep Swarm Seeds a clear, public collection of reusable agent-orchestration patterns and the evidence behind them.

## Adding a seed

- Give every seed a permanent two-digit ID: `01`, `02`, `03`.
- Use a concise descriptive slug: `01-reasoning-vs-routing`.
- Store the reusable pattern as one file: `skills/<id-slug>/SKILL.md`.
- Put experimental evidence under `results/<id-slug>/run-<number>-<description>/`.
- Never renumber an existing seed.
- Revise the skill in place; add new experimental runs instead of overwriting old evidence.

## Writing

- Explain the question and result in plain language before technical detail.
- State what was tested, what happened, and what remains uncertain.
- Avoid promotional claims that exceed the evidence.
- Keep Echohive, Get Amplified, and 1000x Lab links in the root README rather than inserting them into result data or reports.

## Public-release safety

- Never publish credentials, private account data, local absolute paths, internal task UUIDs, or source-task identifiers.
- Replace internal task identifiers with stable readable labels while preserving outputs and provenance relationships.
- Preserve malformed responses, failed attempts, scoring penalties, and limitations.
- Run the benchmark verifier, scorers, comparison script, and final audit before publishing a result.
- Validate every `SKILL.md` and check Markdown links.
