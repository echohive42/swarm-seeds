#!/usr/bin/env python3
"""Post-collection scorer overlay for the frozen Experiment 02 scorer.

The frozen scorer dropped execution-role provenance inside ``score_attempt``.
That made the valid structured-arm judge role invisible to its exact-one-judge
guard. This overlay preserves those identity fields without changing any
frozen scoring, voting, failure, or statistical rule.
"""

from __future__ import annotations

import importlib.util
import hashlib
import sys
from pathlib import Path
from typing import Any


FROZEN_SCORER = Path(__file__).with_name("score_results.py")
_SPEC = importlib.util.spec_from_file_location("experiment02_frozen_scorer", FROZEN_SCORER)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen scorer: {FROZEN_SCORER}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)
_FROZEN_SCORE_ATTEMPT = _BASE.score_attempt
_FROZEN_RUN_SCORE = _BASE.run_score

PROVENANCE_FIELDS = (
    "architecture", "role", "architecture_role", "call_id", "execution_wave",
    "batch", "batch_id", "batch_index", "execution_batch", "schedule_batch",
    "selected_concurrency", "telemetry_source",
)


def score_attempt(record: dict[str, Any], truth: tuple[int, ...]) -> dict[str, Any]:
    scored = _FROZEN_SCORE_ATTEMPT(record, truth)
    for key in PROVENANCE_FIELDS:
        if key in record:
            scored[key] = record[key]
    return scored


_BASE.score_attempt = score_attempt


def run_score(args: Any) -> dict[str, Any]:
    scored = _FROZEN_RUN_SCORE(args)
    scored.setdefault("provenance", {})["postcollection_scorer"] = {
        "path": "scripts/score_results_postcollection.py",
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "frozen_base_sha256": hashlib.sha256(FROZEN_SCORER.read_bytes()).hexdigest(),
    }
    return scored


_BASE.run_score = run_score


def postcollection_self_test() -> None:
    truth = {"C01": {"answer": (1, 2, 3, 4, 5), "block": "B01"}}
    rows = [
        {"case_id": "C01", "slot": slot, "reasoning": "light",
         "prediction": ["1", "2", "3", "4", "5"], "confidence": 0.5}
        for slot in _BASE.SLOTS
    ]
    rows.extend([
        {"case_id": "C01", "architecture": "swarm10", "role": "verifier",
         "prediction": None, "_schema_compliant": False},
        {"case_id": "C01", "architecture": "swarm10", "role": "judge",
         "prediction": ["1", "2", "3", "4", "5"], "confidence": 0.8},
    ])
    result = _BASE.score_data(rows, truth)
    swarm = result["cases"][0]["methods"]["Swarm10"]
    assert swarm["role"] == "judge" and swarm["exact"] is True
    print("score_results_postcollection.py self-test: ok")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    code = _BASE.main(arguments)
    if code == 0 and "--self-test" in arguments:
        postcollection_self_test()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
