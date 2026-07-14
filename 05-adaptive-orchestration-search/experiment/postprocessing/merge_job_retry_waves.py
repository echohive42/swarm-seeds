#!/usr/bin/env python3
"""Merge valid exact-job retry waves without modifying any source run."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-runner", type=Path, required=True)
    parser.add_argument(
        "--retry-runner", type=Path, action="append", required=True
    )
    parser.add_argument("--output-run", type=Path, required=True)
    args = parser.parse_args()

    manifest = load(args.manifest)
    jobs = manifest["jobs"]
    output_manifest = args.output_run / "manifests" / args.manifest.name
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.manifest, output_manifest)

    selected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {"base": 0}
    replacements: list[str] = []
    for job in jobs:
        job_id = job["job_id"]
        candidates = [
            ("base", args.base_runner / "jobs" / job_id / "result.json")
        ]
        candidates.extend(
            (f"retry_{index}", runner / "jobs" / job_id / "result.json")
            for index, runner in enumerate(args.retry_runner, start=1)
        )
        source_kind = ""
        source_path: Path | None = None
        for kind, path in candidates:
            result = load(path) if path.is_file() else {}
            if result.get("outcome") == "valid_output":
                source_kind, source_path = kind, path
                break
        if source_path is None:
            raise RuntimeError(f"no valid base or retry result for {job_id}")

        destination = args.output_run / "runner" / "jobs" / job_id / "result.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        source_counts[source_kind] = source_counts.get(source_kind, 0) + 1
        if source_kind != "base":
            replacements.append(job_id)
        selected.append(
            {
                "job_id": job_id,
                "source": source_kind,
                "source_sha256": sha256(source_path),
                "merged_result_sha256": sha256(destination),
            }
        )

    merge_record = {
        "schema_version": "5.1-validation",
        "artifact_type": "exact-job-retry-wave-merge",
        "job_count": len(jobs),
        "source_counts": source_counts,
        "replacement_job_ids": replacements,
        "manifest_sha256": sha256(args.manifest),
        "jobs": selected,
    }
    write_json(args.output_run / "retry_merge.json", merge_record)
    print(
        json.dumps(
            {
                "jobs": len(jobs),
                "replacements": len(replacements),
                "source_counts": source_counts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
