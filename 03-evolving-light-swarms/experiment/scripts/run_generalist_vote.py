#!/usr/bin/env python3
"""Run Amendment 01's protocol-compliant ten-generalist Vote10 baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import orchestrate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, nargs="+", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    blocks = orchestrate.load_blocks([path.resolve() for path in args.blocks])
    run_dir = args.run_dir.resolve()
    common = (orchestrate.PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8")
    catalog = orchestrate.load_json(orchestrate.PROMPT_DIR / "LENSES.json")
    generalist_lens = catalog["worker"]["generalist"]
    jobs = []
    for block in blocks:
        for index in range(1, 11):
            job_id = f"amendment-01-VOTE10-{block['block_id']}-proposer-{index:02d}"
            prompt_path = run_dir / "prompts" / f"{job_id}.txt"
            orchestrate.write_text(
                prompt_path,
                orchestrate.render_prompt(
                    common=common,
                    role="proposer",
                    lens=generalist_lens,
                    policy=None,
                    block=block,
                    packet=None,
                ),
            )
            jobs.append(
                {
                    "job_id": job_id,
                    "phase": "final-amendment-01",
                    "method": "Vote10",
                    "genome_id": "VOTE10",
                    "block_id": block["block_id"],
                    "role": "proposer",
                    "call_index": index,
                    "prompt": prompt_path.read_text(encoding="utf-8"),
                    "output_schema": orchestrate.load_json(orchestrate.SCHEMA_PATH),
                    "expected_block_id": block["block_id"],
                    "expected_case_ids": [case["case_id"] for case in block["cases"]],
                }
            )

    orchestrate.invoke_runner(
        jobs,
        run_dir,
        args.codex_binary.resolve(),
        args.concurrency,
        args.timeout_seconds,
        "vote10-generalist",
    )
    predictions = orchestrate.normalize_predictions(run_dir, jobs)
    orchestrate.write_json(
        run_dir / "run_summary.json",
        {
            "schema_version": "experiment-03-amendment-01-run-v1",
            "amendment": "AMENDMENT-01.md",
            "phase": "final-amendment-01",
            "blocks": [block["block_id"] for block in blocks],
            "genomes": ["VOTE10"],
            "worker_lens": "generalist",
            "planned_calls": len(jobs),
            "concurrency": args.concurrency,
            "common_prefix_sha256": hashlib.sha256(common.encode("utf-8")).hexdigest(),
            "generalist_lens_sha256": hashlib.sha256(generalist_lens.encode("utf-8")).hexdigest(),
            "prediction_records_sha256": predictions["records_sha256"],
        },
    )
    print(json.dumps({"status": "complete", "planned_calls": len(jobs)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
