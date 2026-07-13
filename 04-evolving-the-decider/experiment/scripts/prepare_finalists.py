#!/usr/bin/env python3
"""Extract the frozen champion and best founder into one-genome run packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_packet(path: Path, source: Path, role: str, genome: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "4.0",
        "artifact_type": "experiment-04-finalist-run-packet",
        "role": role,
        "source_champion_freeze": source.name,
        "source_champion_freeze_sha256": sha256(source),
        "population": [genome],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--champion-output", type=Path, required=True)
    parser.add_argument("--founder-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.freeze.resolve()
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("schema_version") != "experiment-04-champion-freeze-v1":
            raise ValueError("unexpected champion freeze schema")
        champion = document["champion_genome"]
        founder = document["best_founder_genome"]
        if not isinstance(champion, dict) or not isinstance(founder, dict):
            raise ValueError("champion freeze lacks finalist genomes")
        write_packet(args.champion_output, source, "evolved_champion", champion)
        write_packet(args.founder_output, source, "best_initial_founder", founder)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"champion": str(args.champion_output), "founder": str(args.founder_output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
