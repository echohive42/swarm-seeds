# Run records

This directory preserves the actual experiment runs.

Public artifacts include exact generated prompts, stage manifests, aggregate model predictions, routing decisions, run summaries, retry merges, and operational summaries. Search, validation, the aborted hidden-final replicate, exploration, and all three fresh 80% gates remain separate.

Machine-local `runner/` transport directories are intentionally excluded from Git. They duplicate the preserved prompts and aggregate outputs while containing local filesystem paths, shell snapshot identifiers, process traces, and large event streams. Infrastructure failures, malformed-output counts, retries, terminal outcomes, and the hidden-final abort remain recorded in the public registrations, summaries, and result artifacts.
