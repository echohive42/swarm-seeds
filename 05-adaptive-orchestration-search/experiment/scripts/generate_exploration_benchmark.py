#!/usr/bin/env python3
"""Generate fresh, nonconfirmatory research cases for Experiment 05 exploration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = "5.1-exploration"
EXPERIMENT_ID = "swarm-seeds-05-exploration"
BENCHMARK_ID = "ruleweave-5-general-prompt-research-v1"
ROOT_SEED = "swarm-seeds-05-generalizable-exploration-2026-07-14-d"

SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
SWARM_SEEDS_DIR = EXPERIMENT_DIR.parent.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark" / "exploration"
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
    "research": {"cases": 240, "blocks": 20, "cell_repetitions": 10, "prefix": "R"},
}


def load_source() -> ModuleType:
    spec = importlib.util.spec_from_file_location("experiment04_generator_e05_explore", SOURCE)
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
    assignments = G.build_assignments()["research"]
    public_records = []
    hidden_records = []
    audits = []
    for index, (family, tier, repetition) in enumerate(assignments, start=1):
        case_id = f"R{index:03d}"
        public, hidden, audit = RW.make_case("research", case_id, family, tier, repetition)
        hidden = dict(hidden)
        hidden["program_sha256"] = audit["program_sha256"]
        hidden["target_sha256"] = audit["target_sha256"]
        public_records.append(public)
        hidden_records.append(hidden)
        audits.append(audit)

    references = G.assert_zero_overlap(public_records, audits)
    generated = {"research": {"public": public_records, "hidden": hidden_records}}
    tier_counts = G.validate_design(generated, audits)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_DIR.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    public_cases = PUBLIC_DIR / "research_cases.jsonl"
    hidden_answers = HIDDEN_DIR / "research_answers.jsonl"
    G.write_jsonl(public_cases, public_records)
    G.write_jsonl(hidden_answers, hidden_records)
    artifacts.extend((public_cases, hidden_answers))

    blocks = []
    for index in range(1, 21):
        block = G.task_block("research", index, public_records[(index - 1) * 12:index * 12])
        blocks.append(block)
        path = PUBLIC_DIR / G.block_filename("research", index)
        path.write_bytes(RW.json_bytes(block, pretty=True))
        artifacts.append(path)
    aggregate = PUBLIC_DIR / "research_blocks.json"
    aggregate.write_bytes(RW.json_bytes({
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "research_blocks": blocks,
    }, pretty=True))
    artifacts.append(aggregate)

    audit_path = HIDDEN_DIR / "recognizer_audit.json"
    audit_path.write_bytes(RW.json_bytes({
        "benchmark_id": BENCHMARK_ID,
        "definition": "All recognized programs matching a full prefix predict one next-five tuple.",
        "cases": audits,
    }, pretty=True))
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
        "status": "exploratory_not_confirmatory",
        "task": "continue each integer sequence with exactly five terms",
        "case_count": 240,
        "block_count": 20,
        "cases_per_block": 12,
        "families": list(G.FAMILIES),
        "tiers": list(G.TIERS),
        "cases_per_family_tier_cell": 10,
        "block_tier_counts": tier_counts["research"],
        "every_adjacent_block_pair_covers_all_24_family_tier_cells_once": True,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode()),
        "overlap_guard_references": references,
        "checksums": checksums,
    }
    manifest_path = BENCHMARK_DIR / "manifest.json"
    manifest_path.write_bytes(RW.json_bytes(manifest, pretty=True))
    return manifest


if __name__ == "__main__":
    result = generate()
    print(json.dumps({
        "benchmark_id": result["benchmark_id"],
        "case_count": result["case_count"],
        "block_count": result["block_count"],
        "status": "generated",
    }, indent=2, sort_keys=True))
