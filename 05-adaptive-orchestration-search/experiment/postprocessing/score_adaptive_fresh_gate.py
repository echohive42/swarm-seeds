#!/usr/bin/env python3
"""Score the pre-registered adaptive fresh-gate system."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


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
ADDED_LENSES = (
    "bounded_state_reconstruction",
    "phase_bounded_reconstruction",
    "variable_segment_reconstruction",
    "coordinate_system_duel",
)
DEEP_LENSES = (
    "interwoven_lag_forensics",
    "phase_congruence_solver",
    "recurrence_procedure_duel",
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def answer(row: dict[str, Any]) -> tuple[str, ...]:
    value = row.get("answer")
    if not isinstance(value, list) or len(value) != 5:
        raise RuntimeError("invalid answer tuple")
    return tuple(value)


def plurality(rows: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    counts: Counter[tuple[str, ...]] = Counter()
    confidence: defaultdict[tuple[str, ...], float] = defaultdict(float)
    for row in rows:
        value = answer(row)
        counts[value] += 1
        confidence[value] += float(row.get("confidence") or 0.0)
    if not counts:
        raise RuntimeError("empty plurality")
    return min(
        counts,
        key=lambda value: (
            -counts[value],
            -(confidence[value] / counts[value]),
            value,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-predictions", type=Path, required=True)
    parser.add_argument("--deep-predictions", type=Path, required=True)
    parser.add_argument("--route-manifest", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base_document = load(args.base_predictions)
    deep_document = load(args.deep_predictions)
    route = load(args.route_manifest)
    truth_rows = load_jsonl(args.answers)
    truth = {row["case_id"]: tuple(row["next"]) for row in truth_rows}
    metadata = {row["case_id"]: row for row in truth_rows}

    base_rows = [row for row in base_document["records"] if not row.get("is_final_output")]
    base_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_rows:
        base_by_case[row["case_id"]].append(row)
    cases = sorted(base_by_case)
    if len(cases) != 24:
        raise RuntimeError("fresh gate requires exactly 24 base cases")
    all_lenses = set(BASE_LENSES + ADDED_LENSES)
    for case_id, rows in base_by_case.items():
        if len(rows) != 15 or {row["lens_id"] for row in rows} != all_lenses:
            raise RuntimeError(f"incomplete base panel for {case_id}")

    selected = [row["case_id"] for row in route["selected"]]
    if route["source_predictions_sha256"] != sha256(args.base_predictions):
        raise RuntimeError("route manifest does not match base predictions")
    deep_rows = [row for row in deep_document["records"] if not row.get("is_final_output")]
    deep_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in deep_rows:
        deep_by_case[row["case_id"]].append(row)
    if set(deep_by_case) != set(selected):
        raise RuntimeError("deep prediction cases do not match route")
    for case_id, rows in deep_by_case.items():
        if len(rows) != 3 or {row["lens_id"] for row in rows} != set(DEEP_LENSES):
            raise RuntimeError(f"incomplete deep panel for {case_id}")

    base_final = {case_id: plurality(rows) for case_id, rows in base_by_case.items()}
    final = dict(base_final)
    deep_final = {}
    for case_id, rows in deep_by_case.items():
        deep_final[case_id] = plurality(rows)
        final[case_id] = deep_final[case_id]

    exact = sum(final[case_id] == truth[case_id] for case_id in cases)
    base_exact = sum(base_final[case_id] == truth[case_id] for case_id in cases)
    terms = sum(
        sum(a == b for a, b in zip(final[case_id], truth[case_id]))
        for case_id in cases
    )
    useful = sum(
        base_final[case_id] != truth[case_id] and final[case_id] == truth[case_id]
        for case_id in selected
    )
    harmful = sum(
        base_final[case_id] == truth[case_id] and final[case_id] != truth[case_id]
        for case_id in selected
    )

    all_candidates: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for row in base_rows + deep_rows:
        all_candidates[row["case_id"]].add(answer(row))
    oracle = sum(truth[case_id] in all_candidates[case_id] for case_id in cases)

    panel_exact: dict[str, int] = defaultdict(int)
    family_exact: dict[str, dict[str, int]] = defaultdict(lambda: {"exact": 0, "cases": 0})
    for case_id in cases:
        block_id = base_by_case[case_id][0]["block_id"]
        parent = block_id[:-1] if block_id.endswith(("a", "b")) else block_id
        panel_exact[parent] += final[case_id] == truth[case_id]
        family = metadata[case_id]["family"]
        family_exact[family]["cases"] += 1
        family_exact[family]["exact"] += final[case_id] == truth[case_id]

    result = {
        "schema_version": "5.2-exploration",
        "artifact_type": "experiment-05-adaptive-fresh-gate-score",
        "status": "target_reached" if exact / len(cases) >= 0.8 else "target_not_reached",
        "registered_system": {
            "exact": exact,
            "cases": len(cases),
            "exact_accuracy": exact / len(cases),
            "correct_terms": terms,
            "terms": 5 * len(cases),
            "term_accuracy": terms / (5 * len(cases)),
        },
        "base_fifteen": {
            "exact": base_exact,
            "cases": len(cases),
            "exact_accuracy": base_exact / len(cases),
        },
        "adaptive_routing": {
            "selected_cases": selected,
            "selected_count": len(selected),
            "useful_overrides": useful,
            "harmful_overrides": harmful,
        },
        "candidate_oracle": {
            "exact": oracle,
            "cases": len(cases),
            "exact_accuracy": oracle / len(cases),
        },
        "panel_exact": dict(sorted(panel_exact.items())),
        "family_exact": dict(sorted(family_exact.items())),
        "sha256": {
            "base_predictions": sha256(args.base_predictions),
            "deep_predictions": sha256(args.deep_predictions),
            "route_manifest": sha256(args.route_manifest),
            "answers": sha256(args.answers),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["registered_system"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
