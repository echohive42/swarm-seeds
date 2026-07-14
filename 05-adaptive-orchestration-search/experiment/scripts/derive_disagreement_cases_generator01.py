#!/usr/bin/env python3
"""Create single-case blocks selected only by base-panel disagreement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PUBLIC_DIR = EXPERIMENT_DIR / "benchmark" / "exploration" / "public"
OUTPUT_DIR = PUBLIC_DIR / "disagreement-single-generator-01"
SOURCE_NAMES = ("research_B11.json", "research_B12.json")
SELECTED_CASE_IDS = ("R121", "R130", "R134", "R138", "R140", "R142", "R144")


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def main() -> int:
    cases = {}
    for name in SOURCE_NAMES:
        source = json.loads((PUBLIC_DIR / name).read_text(encoding="utf-8"))
        for case in source["cases"]:
            cases[case["case_id"]] = case
    if not set(SELECTED_CASE_IDS).issubset(cases):
        raise RuntimeError("selected disagreement cases are missing")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checksums = {}
    block_files = []
    for case_id in SELECTED_CASE_IDS:
        block_id = f"dispute-{case_id.lower()}"
        document = {
            "schema_version": "5.2-exploration",
            "experiment_id": "swarm-seeds-05-exploration",
            "block_id": block_id,
            "selection_rule": "base eleven plurality support equals one",
            "cases": [cases[case_id]],
        }
        filename = f"{block_id}.json"
        payload = canonical_bytes(document)
        (OUTPUT_DIR / filename).write_bytes(payload)
        checksums[filename] = hashlib.sha256(payload).hexdigest()
        block_files.append(filename)

    manifest = {
        "schema_version": "5.2-exploration",
        "artifact_type": "disagreement-selected-single-case-manifest",
        "selection_source": "exploration-generator-01 base eleven predictions",
        "selection_rule": "select every case where all eleven base generators returned distinct answers",
        "answer_independent_at_runtime": True,
        "case_count": len(SELECTED_CASE_IDS),
        "case_ids": list(SELECTED_CASE_IDS),
        "block_files": block_files,
        "checksums": checksums,
    }
    (OUTPUT_DIR / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(json.dumps({"blocks": len(block_files), "status": "generated"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
