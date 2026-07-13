#!/usr/bin/env python3
"""Merge the four independently collected hidden-final prediction artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LABELS = (
    "evolved_champion",
    "best_initial_founder",
    "generalist_vote10",
    "diversified_vote10",
)
BASELINES = {"generalist_vote10", "diversified_vote10"}


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError(f"invalid prediction artifact: {path}")
    return value


def merge(inputs: dict[str, Path]) -> dict:
    if set(inputs) != set(LABELS):
        raise ValueError(f"expected exactly these labels: {', '.join(LABELS)}")
    records: list[dict] = []
    sources: dict[str, dict] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for label in LABELS:
        path = inputs[label]
        document = load(path)
        if document.get("paid_call_count") != 80 or document.get("aggregate_record_count") != 96:
            raise ValueError(f"{label} must contain 80 paid calls and 96 aggregate records")
        rewritten: list[dict] = []
        for source in document["records"]:
            row = dict(source)
            row["method"] = label
            row["candidate_id"] = label
            row["genome_id"] = None if label in BASELINES else label
            pair = (str(row.get("job_id")), str(row.get("case_id")))
            if pair in seen_pairs:
                raise ValueError(f"duplicate job/case pair after merge: {pair}")
            seen_pairs.add(pair)
            rewritten.append(row)
        records.extend(rewritten)
        sources[label] = {
            "file": path.name,
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_records_sha256": document.get("records_sha256"),
            "paid_call_count": document["paid_call_count"],
        }
    return {
        "schema_version": "4.0",
        "artifact_type": "experiment-04-final-predictions",
        "methods": list(LABELS),
        "paid_call_count": 320,
        "aggregate_record_count": 384,
        "sources": sources,
        "records": records,
        "records_sha256": canonical_sha256(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs: dict[str, Path] = {}
    for item in args.input:
        label, separator, path = item.partition("=")
        if not separator or label in inputs:
            parser.error(f"invalid or duplicate --input {item!r}")
        inputs[label] = Path(path).resolve()
    try:
        document = merge(inputs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "paid_call_count": 320, "records_sha256": document["records_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
