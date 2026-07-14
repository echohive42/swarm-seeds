#!/usr/bin/env python3
"""Generate and separately seal a fresh 24-case benchmark for gate 03."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = "5.2-fresh-gate"
EXPERIMENT_ID = "swarm-seeds-05-fresh-80-gate-03"
BENCHMARK_ID = "ruleweave-5-length-weighted-holdout-fresh-gate-03"
ROOT_SEED = "swarm-seeds-05-fresh-80-gate-03-2026-07-14-a"

SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
SWARM_SEEDS_DIR = EXPERIMENT_DIR.parent.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark" / "fresh-80-gate-03"
PUBLIC_DIR = BENCHMARK_DIR / "public"
HIDDEN_DIR = BENCHMARK_DIR / "hidden"
SOURCE = (
    SWARM_SEEDS_DIR
    / "04-evolving-the-decider"
    / "experiment"
    / "scripts"
    / "generate_benchmark.py"
)
REFERENCE_BENCHMARKS = (
    SWARM_SEEDS_DIR / "02-hard-sequence-scaling" / "experiment" / "benchmark",
    SWARM_SEEDS_DIR / "03-evolving-light-swarms" / "experiment" / "benchmark",
    SWARM_SEEDS_DIR / "04-evolving-the-decider" / "experiment" / "benchmark",
    EXPERIMENT_DIR / "benchmark",
)
SPLIT_CONFIG = {
    "gate": {"cases": 24, "blocks": 2, "cell_repetitions": 1, "prefix": "S"},
}


def load_source() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "experiment04_generator_e05_fresh_gate03", SOURCE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark adapter: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.SCHEMA_VERSION = SCHEMA_VERSION
    module.EXPERIMENT_ID = EXPERIMENT_ID
    module.BENCHMARK_ID = BENCHMARK_ID
    module.ROOT_SEED = ROOT_SEED
    module.EXPERIMENT_DIR = EXPERIMENT_DIR
    module.BENCHMARK_DIR = BENCHMARK_DIR
    module.PUBLIC_DIR = PUBLIC_DIR
    module.HIDDEN_DIR = HIDDEN_DIR
    module.REFERENCE_BENCHMARKS = REFERENCE_BENCHMARKS
    module.SPLIT_CONFIG = SPLIT_CONFIG
    module.RW.ROOT_SEED = ROOT_SEED
    return module


G = load_source()
RW = G.RW


def generate() -> dict[str, Any]:
    assignments = G.build_assignments()["gate"]
    public_records: list[dict[str, Any]] = []
    hidden_records: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for index, (family, tier, repetition) in enumerate(assignments, start=1):
        case_id = f"S{index:03d}"
        public, hidden, audit = RW.make_case(
            "fresh_gate_03", case_id, family, tier, repetition
        )
        hidden = dict(hidden)
        hidden["program_sha256"] = audit["program_sha256"]
        hidden["target_sha256"] = audit["target_sha256"]
        public_records.append(public)
        hidden_records.append(hidden)
        audits.append(audit)

    references = G.assert_zero_overlap(public_records, audits)
    generated = {"gate": {"public": public_records, "hidden": hidden_records}}
    G.validate_design(generated, audits)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=False)
    HIDDEN_DIR.mkdir(parents=True, exist_ok=False)

    artifacts: list[Path] = []
    public_cases = PUBLIC_DIR / "cases.jsonl"
    hidden_answers = HIDDEN_DIR / "answers.jsonl"
    G.write_jsonl(public_cases, public_records)
    G.write_jsonl(hidden_answers, hidden_records)
    artifacts.extend((public_cases, hidden_answers))

    block_files: list[str] = []
    for index in range(4):
        block_id = f"fresh-g03-{chr(ord('a') + index)}"
        block_rows = public_records[index * 6 : (index + 1) * 6]
        block = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            "block_id": block_id,
            "cases": [
                {"case_id": row["case_id"], "prefix": row["terms"]}
                for row in block_rows
            ],
        }
        path = PUBLIC_DIR / f"{block_id}.json"
        path.write_bytes(RW.json_bytes(block, pretty=True))
        artifacts.append(path)
        block_files.append(path.name)

    audit_path = HIDDEN_DIR / "recognizer_audit.json"
    audit_path.write_bytes(
        RW.json_bytes(
            {
                "benchmark_id": BENCHMARK_ID,
                "definition": "All recognized programs matching the public prefix predict one next-five tuple.",
                "cases": audits,
            },
            pretty=True,
        )
    )
    artifacts.append(audit_path)

    checksums = {
        path.relative_to(BENCHMARK_DIR).as_posix(): RW.sha256_bytes(path.read_bytes())
        for path in sorted(artifacts)
    }
    manifest = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "block_schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "status": "separately_sealed_fresh_progressive_gate",
        "task": "continue each integer sequence with exactly five terms",
        "case_count": 24,
        "block_count": 4,
        "cases_per_block": 6,
        "families": list(G.FAMILIES),
        "tiers": list(G.TIERS),
        "cases_per_family_tier_cell": 1,
        "every_family_tier_cell_present_once": True,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode("utf-8")),
        "block_files": block_files,
        "answer_file": "hidden/answers.jsonl",
        "overlap_guard_references": references,
        "checksums": checksums,
    }
    manifest_path = BENCHMARK_DIR / "manifest.json"
    manifest_path.write_bytes(RW.json_bytes(manifest, pretty=True))
    return manifest


if __name__ == "__main__":
    result = generate()
    print(
        json.dumps(
            {
                "benchmark_id": result["benchmark_id"],
                "case_count": result["case_count"],
                "block_count": result["block_count"],
                "status": "generated_and_answers_sealed",
            },
            indent=2,
            sort_keys=True,
        )
    )
