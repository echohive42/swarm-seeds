#!/usr/bin/env python3
"""Analyze two hidden-final replicates with a paired stratified interval."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


CHAMPION = "B02-N03"
RUNNER_UP = "B02-H01"
CONTROL = "VAL-CONTROL-C02"
METHODS = (CHAMPION, RUNNER_UP, CONTROL)
BOOTSTRAP_REPLICATES = 100_000
BOOTSTRAP_SEED = 20_260_713


class AnalysisError(RuntimeError):
    pass


def read_matrix(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            case_id = row["case_id"]
            if case_id in rows:
                raise AnalysisError(f"duplicate case {case_id} in {path}")
            rows[case_id] = {
                "family": row["family"],
                "tier": row["tier"],
                "block": row["block"],
                "exact": {method: int(row[f"{method}.exact"]) for method in METHODS},
            }
    if len(rows) != 192:
        raise AnalysisError(f"expected 192 cases in {path}, found {len(rows)}")
    return rows


def percentile(sorted_values: list[float], probability: float) -> float:
    index = (len(sorted_values) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def paired_interval(
    rows: dict[str, dict[str, Any]], replicates: int, seed: int
) -> tuple[float, float]:
    strata: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows.values():
        strata[(row["family"], row["tier"])].append(row["paired_difference"])
    rng = random.Random(seed)
    estimates = []
    for _ in range(replicates):
        total = 0.0
        count = 0
        for values in strata.values():
            total += sum(values[rng.randrange(len(values))] for _ in values)
            count += len(values)
        estimates.append(total / count)
    estimates.sort()
    return percentile(estimates, 0.025), percentile(estimates, 0.975)


def analyze(first: Path, second: Path, protocol_audit_passed: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    matrices = [read_matrix(first), read_matrix(second)]
    if set(matrices[0]) != set(matrices[1]):
        raise AnalysisError("replicate case sets differ")
    paired_rows: list[dict[str, Any]] = []
    combined: dict[str, dict[str, Any]] = {}
    for case_id in sorted(matrices[0]):
        one, two = matrices[0][case_id], matrices[1][case_id]
        if (one["family"], one["tier"]) != (two["family"], two["tier"]):
            raise AnalysisError(f"metadata differs for {case_id}")
        champion = [one["exact"][CHAMPION], two["exact"][CHAMPION]]
        control = [one["exact"][CONTROL], two["exact"][CONTROL]]
        paired_difference = ((champion[0] - control[0]) + (champion[1] - control[1])) / 2
        combined[case_id] = {
            "family": one["family"],
            "tier": one["tier"],
            "paired_difference": paired_difference,
        }
        paired_rows.append({
            "case_id": case_id,
            "family": one["family"],
            "tier": one["tier"],
            "champion_replicate_01": champion[0],
            "champion_replicate_02": champion[1],
            "control_replicate_01": control[0],
            "control_replicate_02": control[1],
            "paired_difference": paired_difference,
        })
    replicate_accuracy = {
        method: [
            sum(row["exact"][method] for row in matrix.values()) / len(matrix)
            for matrix in matrices
        ]
        for method in METHODS
    }
    average_accuracy = {
        method: sum(values) / len(values) for method, values in replicate_accuracy.items()
    }
    delta = average_accuracy[CHAMPION] - average_accuracy[CONTROL]
    interval = paired_interval(combined, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED)
    champion_values = replicate_accuracy[CHAMPION]
    material_collapse = min(champion_values) < 0.45 or max(champion_values) - min(champion_values) > 0.10
    checks = {
        "champion_average_above_50_percent": average_accuracy[CHAMPION] > 0.50,
        "champion_lead_at_least_5_percentage_points": delta >= 0.05,
        "paired_interval_lower_bound_above_zero": interval[0] > 0,
        "no_material_replicate_collapse": not material_collapse,
        "protocol_audit_passed": protocol_audit_passed,
    }
    return {
        "schema_version": "5.0",
        "primary_champion": CHAMPION,
        "secondary_finalist": RUNNER_UP,
        "control": CONTROL,
        "case_count": 192,
        "replicate_count": 2,
        "replicate_accuracy": replicate_accuracy,
        "average_accuracy": average_accuracy,
        "champion_minus_control": delta,
        "paired_family_tier_stratified_ci95": list(interval),
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "unit": "sequence case",
            "strata": "family by tier",
            "replicate_handling": "average the two paired outcomes within each case before resampling",
        },
        "material_collapse_rule": "either champion replicate below 45% exact accuracy or more than 10 percentage points between champion replicates",
        "success_checks": checks,
        "verdict": "successful" if all(checks.values()) else "not_successful",
        "inputs": {
            "replicate_01_case_matrix_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
            "replicate_02_case_matrix_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
        },
    }, paired_rows


def write_outputs(output_dir: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "final_analysis.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "paired_cases.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicate-one", type=Path, required=True)
    parser.add_argument("--replicate-two", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol-audit-passed", action="store_true")
    args = parser.parse_args()
    summary, rows = analyze(
        args.replicate_one.resolve(), args.replicate_two.resolve(), args.protocol_audit_passed
    )
    write_outputs(args.output_dir.resolve(), summary, rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, AnalysisError) as exc:
        print(f"analyze_final.py: error: {exc}")
        raise SystemExit(2)
