#!/usr/bin/env python3
"""Merge normalized prediction files without changing any record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args()
    records = []
    seen = set()
    sources = []
    for path in args.inputs:
        document = json.loads(path.read_text(encoding="utf-8"))
        source_records = document.get("records")
        if not isinstance(source_records, list):
            raise SystemExit(f"{path} has no records array")
        for record in source_records:
            identity = (record.get("job_id"), record.get("case_id"))
            if identity in seen:
                raise SystemExit(f"duplicate prediction row: {identity}")
            seen.add(identity)
            records.append(record)
        sources.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "record_count": len(source_records),
            }
        )
    output = {
        "schema_version": "predictions-v1",
        "records": records,
        "record_count": len(records),
        "records_sha256": canonical_hash(records),
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"records": len(records), "sources": len(sources)}, sort_keys=True))


if __name__ == "__main__":
    main()
