#!/usr/bin/env python3
"""Merge valid exact-job retries into a complete result set without altering source runs."""

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
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-runner", type=Path, required=True)
    parser.add_argument("--retry-runner", type=Path, required=True)
    parser.add_argument("--output-run", type=Path, required=True)
    args = parser.parse_args()

    manifest = load(args.manifest)
    jobs = manifest["jobs"]
    output_manifest = args.output_run / "manifests" / args.manifest.name
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.manifest, output_manifest)

    replacements = []
    selected = []
    for job in jobs:
        job_id = job["job_id"]
        base_path = args.base_runner / "jobs" / job_id / "result.json"
        retry_path = args.retry_runner / "jobs" / job_id / "result.json"
        base = load(base_path) if base_path.is_file() else {}
        retry = load(retry_path) if retry_path.is_file() else {}
        if base.get("outcome") == "valid_output":
            source = base_path
            source_kind = "base"
        elif retry.get("outcome") == "valid_output":
            source = retry_path
            source_kind = "retry"
            replacements.append(job_id)
        else:
            raise RuntimeError(f"no valid base or retry result for {job_id}")
        destination = args.output_run / "runner" / "jobs" / job_id / "result.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        selected.append({
            "job_id": job_id,
            "source": source_kind,
            "source_sha256": sha256(source),
            "merged_result_sha256": sha256(destination),
        })

    merge_record = {
        "schema_version": "5.1-exploration",
        "artifact_type": "exact-job-retry-merge",
        "job_count": len(jobs),
        "base_jobs": len(jobs) - len(replacements),
        "retry_jobs": len(replacements),
        "replacement_job_ids": replacements,
        "manifest_sha256": sha256(args.manifest),
        "jobs": selected,
    }
    write_json(args.output_run / "retry_merge.json", merge_record)
    print(json.dumps({"jobs": len(jobs), "base": len(jobs) - len(replacements), "retries": len(replacements)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
