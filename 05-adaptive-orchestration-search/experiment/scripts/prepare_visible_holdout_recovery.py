#!/usr/bin/env python3
"""Prepare a second holdout generation from answer-independent survivor counts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
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
    parser.add_argument("--stage-one-manifest", type=Path, required=True)
    parser.add_argument("--stage-one-holdout", type=Path, required=True)
    parser.add_argument("--stage-one-runner", type=Path, required=True)
    parser.add_argument("--block", type=Path, action="append", required=True)
    parser.add_argument("--prompt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--survivor-threshold", type=int, default=3)
    parser.add_argument("--route-cap", type=int, default=8)
    parser.add_argument("--phase", default="visible-holdout-recovery-01")
    args = parser.parse_args()

    if not 0 <= args.survivor_threshold <= 8:
        raise PreparationError("survivor threshold must be from zero through eight")
    if not 1 <= args.route_cap <= 24:
        raise PreparationError("route cap must be from one through 24")

    stage_one_manifest = load(args.stage_one_manifest)
    stage_one_jobs = stage_one_manifest.get("jobs")
    stage_one_holdout = load(args.stage_one_holdout).get("rows")
    if not isinstance(stage_one_jobs, list) or not isinstance(stage_one_holdout, list):
        raise PreparationError("invalid stage-one artifacts")
    jobs_by_id = {row["job_id"]: row for row in stage_one_jobs}
    key_by_id = {row["job_id"]: row for row in stage_one_holdout}
    if len(jobs_by_id) != len(stage_one_jobs) or set(jobs_by_id) != set(key_by_id):
        raise PreparationError("stage-one job and holdout IDs do not align")

    survivor_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    case_job_counts: defaultdict[str, int] = defaultdict(int)
    for job_id, job in jobs_by_id.items():
        key = key_by_id[job_id]
        case_id = key["case_id"]
        case_job_counts[case_id] += 1
        result_path = args.stage_one_runner / "jobs" / job_id / "result.json"
        if not result_path.is_file():
            raise PreparationError(f"missing stage-one result for {job_id}")
        result = load(result_path)
        if result.get("outcome") != "valid_output":
            raise PreparationError(f"stage-one result is not valid for {job_id}")
        document = result.get("document")
        items = document.get("results") if isinstance(document, dict) else None
        if (
            document.get("block_id") != job["expected_block_id"]
            or not isinstance(items, list)
            or len(items) != 1
        ):
            raise PreparationError(f"stage-one identity mismatch for {job_id}")
        holdout_terms = int(key["holdout_terms"])
        answer = canonical_answer(items[0].get("answer"), holdout_terms + 5)
        if answer[:holdout_terms] == tuple(key["visible_holdout"]):
            survivor_rows[case_id].append(
                {
                    "future_answer": list(answer[holdout_terms:]),
                    "holdout_terms": holdout_terms,
                    "lens_id": key["lens_id"],
                }
            )
    if any(count != 8 for count in case_job_counts.values()):
        raise PreparationError("each stage-one case must have eight jobs")

    route_candidates: list[dict[str, Any]] = []
    for case_id in sorted(case_job_counts):
        survivors = survivor_rows.get(case_id, [])
        survivor_count = len(survivors)
        if survivor_count <= args.survivor_threshold:
            route_candidates.append(
                {
                    "case_id": case_id,
                    "survivor_count": survivor_count,
                    "unique_surviving_answers": len(
                        {tuple(row["future_answer"]) for row in survivors}
                    ),
                    "longest_surviving_holdout": max(
                        (row["holdout_terms"] for row in survivors), default=0
                    ),
                }
            )
    route_candidates.sort(
        key=lambda row: (
            row["survivor_count"],
            -row["unique_surviving_answers"],
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
        raise PreparationError("recovery catalog must contain eight lenses")
    lens_ids = [lens.get("lens_id") for lens in lenses if isinstance(lens, dict)]
    if len(lens_ids) != 8 or len(set(lens_ids)) != 8:
        raise PreparationError("recovery lens IDs must be unique")
    for lens in lenses:
        if lens.get("holdout_terms") not in (1, 2) or not isinstance(
            lens.get("instruction"), str
        ):
            raise PreparationError("each recovery lens needs a one- or two-term holdout")

    configuration = {
        "phase": args.phase,
        "survivor_threshold": args.survivor_threshold,
        "route_cap": args.route_cap,
        "selected": selected,
        "lenses": lenses,
        "stage_one_manifest_sha256": sha256_file(args.stage_one_manifest),
        "stage_one_holdout_sha256": sha256_file(args.stage_one_holdout),
        "stage_one_attempt_ledger_sha256": sha256_file(
            args.stage_one_runner / "attempts.jsonl"
        ),
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
            holdout_terms = int(lens["holdout_terms"])
            shortened = full_prefix[:-holdout_terms]
            visible_holdout = full_prefix[-holdout_terms:]
            block_id = f"recovery-{case_id.lower()}-h{holdout_terms}"
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
                    "method": "Visible Holdout Failure Recovery",
                    "strategy_id": "VH02",
                    "strategy_sha256": strategy_sha256,
                    "category": "visible_holdout_recovery",
                    "block_id": block_id,
                    "role": "proposer",
                    "stage": "recovery_solve",
                    "stage_id": "recovery_solve",
                    "stage_index": 0,
                    "call_index": (route_index - 1) * len(lenses) + lens_index,
                    "role_index": lens_index,
                    "slot": f"R{lens_index:02d}",
                    "lens_id": lens["lens_id"],
                    "scope": "all",
                    "prompt": prompt,
                    "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "output_schema": output_schema(holdout_terms + 5),
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
                    "holdout_terms": holdout_terms,
                    "visible_holdout": visible_holdout,
                    "shortened_prefix_length": len(shortened),
                    "full_prefix_length": len(full_prefix),
                }
            )

    route_manifest = {
        "schema_version": "5.2-exploration",
        "artifact_type": "visible-holdout-survivor-count-route",
        "phase": args.phase,
        "selection_rule": (
            f"Route cases with at most {args.survivor_threshold} candidates that exactly "
            "recovered their own stage-one visible holdout."
        ),
        "ranking_rule": "survivor count ascending, unique surviving answers descending, case_id ascending",
        "route_cap": args.route_cap,
        "candidate_count": len(route_candidates),
        "selected_count": len(selected),
        "selected": selected,
        "uses_benchmark_answers": False,
        "source_blocks": source_blocks,
        "stage_one_manifest_sha256": sha256_file(args.stage_one_manifest),
        "stage_one_holdout_sha256": sha256_file(args.stage_one_holdout),
        "stage_one_attempt_ledger_sha256": sha256_file(
            args.stage_one_runner / "attempts.jsonl"
        ),
    }
    holdout_truth = {
        "schema_version": "5.2-exploration",
        "artifact_type": "visible-holdout-recovery-public-term-key",
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
            "artifact_type": "visible-holdout-recovery-preparation-summary",
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
