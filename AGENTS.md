# Repository instructions

## Purpose

Keep Swarm Seeds a clear, public collection of reusable AI-agent orchestration patterns and the complete experiments behind them.

## Adding a seed

- Give every seed a permanent two-digit ID such as `01`, `02`, `03`, or `04`.
- Use a concise descriptive slug: `01-reasoning-vs-routing`.
- Keep the seed and all of its evidence in one root folder: `<id-slug>/`.
- Store the reusable pattern at `<id-slug>/SKILL.md`.
- Store the first complete run at `<id-slug>/experiment/`.
- Put later runs at `<id-slug>/experiments/run-02-<description>/` without overwriting the original run.
- Keep experiment images at `<id-slug>/images/` when they exist.
- Keep social copy, publishing drafts, and chart-generation working files outside this repository.
- Never renumber an existing seed.

## Writing

- Explain the question and result in plain language before technical detail.
- State what was tested, what happened, and what remains uncertain.
- Avoid claims that exceed the evidence.
- Keep Echohive, Get Amplified, and 1000x Lab links in the root README rather than result data or raw records.

## Evidence preservation

- Publish the real protocol, prompts, benchmark, outputs, failures, scoring, audits, and limitations.
- Do not replace the full experiment with a simplified example.
- Preserve malformed responses, failed attempts, scoring penalties, and uncertainty.
- Add new experimental runs instead of rewriting old evidence.

## Lean execution default

- Prefer one standard-library Python runner and append-only JSONL logs.
- Freeze questions, scoring, routing, packet limits, and retry rules before final collection.
- Preflight the largest downstream packet.
- Retry real infrastructure failures with the identical prompt and preserve every attempt.
- For future experiments, predefine one identical-prompt retry for schema-invalid completed output. Preserve both attempts and follow the frozen scoring rule.
- For large non-urgent Codex CLI runs, test whether the selected model exposes the Flex service tier. Prefer Flex when supported, allow longer timeouts and registered availability retries, and record the requested tier exactly. If completion matters more than tier purity, freeze and log a Standard fallback after bounded Flex retries. Do not assume an unsupported model or Standard fallback used Flex.
- Do not add orchestration machinery unless it protects blinding, repeatability, or evidence.

## Public-release safety

- Never publish credentials, private account data, local absolute paths, internal task UUIDs, or source-task identifiers.
- Replace internal task identifiers with stable readable labels while preserving provenance relationships.
- Run the benchmark verifier, scorers, comparison script, and final audit before publishing a result.
- Validate every `SKILL.md` and check Markdown links.
