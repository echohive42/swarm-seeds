#!/usr/bin/env python3
"""Route maximally disputed cases to single-case deep reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


BASE_LENSES = (
    "generalist",
    "growing_block_slow",
    "hypothesis_tournament",
    "internal_panel",
    "interwoven_stream_slow",
    "lag_class_slow",
    "mdl_suffix_holdout",
    "modulus_equation",
    "periodic_delta_slow",
    "recurrence_exhaustive",
    "wildcard_compression",
)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--source-block", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cap", type=int, default=8)
    args = parser.parse_args()
    if args.cap < 1:
        raise ValueError("cap must be positive")

    document = json.loads(args.predictions.read_text(encoding="utf-8"))
    rows = [
        row
        for row in document["records"]
        if not row.get("is_final_output") and row.get("lens_id") in BASE_LENSES
    ]
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    if not by_case or any(len(case_rows) != 11 for case_rows in by_case.values()):
        raise RuntimeError("router requires exactly eleven base predictions per case")

    candidates = []
    for case_id, case_rows in sorted(by_case.items()):
        answers = [tuple(row["answer"]) for row in case_rows]
        support = Counter(answers).most_common(1)[0][1]
        if support == 1:
            candidates.append(
                {
                    "case_id": case_id,
                    "unique_answers": len(set(answers)),
                    "maximum_support": support,
                    "mean_confidence": mean(
                        float(row.get("confidence") or 0.0) for row in case_rows
                    ),
                }
            )
    candidates.sort(
        key=lambda row: (
            -row["unique_answers"],
            row["mean_confidence"],
            row["case_id"],
        )
    )
    selected = candidates[: args.cap]

    public_cases = {}
    for source_path in args.source_block:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        for case in source["cases"]:
            public_cases[case["case_id"]] = case
    if any(row["case_id"] not in public_cases for row in selected):
        raise RuntimeError("selected case is missing from supplied public blocks")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checksums = {}
    block_files = []
    for row in selected:
        case_id = row["case_id"]
        block_id = f"fresh-dispute-{case_id.lower()}"
        block = {
            "schema_version": "5.2-exploration",
            "experiment_id": "swarm-seeds-05-exploration",
            "block_id": block_id,
            "selection_rule": "all eleven base predictions are unique",
            "cases": [public_cases[case_id]],
        }
        filename = f"{block_id}.json"
        payload = canonical_bytes(block)
        (args.output_dir / filename).write_bytes(payload)
        checksums[filename] = hashlib.sha256(payload).hexdigest()
        block_files.append(filename)

    manifest = {
        "schema_version": "5.2-exploration",
        "artifact_type": "fresh-max-disagreement-route-manifest",
        "source_predictions_sha256": sha256(args.predictions),
        "base_lenses": list(BASE_LENSES),
        "selection_rule": "maximum base plurality support equals one",
        "ranking_rule": "unique answers descending, mean confidence ascending, case_id ascending",
        "cap": args.cap,
        "candidate_count_before_cap": len(candidates),
        "selected_case_count": len(selected),
        "selected": selected,
        "block_files": block_files,
        "checksums": checksums,
    }
    (args.output_dir / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "selected": len(selected),
                "status": "routed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
