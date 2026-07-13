#!/usr/bin/env python3
"""Deterministically verify every RuleWeave-5 case and design invariant."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import generate_benchmark as generator


BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "benchmark"
PUBLIC_DIR = BENCHMARK_DIR / "public"
HIDDEN_DIR = BENCHMARK_DIR / "hidden"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        require(bool(line.strip()), f"{path}: blank line {line_number}")
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise VerificationError(f"{path}: malformed JSON on line {line_number}: {error}") from error
    return records


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decimal_string(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value[0] == "-":
        return len(value) > 1 and value[1:].isdigit() and value[1] != "0"
    return value.isdigit() and (value == "0" or value[0] != "0")


def public_case_digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(generator.json_bytes(record)).hexdigest()


def verify_task_block(block: dict[str, Any], block_id: str, records: list[dict[str, Any]]) -> None:
    require(set(block) == {"block_id", "cases", "experiment_id", "schema_version"}, f"task block keys are wrong: {block_id}")
    require(block["schema_version"] == "2.0", f"task block schema is wrong: {block_id}")
    require(block["experiment_id"] == "swarm-seeds-02", f"task block experiment ID is wrong: {block_id}")
    require(block["block_id"] == block_id, f"task block ID is wrong: {block_id}")
    require(len(block["cases"]) == 12, f"task block does not contain 12 cases: {block_id}")
    expected = [
        {"case_id": record["case_id"], "prefix": record["terms"]}
        for record in records
    ]
    require(block["cases"] == expected, f"task block cases differ from public JSONL: {block_id}")
    for case in block["cases"]:
        require(set(case) == {"case_id", "prefix"}, f"task block exposes extra fields: {block_id}")
        require(all(decimal_string(value) for value in case["prefix"]), f"task block integer is noncanonical: {block_id}")


def verify_checksums(manifest: dict[str, Any]) -> int:
    count = 0
    for relative, expected in manifest["checksums"].items():
        path = BENCHMARK_DIR / relative
        require(path.is_file(), f"missing checksummed file: {relative}")
        require(digest(path) == expected, f"checksum mismatch: {relative}")
        count += 1
    return count


def verify_case(
    public: dict[str, Any],
    hidden: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    case_id = public.get("case_id")
    require(case_id == hidden.get("case_id") == audit.get("case_id"), f"case ID mismatch near {case_id}")
    require(set(public) == {"answer_format", "case_id", "target_count", "terms"}, f"unexpected public keys: {case_id}")
    require(public["target_count"] == 5, f"target count is not five: {case_id}")
    require(isinstance(public["terms"], list), f"terms are not a list: {case_id}")
    require(all(decimal_string(value) for value in public["terms"]), f"noncanonical public integer: {case_id}")
    require(all(decimal_string(value) for value in hidden["next"]), f"noncanonical answer integer: {case_id}")
    require(len(hidden["next"]) == 5, f"answer length is not five: {case_id}")
    require(hidden["visible_count"] == len(public["terms"]), f"visible length mismatch: {case_id}")
    require(
        hidden["visible_count"] == generator.VISIBLE_BY_TIER[hidden["tier"]],
        f"tier visible length mismatch: {case_id}",
    )
    require(hidden["public_case_sha256"] == public_case_digest(public), f"public case digest mismatch: {case_id}")

    program = generator.decode_program(hidden["program"])
    require(program["family"] == hidden["family"], f"program family mismatch: {case_id}")
    require(generator.allowed_program_shape(program), f"illegal DSL shape: {case_id}")
    require(generator.parameter_bounds_ok(program), f"program parameter bounds failed: {case_id}")
    require(generator.minimum_tier(program) == generator.TIER_NUMBER[hidden["tier"]], f"program tier mismatch: {case_id}")

    expected = generator.evaluate(program, hidden["visible_count"] + 5)
    actual_visible = [int(value) for value in public["terms"]]
    actual_target = [int(value) for value in hidden["next"]]
    require(expected[: hidden["visible_count"]] == actual_visible, f"visible terms do not match program: {case_id}")
    require(expected[hidden["visible_count"] :] == actual_target, f"answer does not match program: {case_id}")

    bounds_ok, bounds = generator.case_bounds_ok(program, hidden["visible_count"])
    require(bounds_ok, f"BigInt or human-solvability bounds failed: {case_id}")
    expected_bounds = {name: str(value) for name, value in bounds.items()}
    require(audit["bounds"] == expected_bounds, f"bounds audit mismatch: {case_id}")

    recomputed = generator.ambiguity_audit(program, actual_visible)
    for key, value in recomputed.items():
        require(audit.get(key) == value, f"recognizer audit mismatch for {key}: {case_id}")
    require(recomputed["intended_semantics_present"], f"recognizers missed intended program: {case_id}")
    require(recomputed["unique_next_five"], f"ambiguous next-five prediction: {case_id}")
    require(recomputed["distinct_target_predictions"] == 1, f"multiple target predictions: {case_id}")
    if hidden["tier"] != "hard":
        require(recomputed["lower_tier_candidate_count"] == 0, f"lower-tier explanation fits: {case_id}")

    expected_target_hash = hashlib.sha256(",".join(map(str, actual_target)).encode("utf-8")).hexdigest()
    expected_program_hash = hashlib.sha256(generator.canonical_program(program).encode("utf-8")).hexdigest()
    require(audit["target_sha256"] == expected_target_hash, f"target hash mismatch: {case_id}")
    require(audit["program_sha256"] == expected_program_hash, f"program hash mismatch: {case_id}")
    return {
        "case_id": case_id,
        "family": hidden["family"],
        "tier": hidden["tier"],
        "candidate_count": recomputed["candidate_count"],
        "semantic_candidate_count": recomputed["semantic_candidate_count"],
    }


def deterministic_regeneration(stored: dict[str, dict[str, list[dict[str, Any]]]]) -> int:
    assignments = generator.build_assignments()
    prefixes = {"development": "D", "calibration": "C", "final": "F"}
    widths = {"development": 2, "calibration": 2, "final": 3}
    count = 0
    for split, cells in assignments.items():
        for index, (family, tier, repetition) in enumerate(cells, start=1):
            case_id = f"{prefixes[split]}{index:0{widths[split]}d}"
            public, hidden, audit = generator.make_case(split, case_id, family, tier, repetition)
            require(public == stored[split]["public"][index - 1], f"nondeterministic public case: {case_id}")
            require(hidden == stored[split]["hidden"][index - 1], f"nondeterministic hidden case: {case_id}")
            require(audit == stored[split]["audit"][index - 1], f"nondeterministic audit: {case_id}")
            count += 1
    return count


def verify() -> dict[str, Any]:
    manifest = read_json(BENCHMARK_DIR / "manifest.json")
    require(manifest["benchmark_id"] == generator.BENCHMARK_ID, "benchmark ID mismatch")
    require(manifest["schema_version"] == "1.0", "benchmark manifest schema version is wrong")
    require("experiment packets and outputs use schema 2.0" in manifest["schema_scope"], "schema scope is unclear")
    require(manifest["public_reasoning_labels"] == ["light", "medium"], "public reasoning labels are wrong")
    require(manifest["provider_reasoning_setting_for_light"] == "low", "provider light alias is wrong")
    require(manifest["final_cases_per_family_tier_cell"] == 2, "final cell count declaration is wrong")
    checksum_count = verify_checksums(manifest)

    audit_document = read_json(HIDDEN_DIR / "recognizer_audit.json")
    audit_by_id = {record["case_id"]: record for record in audit_document["cases"]}
    require(len(audit_by_id) == 72, "recognizer audit does not contain 72 unique cases")

    stored: dict[str, dict[str, list[dict[str, Any]]]] = {}
    verified_records = []
    all_ids = []
    for split, expected_count in (("development", 12), ("calibration", 12), ("final", 48)):
        public_records = read_jsonl(PUBLIC_DIR / f"{split}_cases.jsonl")
        hidden_records = read_jsonl(HIDDEN_DIR / f"{split}_answers.jsonl")
        require(len(public_records) == expected_count, f"{split} public count mismatch")
        require(len(hidden_records) == expected_count, f"{split} hidden count mismatch")
        audit_records = []
        for public, hidden in zip(public_records, hidden_records):
            case_id = public["case_id"]
            require(case_id in audit_by_id, f"missing audit record: {case_id}")
            audit = audit_by_id[case_id]
            require(hidden["split"] == split and audit["split"] == split, f"split mismatch: {case_id}")
            verified_records.append(verify_case(public, hidden, audit))
            audit_records.append(audit)
            all_ids.append(case_id)
        stored[split] = {"public": public_records, "hidden": hidden_records, "audit": audit_records}
    require(len(all_ids) == len(set(all_ids)) == 72, "case IDs are not globally unique")

    verify_task_block(read_json(PUBLIC_DIR / "development_block.json"), "development-b01", stored["development"]["public"])
    verify_task_block(read_json(PUBLIC_DIR / "calibration_block.json"), "calibration-b01", stored["calibration"]["public"])
    aggregate = read_json(PUBLIC_DIR / "final_blocks.json")
    require(set(aggregate) == {"experiment_id", "final_blocks", "schema_version"}, "final block manifest keys are wrong")
    require(aggregate["schema_version"] == "2.0", "final block manifest schema is wrong")
    require(aggregate["experiment_id"] == "swarm-seeds-02", "final block manifest experiment ID is wrong")
    require(len(aggregate["final_blocks"]) == 4, "final block manifest does not contain four blocks")
    for block_index in range(4):
        block_id = f"B{block_index + 1:02d}"
        records = stored["final"]["public"][block_index * 12 : (block_index + 1) * 12]
        file_block = read_json(PUBLIC_DIR / f"final_{block_id}.json")
        verify_task_block(file_block, block_id, records)
        require(aggregate["final_blocks"][block_index] == file_block, f"aggregate block mismatch: {block_id}")

    development_and_calibration = stored["development"]["hidden"] + stored["calibration"]["hidden"]
    dev_cal_cells = Counter((record["family"], record["tier"]) for record in development_and_calibration)
    expected_cells = {(family, tier) for family in generator.FAMILIES for tier in generator.TIERS}
    require(set(dev_cal_cells) == expected_cells, "development plus calibration do not cover all cells")
    require(set(dev_cal_cells.values()) == {1}, "development plus calibration cell counts are not exactly one")

    final_records = stored["final"]["hidden"]
    final_cells = Counter((record["family"], record["tier"]) for record in final_records)
    require(set(final_cells) == expected_cells, "final does not cover all family-tier cells")
    require(set(final_cells.values()) == {2}, "final does not contain exactly two cases per cell")
    family_counts = Counter(record["family"] for record in final_records)
    tier_counts = Counter(record["tier"] for record in final_records)
    require(all(family_counts[family] == 6 for family in generator.FAMILIES), "final family counts are not six")
    require(all(tier_counts[tier] == 16 for tier in generator.TIERS), "final tier counts are not sixteen")
    block_counts = []
    for block in range(4):
        counts = Counter(record["tier"] for record in final_records[block * 12 : (block + 1) * 12])
        require(all(counts[tier] == 4 for tier in generator.TIERS), f"final block {block + 1} is unbalanced")
        block_counts.append(dict(sorted(counts.items())))

    regenerated_count = deterministic_regeneration(stored)
    candidate_counts = [record["candidate_count"] for record in verified_records]
    semantic_counts = [record["semantic_candidate_count"] for record in verified_records]
    return {
        "benchmark_id": generator.BENCHMARK_ID,
        "verified_cases": len(verified_records),
        "deterministically_regenerated_cases": regenerated_count,
        "checksums_verified": checksum_count,
        "public_task_blocks_verified": 6,
        "development_plus_calibration_cells": len(dev_cal_cells),
        "final_family_tier_cells": len(final_cells),
        "final_family_counts": dict(sorted(family_counts.items())),
        "final_tier_counts": dict(sorted(tier_counts.items())),
        "final_12_case_block_tier_counts": block_counts,
        "recognizer_candidate_count_range": [min(candidate_counts), max(candidate_counts)],
        "semantic_candidate_count_range": [min(semantic_counts), max(semantic_counts)],
        "distinct_next_five_predictions_per_case": 1,
        "status": "verified",
    }


if __name__ == "__main__":
    try:
        report = verify()
    except VerificationError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        raise SystemExit(1)
    print(json.dumps(report, indent=2, sort_keys=True))
