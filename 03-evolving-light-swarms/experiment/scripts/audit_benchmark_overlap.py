#!/usr/bin/env python3
"""Prove Experiment 03 does not reuse Experiment 02 cases or programs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parent.parent
DEFAULT_CURRENT = EXPERIMENT_ROOT / "benchmark"
DEFAULT_REFERENCE = REPO_ROOT / "02-hard-sequence-scaling" / "experiment" / "benchmark"
DEFAULT_OUTPUT = DEFAULT_CURRENT / "overlap_with_experiment_02.json"


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
    value = json.loads((benchmark / "hidden" / "recognizer_audit.json").read_text(encoding="utf-8"))
    cases = value.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"missing recognizer cases in {benchmark}")
    return cases


def describe(benchmark: Path) -> dict[str, Any]:
    manifest_path = benchmark / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public = load_cases(benchmark)
    audited = load_audit_cases(benchmark)
    prefixes = [tuple(record["terms"]) for record in public]
    programs = [str(record["program_sha256"]) for record in audited]
    targets = [str(record["target_sha256"]) for record in audited]
    if not (len(public) == len(audited) == len(prefixes)):
        raise ValueError(f"public and recognizer counts differ in {benchmark}")
    return {
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


def public_view(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"prefixes", "programs", "targets"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    current = describe(args.current.resolve())
    reference = describe(args.reference.resolve())
    overlaps = {
        "visible_prefixes": len(current["prefixes"] & reference["prefixes"]),
        "generator_programs": len(current["programs"] & reference["programs"]),
        "next_five_targets": len(current["targets"] & reference["targets"]),
    }
    current_internal_duplicates = {
        "visible_prefixes": current["case_count"] - current["unique_visible_prefix_count"],
        "generator_programs": current["case_count"] - current["unique_program_count"],
        "next_five_targets": current["case_count"] - current["unique_target_count"],
    }
    passed = not any(overlaps.values()) and not any(current_internal_duplicates.values())
    report = {
        "schema_version": "experiment-03-overlap-audit-v1",
        "status": "passed" if passed else "failed",
        "current": public_view(current),
        "reference": public_view(reference),
        "cross_experiment_overlap_counts": overlaps,
        "current_internal_duplicate_counts": current_internal_duplicates,
        "definition": {
            "visible_prefix": "exact ordered tuple of all public input terms",
            "generator_program": "SHA-256 of the hidden canonical generator program",
            "next_five_target": "SHA-256 of the hidden ordered target tuple",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["status"], "overlaps": overlaps}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
