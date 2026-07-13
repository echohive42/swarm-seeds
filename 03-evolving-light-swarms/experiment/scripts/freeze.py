#!/usr/bin/env python3
"""Create or verify the immutable Experiment 03 pre-collection manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
FREEZE_PATH = EXPERIMENT_DIR / "freeze_manifest.json"

REQUIRED = (
    "PROTOCOL.md",
    "benchmark/manifest.json",
    "benchmark/public/training_block.json",
    "benchmark/public/validation_B01.json",
    "benchmark/public/validation_B02.json",
    "benchmark/public/final_B01.json",
    "benchmark/public/final_B02.json",
    "benchmark/public/final_B03.json",
    "benchmark/public/final_B04.json",
    "benchmark/hidden/training_answers.jsonl",
    "benchmark/hidden/validation_answers.jsonl",
    "benchmark/hidden/final_answers.jsonl",
    "benchmark/hidden/recognizer_audit.json",
    "benchmark/hidden/generation_receipt.json",
    "genomes/GENOME_CATALOG.json",
    "genomes/generation-00.json",
    "genomes/fixed-swarm10.json",
    "prompts/COMMON_PREFIX.txt",
    "prompts/LENSES.json",
    "prompts/answer_block.schema.json",
    "scripts/evolve.py",
    "scripts/freeze.py",
    "scripts/generate_benchmark.py",
    "scripts/merge_predictions.py",
    "scripts/orchestrate.py",
    "scripts/run_jobs.py",
    "scripts/score.py",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build() -> dict[str, object]:
    files = {}
    for relative in REQUIRED:
        path = EXPERIMENT_DIR / relative
        if not path.is_file():
            raise SystemExit(f"missing frozen input: {relative}")
        files[relative] = digest(path)
    manifest: dict[str, object] = {
        "schema_version": "experiment-03-freeze-v1",
        "experiment_id": "swarm-seeds-03",
        "model": "gpt-5.6-luna",
        "public_reasoning_label": "Light reasoning",
        "provider_reasoning_effort": "low",
        "call_budget_per_method_block": 10,
        "population_size": 6,
        "generation_count": 3,
        "validation_finalists": 3,
        "planned_calls": {
            "evolution": 180,
            "validation": 60,
            "final": 160,
            "total": 400,
        },
        "maximum_concurrency": 50,
        "schema_invalid_retries": 1,
        "infrastructure_retries": 2,
        "primary_comparison": "evolved champion minus Vote10 on 48 final cases",
        "files": files,
    }
    manifest["freeze_sha256"] = canonical_hash(manifest)
    return manifest


def create(overwrite: bool) -> None:
    if FREEZE_PATH.exists() and not overwrite:
        raise SystemExit(f"{FREEZE_PATH} already exists; use verify")
    manifest = build()
    FREEZE_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "frozen", "freeze_sha256": manifest["freeze_sha256"]}))


def verify() -> None:
    frozen = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    current = build()
    if frozen != current:
        changed = sorted(
            path
            for path in set(frozen.get("files", {})) | set(current.get("files", {}))
            if frozen.get("files", {}).get(path) != current.get("files", {}).get(path)
        )
        raise SystemExit(f"freeze verification failed; changed inputs: {changed}")
    print(json.dumps({"status": "verified", "freeze_sha256": current["freeze_sha256"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    create(args.overwrite) if args.command == "create" else verify()


if __name__ == "__main__":
    main()
