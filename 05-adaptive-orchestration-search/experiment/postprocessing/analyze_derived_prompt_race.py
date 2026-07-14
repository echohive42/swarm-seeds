#!/usr/bin/env python3
"""Project split blocks to their parent panels and reuse the prompt-race analyzer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ANALYZER = SCRIPT_DIR / "analyze_prompt_race.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--strategy-batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--random-subsets", type=int, default=25000)
    parser.add_argument(
        "--block-map",
        action="append",
        default=[],
        metavar="CHILD=PARENT",
        help="Map a derived block ID to its parent analysis panel; repeat as needed.",
    )
    args = parser.parse_args()

    document = json.loads(args.predictions.read_text(encoding="utf-8"))
    mapping = {}
    for item in args.block_map:
        if "=" not in item:
            parser.error(f"invalid --block-map value: {item}")
        child, parent = item.split("=", 1)
        if not child or not parent or child in mapping:
            parser.error(f"invalid or duplicate --block-map value: {item}")
        mapping[child] = parent
    if not mapping:
        mapping = {
            "research-b05a": "research-b05",
            "research-b05b": "research-b05",
            "research-b06a": "research-b06",
            "research-b06b": "research-b06",
        }
    for row in document["records"]:
        if row.get("block_id") in mapping:
            row["block_id"] = mapping[row["block_id"]]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    projection = args.output_dir / f"{args.label}-parent-block-predictions.json"
    projection.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    completed = subprocess.run([
        sys.executable,
        str(ANALYZER),
        "--predictions", str(projection),
        "--answers", str(args.answers),
        "--strategy-batch", str(args.strategy_batch),
        "--output-dir", str(args.output_dir),
        "--random-subsets", str(args.random_subsets),
    ], check=False)
    if completed.returncode:
        return completed.returncode
    names = ("analysis.json", "lens-scores.csv", "case-scores.csv", "top-subsets.json")
    for name in names:
        source = args.output_dir / f"wide-01-{name}"
        destination = args.output_dir / f"{args.label}-{name}"
        source.replace(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
