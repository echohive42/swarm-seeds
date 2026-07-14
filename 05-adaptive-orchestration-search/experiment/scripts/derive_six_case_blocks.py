#!/usr/bin/env python3
"""Derive deterministic six-case research blocks from fresh 12-case blocks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PUBLIC_DIR = EXPERIMENT_DIR / "benchmark" / "exploration" / "public"
OUTPUT_DIR = PUBLIC_DIR / "derived-six"
SOURCE_NAMES = ("research_B05.json", "research_B06.json")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    case_ids: list[str] = []
    for source_name in SOURCE_NAMES:
        source_path = PUBLIC_DIR / source_name
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if len(source.get("cases", [])) != 12:
            raise RuntimeError(f"{source_name} does not contain 12 cases")
        stem = source["block_id"]
        for suffix, cases in zip(("a", "b"), (source["cases"][:6], source["cases"][6:])):
            block = {
                "schema_version": source["schema_version"],
                "experiment_id": source["experiment_id"],
                "block_id": f"{stem}{suffix}",
                "derived_from": source["block_id"],
                "cases": cases,
            }
            path = OUTPUT_DIR / f"{stem}{suffix}.json"
            payload = canonical_bytes(block)
            path.write_bytes(payload)
            checksums[path.name] = hashlib.sha256(payload).hexdigest()
            case_ids.extend(case["case_id"] for case in cases)
    if len(case_ids) != 24 or len(set(case_ids)) != 24:
        raise RuntimeError("derived blocks must contain 24 unique cases")
    manifest = {
        "schema_version": "5.1-exploration",
        "artifact_type": "derived-six-case-block-manifest",
        "sources": list(SOURCE_NAMES),
        "derived_block_count": 4,
        "cases_per_block": 6,
        "unique_case_count": 24,
        "case_ids": case_ids,
        "checksums": checksums,
    }
    (OUTPUT_DIR / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(json.dumps({"blocks": 4, "cases": 24, "status": "generated"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
