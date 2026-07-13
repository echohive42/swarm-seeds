#!/usr/bin/env python3
"""Generate the deterministic Experiment 04 RuleWeave-5 benchmark.

The RuleWeave grammar, evaluator, generator, and recognizer remain owned by
Experiment 03.  This adapter imports that frozen implementation and supplies
only Experiment 04's seed, split assignment, schemas, and artifact layout.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = "4.0"
EXPERIMENT_ID = "swarm-seeds-04"
BENCHMARK_ID = "ruleweave-5-decider-v1"
ROOT_SEED = "swarm-seeds-04-evolving-the-decider-2026-07-13-a"

SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
SWARM_SEEDS_DIR = EXPERIMENT_DIR.parent.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark"
PUBLIC_DIR = BENCHMARK_DIR / "public"
HIDDEN_DIR = BENCHMARK_DIR / "hidden"
RULEWEAVE_SOURCE = (
    SWARM_SEEDS_DIR
    / "03-evolving-light-swarms"
    / "experiment"
    / "scripts"
    / "generate_benchmark.py"
)
REFERENCE_BENCHMARKS = (
    SWARM_SEEDS_DIR / "02-hard-sequence-scaling" / "experiment" / "benchmark",
    SWARM_SEEDS_DIR / "03-evolving-light-swarms" / "experiment" / "benchmark",
)

SPLIT_CONFIG = {
    "search": {"cases": 192, "blocks": 16, "cell_repetitions": 8, "prefix": "S"},
    "validation": {"cases": 72, "blocks": 6, "cell_repetitions": 3, "prefix": "V"},
    "final": {"cases": 96, "blocks": 8, "cell_repetitions": 4, "prefix": "F"},
}


def load_ruleweave() -> ModuleType:
    if not RULEWEAVE_SOURCE.is_file():
        raise FileNotFoundError(f"missing frozen RuleWeave generator: {RULEWEAVE_SOURCE}")
    name = "swarm_seeds_03_ruleweave_generator"
    spec = importlib.util.spec_from_file_location(name, RULEWEAVE_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load RuleWeave generator: {RULEWEAVE_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.ROOT_SEED = ROOT_SEED
    return module


RW = load_ruleweave()
FAMILIES = tuple(RW.FAMILIES)
TIERS = tuple(RW.TIERS)
ALL_CELLS = frozenset((family, tier) for family in FAMILIES for tier in TIERS)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(RW.json_bytes(record) for record in records))


def block_id(split: str, index: int) -> str:
    return f"{split}-b{index:02d}"


def block_filename(split: str, index: int) -> str:
    return f"{split}_B{index:02d}.json"


def task_block(split: str, index: int, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "block_id": block_id(split, index),
        "cases": [
            {"case_id": record["case_id"], "prefix": list(record["terms"])}
            for record in records
        ],
    }


def build_assignments() -> dict[str, list[tuple[str, str, int]]]:
    """Alternate complementary 12-cell blocks, then shuffle within each block.

    Thus every registered pair and every sliding adjacent pair contains each of
    the 24 family-tier cells exactly once, while each block has 4/4/4 tiers.
    """
    assignments: dict[str, list[tuple[str, str, int]]] = {}
    for split, config in SPLIT_CONFIG.items():
        split_cells: list[tuple[str, str, int]] = []
        for zero_based_block in range(config["blocks"]):
            repetition = zero_based_block // 2 + 1
            family_indices = range(0, 4) if zero_based_block % 2 == 0 else range(4, 8)
            cells = [
                (FAMILIES[family_index], tier, repetition)
                for tier in TIERS
                for family_index in family_indices
            ]
            RW.SplitMix64(
                f"{ROOT_SEED}|{split}-block-{zero_based_block + 1}"
            ).shuffle(cells)
            split_cells.extend(cells)
        assignments[split] = split_cells
    return assignments


def load_reference_description(benchmark: Path) -> dict[str, Any]:
    public: list[dict[str, Any]] = []
    for path in sorted((benchmark / "public").glob("*_cases.jsonl")):
        public.extend(read_jsonl(path))
    audit = json.loads(
        (benchmark / "hidden" / "recognizer_audit.json").read_text(encoding="utf-8")
    )
    audited = audit.get("cases")
    if not isinstance(audited, list) or len(public) != len(audited):
        raise ValueError(f"public/recognizer count mismatch in {benchmark}")
    manifest_path = benchmark / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "benchmark_id": manifest["benchmark_id"],
        "manifest_sha256": RW.sha256_bytes(manifest_path.read_bytes()),
        "case_count": len(public),
        "prefixes": {tuple(record["terms"]) for record in public},
        "programs": {str(record["program_sha256"]) for record in audited},
        "targets": {str(record["target_sha256"]) for record in audited},
    }


def assert_zero_overlap(
    public_records: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current = {
        "prefixes": [tuple(record["terms"]) for record in public_records],
        "programs": [str(record["program_sha256"]) for record in audits],
        "targets": [str(record["target_sha256"]) for record in audits],
    }
    duplicate_counts = {
        name: len(values) - len(set(values)) for name, values in current.items()
    }
    if any(duplicate_counts.values()):
        raise RuntimeError(f"internal benchmark duplicates: {duplicate_counts}")

    references = [load_reference_description(path) for path in REFERENCE_BENCHMARKS]
    current_sets = {name: set(values) for name, values in current.items()}
    for reference in references:
        overlap = {
            "visible_prefixes": len(current_sets["prefixes"] & reference["prefixes"]),
            "generator_programs": len(current_sets["programs"] & reference["programs"]),
            "next_five_targets": len(current_sets["targets"] & reference["targets"]),
        }
        if any(overlap.values()):
            raise RuntimeError(
                f"overlap with {reference['benchmark_id']}: {overlap}"
            )
    return [
        {
            "benchmark_id": item["benchmark_id"],
            "manifest_sha256": item["manifest_sha256"],
            "case_count": item["case_count"],
        }
        for item in references
    ]


def validate_design(
    generated: dict[str, dict[str, list[dict[str, Any]]]],
    audits: list[dict[str, Any]],
) -> dict[str, list[dict[str, int]]]:
    if len(audits) != sum(config["cases"] for config in SPLIT_CONFIG.values()):
        raise RuntimeError("recognizer audit count does not match split inventory")
    all_case_ids: list[str] = []
    tier_counts_by_split: dict[str, list[dict[str, int]]] = {}
    for split, config in SPLIT_CONFIG.items():
        public = generated[split]["public"]
        hidden = generated[split]["hidden"]
        if len(public) != config["cases"] or len(hidden) != config["cases"]:
            raise RuntimeError(f"wrong {split} case count")
        all_case_ids.extend(record["case_id"] for record in public)
        cell_counts = Counter((record["family"], record["tier"]) for record in hidden)
        expected = config["cell_repetitions"]
        if set(cell_counts) != ALL_CELLS or set(cell_counts.values()) != {expected}:
            raise RuntimeError(f"wrong {split} family-tier balance: {cell_counts}")

        blocks = [
            hidden[offset : offset + 12]
            for offset in range(0, len(hidden), 12)
        ]
        if len(blocks) != config["blocks"]:
            raise RuntimeError(f"wrong {split} block count")
        split_tier_counts: list[dict[str, int]] = []
        for index, records in enumerate(blocks, start=1):
            tier_counts = Counter(record["tier"] for record in records)
            if tier_counts != Counter({tier: 4 for tier in TIERS}):
                raise RuntimeError(f"wrong tier balance in {block_id(split, index)}")
            split_tier_counts.append(dict(sorted(tier_counts.items())))
        for index, (left, right) in enumerate(zip(blocks, blocks[1:]), start=1):
            pair_cells = Counter(
                (record["family"], record["tier"]) for record in left + right
            )
            if set(pair_cells) != ALL_CELLS or set(pair_cells.values()) != {1}:
                raise RuntimeError(
                    f"adjacent blocks {index}/{index + 1} fail cell coverage for {split}"
                )
        tier_counts_by_split[split] = split_tier_counts

    if len(all_case_ids) != len(set(all_case_ids)):
        raise RuntimeError("duplicate case IDs")

    audit_by_case = {record["case_id"]: record for record in audits}
    for split in SPLIT_CONFIG:
        for public, hidden in zip(
            generated[split]["public"], generated[split]["hidden"]
        ):
            audit = audit_by_case[public["case_id"]]
            if hidden["case_id"] != public["case_id"]:
                raise RuntimeError("public/hidden case order mismatch")
            if hidden["public_case_sha256"] != RW.sha256_bytes(RW.json_bytes(public)):
                raise RuntimeError(f"public hash mismatch for {public['case_id']}")
            if hidden["program_sha256"] != audit["program_sha256"]:
                raise RuntimeError(f"program hash mismatch for {public['case_id']}")
            if hidden["target_sha256"] != audit["target_sha256"]:
                raise RuntimeError(f"target hash mismatch for {public['case_id']}")
    return tier_counts_by_split


def readme_text() -> str:
    return """# RuleWeave-5 decider benchmark

This is the frozen Experiment 04 RuleWeave-5 benchmark. It reuses Experiment
03's generator and recognizer through a thin import adapter while changing the
seed, cases, split sizes, and Experiment 04 block schema.

## Layout

- `public/search_cases.jsonl` and `search_B01.json` through `search_B16.json`:
  192 search cases, two fresh blocks for each of eight evolutionary rounds
- `public/validation_cases.jsonl` and `validation_B01.json` through
  `validation_B06.json`: 72 champion-selection cases
- `public/final_cases.jsonl` and `final_B01.json` through `final_B08.json`:
  96 untouched comparison cases
- `hidden/*_answers.jsonl`: exact programs and next-five answers
- `hidden/search_R01_answers.jsonl` through `search_R08_answers.jsonl`:
  round-scoped answer-release units matching consecutive search block pairs
- `hidden/recognizer_audit.json`: ambiguity, bounds, program-hash, and target-hash audit
- `hidden/generation_receipt.json`: seed and generator provenance
- `manifest.json`: balance invariants and SHA-256 checksums
- `overlap_with_experiments_02_03.json`: separately generated exact-overlap audit

Never provide `hidden/`, the generator seed, or answers to subject agents. Each
model call receives one complete 12-case public block. Search answers are opened
only after all 240 calls for that round are terminal; validation and final
answers follow the release gates registered in `PROTOCOL.md`.

Every block has four hard, four very-hard, and four stress cases. Every pair of
consecutive blocks covers all 24 family-tier cells exactly once. Search,
validation, and final contain respectively 8, 3, and 4 cases per cell.
"""


def generate() -> dict[str, Any]:
    assignments = build_assignments()
    generated: dict[str, dict[str, list[dict[str, Any]]]] = {}
    all_public: list[dict[str, Any]] = []
    all_audits: list[dict[str, Any]] = []

    for split, cells in assignments.items():
        public_records: list[dict[str, Any]] = []
        hidden_records: list[dict[str, Any]] = []
        prefix = SPLIT_CONFIG[split]["prefix"]
        for index, (family, tier, repetition) in enumerate(cells, start=1):
            case_id = f"{prefix}{index:03d}"
            public, hidden, audit = RW.make_case(
                split, case_id, family, tier, repetition
            )
            hidden = dict(hidden)
            hidden["program_sha256"] = audit["program_sha256"]
            hidden["target_sha256"] = audit["target_sha256"]
            public_records.append(public)
            hidden_records.append(hidden)
            all_public.append(public)
            all_audits.append(audit)
        generated[split] = {"public": public_records, "hidden": hidden_records}

    reference_provenance = assert_zero_overlap(all_public, all_audits)
    tier_counts = validate_design(generated, all_audits)

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_DIR.mkdir(parents=True, exist_ok=True)
    artifact_paths: list[Path] = []
    registered_pairs: dict[str, list[list[str]]] = {}
    for split, config in SPLIT_CONFIG.items():
        public_records = generated[split]["public"]
        hidden_records = generated[split]["hidden"]
        public_jsonl = PUBLIC_DIR / f"{split}_cases.jsonl"
        hidden_jsonl = HIDDEN_DIR / f"{split}_answers.jsonl"
        write_jsonl(public_jsonl, public_records)
        write_jsonl(hidden_jsonl, hidden_records)
        artifact_paths.extend((public_jsonl, hidden_jsonl))

        blocks: list[dict[str, Any]] = []
        for index in range(1, config["blocks"] + 1):
            records = public_records[(index - 1) * 12 : index * 12]
            block = task_block(split, index, records)
            blocks.append(block)
            path = PUBLIC_DIR / block_filename(split, index)
            path.write_bytes(RW.json_bytes(block, pretty=True))
            artifact_paths.append(path)
        aggregate = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            f"{split}_blocks": blocks,
        }
        aggregate_path = PUBLIC_DIR / f"{split}_blocks.json"
        aggregate_path.write_bytes(RW.json_bytes(aggregate, pretty=True))
        artifact_paths.append(aggregate_path)
        registered_pairs[split] = [
            [block_id(split, index), block_id(split, index + 1)]
            for index in range(1, config["blocks"] + 1, 2)
        ]

    for round_index in range(1, 9):
        records = generated["search"]["hidden"][(round_index - 1) * 24 : round_index * 24]
        path = HIDDEN_DIR / f"search_R{round_index:02d}_answers.jsonl"
        write_jsonl(path, records)
        artifact_paths.append(path)

    audit_document = {
        "benchmark_id": BENCHMARK_ID,
        "definition": "All recognized DSL programs matching a complete prefix must predict the same next five terms.",
        "cases": all_audits,
    }
    recognizer_path = HIDDEN_DIR / "recognizer_audit.json"
    recognizer_path.write_bytes(RW.json_bytes(audit_document, pretty=True))
    artifact_paths.append(recognizer_path)

    receipt = {
        "benchmark_id": BENCHMARK_ID,
        "experiment_id": EXPERIMENT_ID,
        "block_schema_version": SCHEMA_VERSION,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode("utf-8")),
        "adapter": "experiment/scripts/generate_benchmark.py",
        "adapter_sha256": RW.sha256_bytes(Path(__file__).read_bytes()),
        "ruleweave_generator": "../03-evolving-light-swarms/experiment/scripts/generate_benchmark.py",
        "ruleweave_generator_sha256": RW.sha256_bytes(RULEWEAVE_SOURCE.read_bytes()),
        "reuse_mode": "dynamic import; no RuleWeave grammar or recognizer source copied",
        "arithmetic": "Python arbitrary-precision integers",
        "case_count": sum(config["cases"] for config in SPLIT_CONFIG.values()),
    }
    receipt_path = HIDDEN_DIR / "generation_receipt.json"
    receipt_path.write_bytes(RW.json_bytes(receipt, pretty=True))
    artifact_paths.append(receipt_path)

    readme_path = BENCHMARK_DIR / "README.md"
    readme_path.write_text(readme_text(), encoding="utf-8")
    artifact_paths.append(readme_path)

    checksums = {
        str(path.relative_to(BENCHMARK_DIR)): RW.sha256_bytes(path.read_bytes())
        for path in sorted(artifact_paths)
    }
    manifest = {
        "schema_version": "1.0",
        "schema_scope": "RuleWeave benchmark manifest only; experiment block packets use schema 4.0",
        "experiment_id": EXPERIMENT_ID,
        "block_schema_version": SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "task": "continue each integer sequence with exactly five terms",
        "public_reasoning_labels": ["light"],
        "provider_reasoning_setting_for_light": "low",
        "families": list(FAMILIES),
        "tiers": list(TIERS),
        "visible_terms": dict(RW.VISIBLE_BY_TIER),
        "target_terms": 5,
        "splits": {name: config["cases"] for name, config in SPLIT_CONFIG.items()},
        "blocks_per_split": {name: config["blocks"] for name, config in SPLIT_CONFIG.items()},
        "cases_per_block": 12,
        "cases_per_family_tier_cell": {
            name: config["cell_repetitions"] for name, config in SPLIT_CONFIG.items()
        },
        "block_tier_counts": tier_counts,
        "registered_adjacent_block_pairs": registered_pairs,
        "all_consecutive_block_pairs_cover_all_24_family_tier_cells_once": True,
        "search_round_answer_files": [
            f"hidden/search_R{index:02d}_answers.jsonl" for index in range(1, 9)
        ],
        "integer_policy": {
            "public_encoding": "signed decimal strings",
            "visible_max_abs": str(RW.VISIBLE_MAX),
            "target_max_abs": str(RW.TARGET_MAX),
            "intermediate_max_abs": str(RW.INTERMEDIATE_MAX),
            "reference_arithmetic": "Python arbitrary-precision integers",
        },
        "ambiguity_policy": "all recognized full-prefix DSL candidates must predict one identical next-five tuple",
        "overlap_policy": "zero internal and Experiment 02/03 overlap for exact visible prefixes, canonical program hashes, and next-five target hashes",
        "overlap_guard_references": reference_provenance,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": RW.sha256_bytes(ROOT_SEED.encode("utf-8")),
        "ruleweave_generator_sha256": RW.sha256_bytes(RULEWEAVE_SOURCE.read_bytes()),
        "checksums": checksums,
    }
    (BENCHMARK_DIR / "manifest.json").write_bytes(RW.json_bytes(manifest, pretty=True))
    return manifest


if __name__ == "__main__":
    generated_manifest = generate()
    print(
        json.dumps(
            {
                "benchmark_id": generated_manifest["benchmark_id"],
                "splits": generated_manifest["splits"],
                "blocks_per_split": generated_manifest["blocks_per_split"],
                "status": "generated",
            },
            indent=2,
            sort_keys=True,
        )
    )
