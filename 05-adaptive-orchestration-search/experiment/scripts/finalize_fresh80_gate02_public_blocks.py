#!/usr/bin/env python3
"""Finalize public blocks around the already-created sealed fresh-gate cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "5.2-fresh-gate"
EXPERIMENT_ID = "swarm-seeds-05-fresh-80-gate-02"
BENCHMARK_ID = "ruleweave-5-verified-holdout-fresh-gate-02"
ROOT_SEED = "swarm-seeds-05-fresh-80-gate-02-2026-07-14-a"
SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark" / "fresh-80-gate-02"
PUBLIC_DIR = BENCHMARK_DIR / "public"
HIDDEN_DIR = BENCHMARK_DIR / "hidden"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    public_path = PUBLIC_DIR / "cases.jsonl"
    answers_path = HIDDEN_DIR / "answers.jsonl"
    if not public_path.is_file() or not answers_path.is_file():
        raise RuntimeError("the already-generated public and sealed answer files are required")
    records = [
        json.loads(line) for line in public_path.read_text().splitlines() if line
    ]
    if len(records) != 24:
        raise RuntimeError("fresh gate requires exactly 24 public cases")
    case_ids = [row.get("case_id") for row in records]
    if len(set(case_ids)) != 24 or case_ids != [f"Q{index:03d}" for index in range(1, 25)]:
        raise RuntimeError("unexpected fresh-gate case identities")
    for row in records:
        terms = row.get("terms")
        if (
            not isinstance(terms, list)
            or not 12 <= len(terms) <= 14
            or any(not isinstance(term, str) for term in terms)
        ):
            raise RuntimeError(f"invalid public terms for {row.get('case_id')}")

    block_files: list[str] = []
    checksums = {
        "public/cases.jsonl": sha256(public_path),
        "hidden/answers.jsonl": sha256(answers_path),
    }
    for index in range(4):
        block_id = f"fresh-g02-{chr(ord('a') + index)}"
        block = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            "block_id": block_id,
            "cases": [
                {"case_id": row["case_id"], "prefix": row["terms"]}
                for row in records[index * 6 : (index + 1) * 6]
            ],
        }
        path = PUBLIC_DIR / f"{block_id}.json"
        write_json(path, block)
        block_files.append(path.name)
        checksums[f"public/{path.name}"] = sha256(path)

    manifest = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "block_schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "status": "separately_sealed_fresh_progressive_gate",
        "generation_status": "Cases and answers were created once under the registered seed. Public block finalization does not parse or rewrite the answer file.",
        "task": "continue each integer sequence with exactly five terms",
        "case_count": 24,
        "block_count": 4,
        "cases_per_block": 6,
        "family_tier_design": "eight families by three tiers, one case per cell; validated by the generator before artifact creation",
        "root_seed": ROOT_SEED,
        "root_seed_sha256": hashlib.sha256(ROOT_SEED.encode()).hexdigest(),
        "block_files": block_files,
        "answer_file": "hidden/answers.jsonl",
        "checksums": checksums,
    }
    manifest_path = BENCHMARK_DIR / "manifest.json"
    write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "case_count": 24,
                "block_count": 4,
                "public_cases_sha256": checksums["public/cases.jsonl"],
                "sealed_answers_sha256": checksums["hidden/answers.jsonl"],
                "status": "public_blocks_finalized_answers_untouched",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
