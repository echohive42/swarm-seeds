#!/usr/bin/env python3
"""Materialize the frozen Experiment 05 validation waves."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "5.0"
ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "strategies"
FINALISTS = (
    ("batch-01.json", "B01-F03"),
    ("batch-01.json", "B01-H04"),
    ("batch-02.json", "B02-N03"),
    ("batch-02.json", "B02-H01"),
    ("batch-03.json", "B03-H01"),
    ("batch-03.json", "B03-R03"),
)
CONTROL_SOURCE = ("batch-01.json", "B01-C02")
CONTROL_ID = "VAL-CONTROL-C02"


class PreparationError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def strategy_from(filename: str, strategy_id: str) -> dict[str, Any]:
    document = load_json(STRATEGY_DIR / filename)
    matches = [
        strategy
        for strategy in document.get("strategies", [])
        if strategy.get("strategy_id") == strategy_id
    ]
    if len(matches) != 1:
        raise PreparationError(f"expected one {strategy_id} in {filename}")
    return copy.deepcopy(matches[0])


def control_strategy() -> dict[str, Any]:
    control = strategy_from(*CONTROL_SOURCE)
    control["strategy_id"] = CONTROL_ID
    control["name"] = "Diversified Vote 15 Control"
    control["description"] = (
        "Frozen strongest repeated search control: fifteen independently prompted "
        "diverse solvers followed by deterministic plurality."
    )
    return control


def build_wave_one() -> dict[str, Any]:
    strategies = [strategy_from(*source) for source in FINALISTS]
    strategies.append(control_strategy())
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-05-validation-strategy-wave",
        "wave_id": "validation-wave-01",
        "design_status": "frozen_after_search_and_before_validation_answers_open",
        "source_finalist_ids": [strategy_id for _, strategy_id in FINALISTS],
        "control_id": CONTROL_ID,
        "strategy_provenance": {
            strategy["strategy_id"]: {
                "strategy_sha256": sha256_json(strategy),
                "source_batch": next(
                    (filename for filename, item in FINALISTS if item == strategy["strategy_id"]),
                    CONTROL_SOURCE[0],
                ),
            }
            for strategy in strategies
        },
        "strategies": strategies,
    }


def top_three(summary: dict[str, Any], wave_one: dict[str, Any]) -> list[str]:
    methods = summary.get("methods")
    if not isinstance(methods, dict):
        raise PreparationError("validation summary contains no methods")
    hashes = {
        strategy["strategy_id"]: sha256_json(strategy)
        for strategy in wave_one["strategies"]
    }
    candidates: list[tuple[list[int], str, str]] = []
    for strategy_id in wave_one["source_finalist_ids"]:
        row = methods.get(strategy_id)
        key = row.get("protocol_fitness_key") if isinstance(row, dict) else None
        if not isinstance(key, list) or any(not isinstance(item, int) for item in key):
            raise PreparationError(f"missing protocol fitness for {strategy_id}")
        candidates.append((key, hashes[strategy_id], strategy_id))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [strategy_id for _, _, strategy_id in candidates[:3]]


def build_wave_two(summary_path: Path) -> dict[str, Any]:
    wave_one_path = STRATEGY_DIR / "validation-wave-01.json"
    wave_one = load_json(wave_one_path)
    selected = top_three(load_json(summary_path), wave_one)
    strategy_index = {
        strategy["strategy_id"]: strategy for strategy in wave_one["strategies"]
    }
    strategies = [copy.deepcopy(strategy_index[item]) for item in selected]
    strategies.append(copy.deepcopy(strategy_index[CONTROL_ID]))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-05-validation-strategy-wave",
        "wave_id": "validation-wave-02",
        "design_status": "mechanically_selected_from_frozen_wave-01_results",
        "selected_finalist_ids": selected,
        "control_id": CONTROL_ID,
        "selection_rule": (
            "descending validation exact cases, weakest block, negative harmful "
            "overrides, correct terms, format validity, then canonical strategy hash"
        ),
        "wave_one_sha256": hashlib.sha256(wave_one_path.read_bytes()).hexdigest(),
        "wave_one_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "strategy_provenance": {
            strategy["strategy_id"]: {"strategy_sha256": sha256_json(strategy)}
            for strategy in strategies
        },
        "strategies": strategies,
    }


def self_test() -> None:
    wave = build_wave_one()
    assert len(wave["strategies"]) == 7
    assert len(set(wave["source_finalist_ids"])) == 6
    assert wave["strategies"][-1]["strategy_id"] == CONTROL_ID
    fake = {
        "methods": {
            strategy_id: {"protocol_fitness_key": [index, 0, 0, 0, 72]}
            for index, strategy_id in enumerate(wave["source_finalist_ids"], 1)
        }
    }
    assert top_three(fake, wave) == list(reversed(wave["source_finalist_ids"][-3:]))
    print("prepare_validation.py self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("wave1", "wave2"))
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.command == "wave1":
        document = build_wave_one()
        output = args.output or STRATEGY_DIR / "validation-wave-01.json"
    else:
        if args.summary is None:
            parser.error("wave2 requires --summary")
        document = build_wave_two(args.summary.resolve())
        output = args.output or STRATEGY_DIR / "validation-wave-02.json"
    write_json(output.resolve(), document)
    print(
        json.dumps(
            {
                "output": str(output),
                "strategy_count": len(document["strategies"]),
                "strategy_ids": [item["strategy_id"] for item in document["strategies"]],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, PreparationError) as exc:
        print(f"prepare_validation.py: error: {exc}")
        raise SystemExit(2)
