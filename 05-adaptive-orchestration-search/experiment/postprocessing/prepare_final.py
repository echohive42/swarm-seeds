#!/usr/bin/env python3
"""Select two validation finalists and materialize the hidden-final strategy set."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "strategies"
CONTROL_ID = "VAL-CONTROL-C02"


class PreparationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def evidence_for(strategy_id: str, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for summary in summaries:
        row = summary.get("methods", {}).get(strategy_id)
        if not isinstance(row, dict):
            raise PreparationError(f"missing validation score for {strategy_id}")
        rows.append(row)
    block_scores = [
        int(score)
        for row in rows
        for score in row.get("block_exact_cases", {}).values()
    ]
    if not block_scores:
        raise PreparationError(f"missing block scores for {strategy_id}")
    return {
        "strategy_id": strategy_id,
        "pooled_exact_cases": sum(int(row["exact_cases"]) for row in rows),
        "weakest_replicate_block_exact": min(block_scores),
        "pooled_harmful_overrides": sum(int(row["harmful_overrides"]) for row in rows),
        "pooled_calls": sum(int(row["calls"]) for row in rows),
        "pooled_term_correct": sum(int(row["term_correct"]) for row in rows),
        "replicate_exact_cases": [int(row["exact_cases"]) for row in rows],
    }


def ranking_key(row: dict[str, Any], strategy_hash: str) -> tuple[Any, ...]:
    return (
        row["pooled_exact_cases"],
        row["weakest_replicate_block_exact"],
        -row["pooled_harmful_overrides"],
        -row["pooled_calls"],
        row["pooled_term_correct"],
        strategy_hash,
    )


def build(wave_one_summary: Path, wave_two_summary: Path) -> dict[str, Any]:
    wave_two_path = STRATEGY_DIR / "validation-wave-02.json"
    wave_two = load_json(wave_two_path)
    index = {item["strategy_id"]: item for item in wave_two["strategies"]}
    candidate_ids = list(wave_two["selected_finalist_ids"])
    summaries = [load_json(wave_one_summary), load_json(wave_two_summary)]
    evidence = [evidence_for(item, summaries) for item in candidate_ids]
    evidence.sort(
        key=lambda row: ranking_key(row, canonical_hash(index[row["strategy_id"]])),
        reverse=True,
    )
    selected = [row["strategy_id"] for row in evidence[:2]]
    strategies = [copy.deepcopy(index[item]) for item in selected]
    strategies.append(copy.deepcopy(index[CONTROL_ID]))
    return {
        "schema_version": "5.0",
        "artifact_type": "experiment-05-hidden-final-strategy-wave",
        "wave_id": "hidden-final",
        "design_status": "mechanically_selected_from_two_frozen_validation_waves",
        "selected_finalist_ids": selected,
        "control_id": CONTROL_ID,
        "selection_rule": (
            "descending pooled exact cases, weakest 12-case block across both "
            "validation executions, fewer pooled harmful overrides, fewer pooled "
            "calls, more pooled correct terms, then canonical strategy hash"
        ),
        "candidate_evidence": evidence,
        "wave_one_summary_sha256": hashlib.sha256(wave_one_summary.read_bytes()).hexdigest(),
        "wave_two_summary_sha256": hashlib.sha256(wave_two_summary.read_bytes()).hexdigest(),
        "validation_wave_two_sha256": hashlib.sha256(wave_two_path.read_bytes()).hexdigest(),
        "strategy_provenance": {
            item["strategy_id"]: {"strategy_sha256": canonical_hash(item)}
            for item in strategies
        },
        "strategies": strategies,
    }


def self_test() -> None:
    fake = [
        {
            "methods": {
                "A": {"exact_cases": 10, "harmful_overrides": 1, "calls": 5,
                      "term_correct": 40, "block_exact_cases": {"x": 2}},
                "B": {"exact_cases": 9, "harmful_overrides": 0, "calls": 5,
                      "term_correct": 41, "block_exact_cases": {"x": 3}},
            }
        },
        {
            "methods": {
                "A": {"exact_cases": 8, "harmful_overrides": 0, "calls": 5,
                      "term_correct": 39, "block_exact_cases": {"x": 1}},
                "B": {"exact_cases": 9, "harmful_overrides": 0, "calls": 5,
                      "term_correct": 40, "block_exact_cases": {"x": 2}},
            }
        },
    ]
    a = evidence_for("A", fake)
    b = evidence_for("B", fake)
    assert ranking_key(b, "0") > ranking_key(a, "f")
    print("prepare_final.py self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave-one-summary", type=Path, required=True)
    parser.add_argument("--wave-two-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=STRATEGY_DIR / "hidden-final.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    document = build(args.wave_one_summary.resolve(), args.wave_two_summary.resolve())
    write_json(args.output.resolve(), document)
    print(json.dumps({
        "output": str(args.output),
        "selected_finalist_ids": document["selected_finalist_ids"],
        "strategy_count": len(document["strategies"]),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, PreparationError) as exc:
        print(f"prepare_final.py: error: {exc}")
        raise SystemExit(2)
