#!/usr/bin/env python3
"""Audit Experiment 04 for internal and Experiment 02/03 benchmark overlap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
SWARM_SEEDS_ROOT = EXPERIMENT_ROOT.parent.parent
DEFAULT_CURRENT = EXPERIMENT_ROOT / "benchmark"
DEFAULT_REFERENCES = (
    SWARM_SEEDS_ROOT / "02-hard-sequence-scaling" / "experiment" / "benchmark",
    SWARM_SEEDS_ROOT / "03-evolving-light-swarms" / "experiment" / "benchmark",
)
DEFAULT_OUTPUT = DEFAULT_CURRENT / "overlap_with_experiments_02_03.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(benchmark: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((benchmark / "public").glob("*_cases.jsonl")):
        records.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return records


def load_audit_cases(benchmark: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (benchmark / "hidden" / "recognizer_audit.json").read_text(encoding="utf-8")
    )
    cases = value.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"missing recognizer cases in {benchmark}")
    return cases


def verify_manifest_checksums(benchmark: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise ValueError(f"missing manifest checksums in {benchmark}")
    mismatches: list[str] = []
    missing: list[str] = []
    for relative, expected in sorted(checksums.items()):
        path = benchmark / relative
        if not path.is_file():
            missing.append(relative)
        elif file_sha256(path) != expected:
            mismatches.append(relative)
    return {
        "listed_file_count": len(checksums),
        "missing_files": missing,
        "checksum_mismatches": mismatches,
        "passed": not missing and not mismatches,
    }


def describe(benchmark: Path, *, verify_checksums: bool) -> dict[str, Any]:
    manifest_path = benchmark / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public = load_cases(benchmark)
    audited = load_audit_cases(benchmark)
    if len(public) != len(audited):
        raise ValueError(f"public and recognizer counts differ in {benchmark}")
    prefixes = [tuple(record["terms"]) for record in public]
    programs = [str(record["program_sha256"]) for record in audited]
    targets = [str(record["target_sha256"]) for record in audited]
    description = {
        "benchmark_id": manifest["benchmark_id"],
        "manifest_sha256": file_sha256(manifest_path),
        "case_count": len(public),
        "unique_visible_prefix_count": len(set(prefixes)),
        "unique_program_count": len(set(programs)),
        "unique_target_count": len(set(targets)),
        "prefixes": set(prefixes),
        "programs": set(programs),
        "targets": set(targets),
    }
    if verify_checksums:
        description["manifest_checksums"] = verify_manifest_checksums(benchmark, manifest)
    return description


def public_view(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"prefixes", "programs", "targets"}
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument(
        "--reference",
        action="append",
        type=Path,
        help="reference benchmark; repeat for multiple references (defaults to E02 and E03)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    current = describe(args.current.resolve(), verify_checksums=True)
    reference_paths = args.reference or list(DEFAULT_REFERENCES)
    references = [describe(path.resolve(), verify_checksums=False) for path in reference_paths]
    overlap_by_reference: dict[str, dict[str, int]] = {}
    for reference in references:
        overlap_by_reference[reference["benchmark_id"]] = {
            "visible_prefixes": len(current["prefixes"] & reference["prefixes"]),
            "generator_programs": len(current["programs"] & reference["programs"]),
            "next_five_targets": len(current["targets"] & reference["targets"]),
        }
    aggregate_overlap = {
        key: sum(counts[key] for counts in overlap_by_reference.values())
        for key in ("visible_prefixes", "generator_programs", "next_five_targets")
    }
    internal_duplicates = {
        "visible_prefixes": current["case_count"] - current["unique_visible_prefix_count"],
        "generator_programs": current["case_count"] - current["unique_program_count"],
        "next_five_targets": current["case_count"] - current["unique_target_count"],
    }
    checksum_failures = not current["manifest_checksums"]["passed"]
    passed = (
        not any(aggregate_overlap.values())
        and not any(internal_duplicates.values())
        and not checksum_failures
    )
    report = {
        "schema_version": "experiment-04-overlap-audit-v1",
        "status": "passed" if passed else "failed",
        "current": public_view(current),
        "references": [public_view(reference) for reference in references],
        "cross_experiment_overlap_counts_by_reference": overlap_by_reference,
        "cross_experiment_overlap_counts_total": aggregate_overlap,
        "current_internal_duplicate_counts": internal_duplicates,
        "definition": {
            "visible_prefix": "exact ordered tuple of all public input terms",
            "generator_program": "SHA-256 of the hidden canonical generator program",
            "next_five_target": "SHA-256 of the hidden ordered target tuple",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "current_case_count": current["case_count"],
                "output": str(args.output),
                "status": report["status"],
                "total_overlaps": aggregate_overlap,
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
