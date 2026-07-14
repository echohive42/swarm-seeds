#!/usr/bin/env python3
"""Prepare a holdout refinement from combined verified-candidate support."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from prepare_visible_holdout_jobs import (
    MODEL,
    PUBLIC_LABEL,
    REASONING_EFFORT,
    SCHEMA_VERSION,
    SERVICE_TIER,
    PreparationError,
    canonical_answer,
    canonical_bytes,
    load,
    output_schema,
    render_prompt,
    safe_job_id,
    sha256_bytes,
    sha256_file,
    write_json,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, action="append", required=True)
    parser.add_argument("--source-holdout", type=Path, action="append", required=True)
    parser.add_argument("--source-runner", type=Path, action="append", required=True)
    parser.add_argument("--block", type=Path, action="append", required=True)
    parser.add_argument("--prompt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--maximum-support", type=int, default=3)
    parser.add_argument("--route-cap", type=int, default=10)
    parser.add_argument("--phase", default="visible-holdout-refinement-01")
    args = parser.parse_args()

    if not (
        len(args.source_manifest)
        == len(args.source_holdout)
        == len(args.source_runner)
    ):
        raise PreparationError("source manifest, holdout, and runner counts must match")
    if not 0 <= args.maximum_support <= 32:
        raise PreparationError("maximum support must be between zero and 32")

    all_case_ids: set[str] = set()
    verified_answers: defaultdict[str, list[tuple[str, ...]]] = defaultdict(list)
    source_hashes: list[dict[str, str]] = []
    for manifest_path, holdout_path, runner_dir in zip(
        args.source_manifest, args.source_holdout, args.source_runner
    ):
        manifest = load(manifest_path)
        jobs = manifest.get("jobs")
        keys = load(holdout_path).get("rows")
        if not isinstance(jobs, list) or not isinstance(keys, list):
            raise PreparationError("invalid source stage artifacts")
        job_index = {job["job_id"]: job for job in jobs}
        key_index = {row["job_id"]: row for row in keys}
        if len(job_index) != len(jobs) or set(job_index) != set(key_index):
            raise PreparationError("source job and holdout IDs do not align")
        for job_id, job in job_index.items():
            key = key_index[job_id]
            case_id = key["case_id"]
            all_case_ids.add(case_id)
            result_path = runner_dir / "jobs" / job_id / "result.json"
            if not result_path.is_file():
                raise PreparationError(f"missing source result for {job_id}")
            result = load(result_path)
            if result.get("outcome") != "valid_output":
                raise PreparationError(f"non-valid source result for {job_id}")
            document = result.get("document")
            items = document.get("results") if isinstance(document, dict) else None
            if (
                document.get("block_id") != job["expected_block_id"]
                or not isinstance(items, list)
                or len(items) != 1
            ):
                raise PreparationError(f"source identity mismatch for {job_id}")
            holdout_terms = int(key["holdout_terms"])
            answer = canonical_answer(items[0].get("answer"), holdout_terms + 5)
            if answer[:holdout_terms] == tuple(key["visible_holdout"]):
                verified_answers[case_id].append(answer[holdout_terms:])
        source_hashes.append(
            {
                "manifest": sha256_file(manifest_path),
                "holdout": sha256_file(holdout_path),
                "attempt_ledger": sha256_file(runner_dir / "attempts.jsonl"),
            }
        )

    route_candidates: list[dict[str, Any]] = []
    for case_id in sorted(all_case_ids):
        counts = Counter(verified_answers.get(case_id, []))
        maximum = max(counts.values(), default=0)
        if maximum <= args.maximum_support:
            route_candidates.append(
                {
                    "case_id": case_id,
                    "verified_survivor_count": sum(counts.values()),
                    "unique_verified_answers": len(counts),
                    "maximum_verified_support": maximum,
                }
            )
    route_candidates.sort(
        key=lambda row: (
            row["maximum_verified_support"],
            row["verified_survivor_count"],
            -row["unique_verified_answers"],
            row["case_id"],
        )
    )
    selected = route_candidates[: args.route_cap]

    public_cases: dict[str, dict[str, Any]] = {}
    source_blocks: list[str] = []
    for path in args.block:
        block = load(path)
        source_blocks.append(block["block_id"])
        for case in block["cases"]:
            if case["case_id"] in public_cases:
                raise PreparationError(f"duplicate public case {case['case_id']}")
            public_cases[case["case_id"]] = case
    if any(row["case_id"] not in public_cases for row in selected):
        raise PreparationError("a selected case is absent from public blocks")

    common_path = args.prompt_dir / "COMMON_PREFIX.txt"
    lenses_path = args.prompt_dir / "LENSES.json"
    common = common_path.read_text(encoding="utf-8")
    lens_document = load(lenses_path)
    lenses = lens_document.get("lenses")
    if (
        lens_document.get("schema_version") != SCHEMA_VERSION
        or not isinstance(lenses, list)
        or len(lenses) != 8
    ):
        raise PreparationError("refinement catalog must contain eight lenses")
    lens_ids = [lens.get("lens_id") for lens in lenses if isinstance(lens, dict)]
    if len(lens_ids) != 8 or len(set(lens_ids)) != 8:
        raise PreparationError("refinement lens IDs must be unique")
    if any(
        lens.get("holdout_terms") != 1 or not isinstance(lens.get("instruction"), str)
        for lens in lenses
    ):
        raise PreparationError("all refinement lenses must use a one-term holdout")

    configuration = {
        "phase": args.phase,
        "maximum_support": args.maximum_support,
        "route_cap": args.route_cap,
        "selected": selected,
        "lenses": lenses,
        "source_hashes": source_hashes,
        "common_prefix_sha256": sha256_file(common_path),
        "lens_catalog_sha256": sha256_file(lenses_path),
    }
    strategy_sha256 = sha256_bytes(canonical_bytes(configuration))

    jobs: list[dict[str, Any]] = []
    holdout_rows: list[dict[str, Any]] = []
    for route_index, route_row in enumerate(selected, 1):
        case_id = route_row["case_id"]
        full_prefix = list(public_cases[case_id]["prefix"])
        for lens_index, lens in enumerate(lenses, 1):
            shortened = full_prefix[:-1]
            block_id = f"worksheet-{case_id.lower()}-h1"
            job_id = safe_job_id((args.phase, case_id, lens["lens_id"]))
            prompt = render_prompt(
                common=common,
                lens=lens,
                block_id=block_id,
                case_id=case_id,
                prefix=shortened,
            )
            write_text(args.output_dir / "prompts" / f"{job_id}.txt", prompt)
            jobs.append(
                {
                    "job_id": job_id,
                    "phase": args.phase,
                    "method": "Externally Verified Structural Worksheets",
                    "strategy_id": "VH03",
                    "strategy_sha256": strategy_sha256,
                    "category": "visible_holdout_refinement",
                    "block_id": block_id,
                    "role": "proposer",
                    "stage": "worksheet_solve",
                    "stage_id": "worksheet_solve",
                    "stage_index": 0,
                    "call_index": (route_index - 1) * len(lenses) + lens_index,
                    "role_index": lens_index,
                    "slot": f"W{lens_index:02d}",
                    "lens_id": lens["lens_id"],
                    "scope": "all",
                    "prompt": prompt,
                    "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "output_schema": output_schema(6),
                    "dependency_ids": [],
                    "expected_block_id": block_id,
                    "expected_case_ids": [case_id],
                }
            )
            holdout_rows.append(
                {
                    "job_id": job_id,
                    "case_id": case_id,
                    "lens_id": lens["lens_id"],
                    "holdout_terms": 1,
                    "visible_holdout": full_prefix[-1:],
                    "shortened_prefix_length": len(shortened),
                    "full_prefix_length": len(full_prefix),
                }
            )

    route_manifest = {
        "schema_version": "5.2-exploration",
        "artifact_type": "combined-verified-support-route",
        "phase": args.phase,
        "selection_rule": (
            f"Route cases whose most-supported externally verified future tuple has support at most "
            f"{args.maximum_support} across all source stages."
        ),
        "ranking_rule": "maximum support ascending, total survivors ascending, unique answers descending, case_id ascending",
        "route_cap": args.route_cap,
        "candidate_count": len(route_candidates),
        "selected_count": len(selected),
        "selected": selected,
        "uses_benchmark_answers": False,
        "source_blocks": source_blocks,
        "source_hashes": source_hashes,
    }
    holdout_truth = {
        "schema_version": "5.2-exploration",
        "artifact_type": "visible-holdout-refinement-public-term-key",
        "phase": args.phase,
        "note": "Removed public terms. Never included in subject prompts or runner manifest.",
        "rows": holdout_rows,
    }
    job_manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-05-job-manifest",
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "public_condition_label": PUBLIC_LABEL,
        "service_tier": SERVICE_TIER,
        "stage_index": 0,
        "jobs": jobs,
    }
    write_json(args.output_dir / "routing.json", route_manifest)
    write_json(args.output_dir / "holdout_truth.json", holdout_truth)
    write_json(args.output_dir / "manifest.json", job_manifest)
    write_json(
        args.output_dir / "preparation_summary.json",
        {
            "schema_version": "5.2-exploration",
            "artifact_type": "verified-support-refinement-preparation-summary",
            "phase": args.phase,
            "selected_cases": len(selected),
            "lenses_per_case": len(lenses),
            "logical_jobs": len(jobs),
            "strategy_sha256": strategy_sha256,
            "route_manifest_sha256": sha256_bytes(canonical_bytes(route_manifest)),
            "holdout_truth_sha256": sha256_bytes(canonical_bytes(holdout_truth)),
            "job_manifest_sha256": sha256_bytes(canonical_bytes(job_manifest)),
        },
    )
    print(
        json.dumps(
            {
                "selected_cases": len(selected),
                "logical_jobs": len(jobs),
                "selected_case_ids": [row["case_id"] for row in selected],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
