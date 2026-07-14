#!/usr/bin/env python3
"""Create or verify the pre-call Experiment 05 integrity manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent.parent
MANIFEST = ROOT / "freeze_manifest.json"
EXCLUDED_PARTS = {"runs", "results", "__pycache__"}
EXCLUDED_FILES = {"freeze_manifest.json"}
INCLUDED_ROOTS = (
    "PROTOCOL.md",
    "benchmark",
    "preflight",
    "prompts",
    "scripts",
    "strategies",
)
EXTERNAL_FILES = {
    "experiment_03_generator": REPOSITORY / "03-evolving-light-swarms" / "experiment" / "scripts" / "generate_benchmark.py",
    "experiment_03_runner": REPOSITORY / "03-evolving-light-swarms" / "experiment" / "scripts" / "run_jobs.py",
    "experiment_03_scorer": REPOSITORY / "03-evolving-light-swarms" / "experiment" / "scripts" / "score.py",
    "experiment_04_generator": REPOSITORY / "04-evolving-the-decider" / "experiment" / "scripts" / "generate_benchmark.py",
    "experiment_04_scorer": REPOSITORY / "04-evolving-the-decider" / "experiment" / "scripts" / "score.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_paths() -> list[Path]:
    paths: list[Path] = []
    for name in INCLUDED_ROOTS:
        candidate = ROOT / name
        if candidate.is_file():
            paths.append(candidate)
        elif candidate.is_dir():
            for path in candidate.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(ROOT)
                if path.name in EXCLUDED_FILES or any(
                    part in EXCLUDED_PARTS for part in relative.parts
                ):
                    continue
                paths.append(path)
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def snapshot() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in frozen_paths()}


def external_snapshot() -> dict[str, str]:
    missing = [str(path) for path in EXTERNAL_FILES.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"missing external dependency: {missing}")
    return {name: sha256(path) for name, path in EXTERNAL_FILES.items()}


def create() -> int:
    files = snapshot()
    if not files:
        raise SystemExit("refusing to create an empty freeze manifest")
    batch = json.loads((ROOT / "strategies" / "batch-01.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0",
        "experiment": "swarm-seeds-05",
        "freeze_scope": "pre-batch-01-subject-calls",
        "hash_algorithm": "sha256",
        "file_count": len(files),
        "files": files,
        "external_dependencies": external_snapshot(),
        "registered_batch_01_strategy_count": len(batch.get("strategies", [])),
        "requested_model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "public_reasoning_label": "Light reasoning",
        "service_tier": "standard",
        "maximum_concurrency": 60,
    }
    MANIFEST.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"frozen {len(files)} files -> {MANIFEST.relative_to(ROOT)}")
    return 0


def verify() -> int:
    if not MANIFEST.exists():
        raise SystemExit("freeze manifest does not exist")
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = payload.get("files")
    if not isinstance(expected, dict):
        raise SystemExit("freeze manifest has no files mapping")
    actual = snapshot()
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(
            path
            for path in set(actual) & set(expected)
            if actual[path] != expected[path]
        )
        print(json.dumps({"missing": missing, "added": added, "changed": changed}, indent=2))
        return 1
    if payload.get("file_count") != len(expected):
        raise SystemExit("freeze manifest file_count mismatch")
    actual_external = external_snapshot()
    if payload.get("external_dependencies") != actual_external:
        print(
            json.dumps(
                {
                    "external_dependency_mismatch": {
                        "expected": payload.get("external_dependencies"),
                        "actual": actual_external,
                    }
                },
                indent=2,
            )
        )
        return 1
    print(f"verified {len(actual)} frozen files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "verify"))
    args = parser.parse_args()
    return create() if args.command == "create" else verify()


if __name__ == "__main__":
    raise SystemExit(main())
