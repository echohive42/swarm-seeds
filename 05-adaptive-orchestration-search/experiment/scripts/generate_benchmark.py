#!/usr/bin/env python3
"""Generate the fresh Experiment 05 RuleWeave-5 benchmark."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = "5.0"
EXPERIMENT_ID = "swarm-seeds-05"
BENCHMARK_ID = "ruleweave-5-adaptive-director-v1"
ROOT_SEED = "swarm-seeds-05-adaptive-orchestration-search-2026-07-13-a"

SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
SWARM_SEEDS_DIR = EXPERIMENT_DIR.parent.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark"
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
)
SPLIT_CONFIG = {
    "search": {"cases": 72, "blocks": 6, "cell_repetitions": 3, "prefix": "S"},
    "validation": {"cases": 72, "blocks": 6, "cell_repetitions": 3, "prefix": "V"},
    "final": {"cases": 192, "blocks": 16, "cell_repetitions": 8, "prefix": "F"},
}


def load_source() -> ModuleType:
    spec = importlib.util.spec_from_file_location("experiment04_generator_e05", SOURCE)
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


def benchmark_readme() -> str:
    return """# RuleWeave-5 adaptive-director benchmark

This fresh Experiment 05 benchmark contains 336 exact next-five sequence cases:
72 search, 72 validation, and 192 hidden final. Every registered 24-case panel
contains each of the 24 family and difficulty cells once. Every model request
receives one public block of at most 12 cases.

Search uses three consecutive block pairs, one per adaptive batch. Validation
uses three pairs. The hidden final uses eight pairs. Search answer files open
only after all calls in their batch are terminal. Validation and final answers
remain sealed until their registered release gates.

The generator rejects internal duplicates and exact visible-prefix, canonical
program, or next-five-target overlap with Experiments 02, 03, and 04.
"""


def generate() -> dict[str, Any]:
    assignments = G.build_assignments()
    generated: dict[str, dict[str, list[dict[str, Any]]]] = {}
    all_public: list[dict[str, Any]] = []
    all_audits: list[dict[str, Any]] = []
    for split, cells in assignments.items():
        public_records: list[dict[str, Any]] = []
        hidden_records: list[dict[str, Any]] = []
        prefix = SPLIT_CONFIG[split]["prefix"]
        for index, (family, tier, repetition) in enumerate(cells, start=1):
            case_id = f"{prefix}{index:03d}"
            public, hidden, audit = RW.make_case(split, case_id, family, tier, repetition)
            hidden = dict(hidden)
            hidden["program_sha256"] = audit["program_sha256"]
            hidden["target_sha256"] = audit["target_sha256"]
            public_records.append(public)
            hidden_records.append(hidden)
            all_public.append(public)
            all_audits.append(audit)
        generated[split] = {"public": public_records, "hidden": hidden_records}

    references = G.assert_zero_overlap(all_public, all_audits)
    tier_counts = G.validate_design(generated, all_audits)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_DIR.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []
    registered_pairs: dict[str, list[list[str]]] = {}

    for split, config in SPLIT_CONFIG.items():
        public_records = generated[split]["public"]
        hidden_records = generated[split]["hidden"]
        public_path = PUBLIC_DIR / f"{split}_cases.jsonl"
        hidden_path = HIDDEN_DIR / f"{split}_answers.jsonl"
        G.write_jsonl(public_path, public_records)
        G.write_jsonl(hidden_path, hidden_records)
        artifacts.extend((public_path, hidden_path))
        blocks: list[dict[str, Any]] = []
        for index in range(1, config["blocks"] + 1):
            records = public_records[(index - 1) * 12:index * 12]
            block = G.task_block(split, index, records)
            blocks.append(block)
            path = PUBLIC_DIR / G.block_filename(split, index)
            path.write_bytes(RW.json_bytes(block, pretty=True))
            artifacts.append(path)
        aggregate = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            f"{split}_blocks": blocks,
        }
        aggregate_path = PUBLIC_DIR / f"{split}_blocks.json"
        aggregate_path.write_bytes(RW.json_bytes(aggregate, pretty=True))
        artifacts.append(aggregate_path)
        registered_pairs[split] = [
            [G.block_id(split, index), G.block_id(split, index + 1)]
            for index in range(1, config["blocks"] + 1, 2)
        ]

    for batch in range(1, 4):
        records = generated["search"]["hidden"][(batch - 1) * 24:batch * 24]
        path = HIDDEN_DIR / f"search_B{batch:02d}_answers.jsonl"
        G.write_jsonl(path, records)
        artifacts.append(path)

    audit_path = HIDDEN_DIR / "recognizer_audit.json"
    audit_path.write_bytes(RW.json_bytes({
        "benchmark_id": BENCHMARK_ID,
        "definition": "All recognized DSL programs matching a complete prefix must predict the same next five terms.",
        "cases": all_audits,
    }, pretty=True))
    artifacts.append(audit_path)

    receipt_path = HIDDEN_DIR / "generation_receipt.json"
    receipt_path.write_bytes(RW.json_bytes({
        "adapter": "experiment/scripts/generate_benchmark.py",
        "adapter_sha256": RW.sha256_bytes(Path(__file__).read_bytes()),
        "benchmark_id": BENCHMARK_ID,
        "block_schema_version": SCHEMA_VERSION,
        "case_count": 336,
        "experiment_id": EXPERIMENT_ID,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode("utf-8")),
        "ruleweave_generator": "../03-evolving-light-swarms/experiment/scripts/generate_benchmark.py",
        "ruleweave_generator_sha256": RW.sha256_bytes(G.RULEWEAVE_SOURCE.read_bytes()),
    }, pretty=True))
    artifacts.append(receipt_path)

    readme_path = BENCHMARK_DIR / "README.md"
    readme_path.write_text(benchmark_readme(), encoding="utf-8")
    artifacts.append(readme_path)
    overlap_path = BENCHMARK_DIR / "overlap_with_experiments_02_03_04.json"
    overlap_path.write_bytes(RW.json_bytes({
        "benchmark_id": BENCHMARK_ID,
        "internal_duplicates": 0,
        "overlap_counts": {
            item["benchmark_id"]: {
                "canonical_programs": 0,
                "next_five_targets": 0,
                "visible_prefixes": 0,
            }
            for item in references
        },
        "references": references,
    }, pretty=True))
    artifacts.append(overlap_path)

    checksums = {
        str(path.relative_to(BENCHMARK_DIR)): RW.sha256_bytes(path.read_bytes())
        for path in sorted(artifacts)
    }
    manifest = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "block_schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "task": "continue each integer sequence with exactly five terms",
        "families": list(G.FAMILIES),
        "tiers": list(G.TIERS),
        "splits": {name: config["cases"] for name, config in SPLIT_CONFIG.items()},
        "blocks_per_split": {name: config["blocks"] for name, config in SPLIT_CONFIG.items()},
        "cases_per_block": 12,
        "cases_per_family_tier_cell": {
            name: config["cell_repetitions"] for name, config in SPLIT_CONFIG.items()
        },
        "block_tier_counts": tier_counts,
        "registered_adjacent_block_pairs": registered_pairs,
        "all_consecutive_block_pairs_cover_all_24_family_tier_cells_once": True,
        "search_batch_answer_files": [
            f"hidden/search_B{index:02d}_answers.jsonl" for index in range(1, 4)
        ],
        "visible_terms": dict(RW.VISIBLE_BY_TIER),
        "target_terms": 5,
        "provider_reasoning_setting_for_light": "low",
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode("utf-8")),
        "overlap_guard_references": references,
        "checksums": checksums,
    }
    (BENCHMARK_DIR / "manifest.json").write_bytes(RW.json_bytes(manifest, pretty=True))
    return manifest


if __name__ == "__main__":
    result = generate()
    print(json.dumps({
        "benchmark_id": result["benchmark_id"],
        "blocks_per_split": result["blocks_per_split"],
        "splits": result["splits"],
        "status": "generated",
    }, indent=2, sort_keys=True))

