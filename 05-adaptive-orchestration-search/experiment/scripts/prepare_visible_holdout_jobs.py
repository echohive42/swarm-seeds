#!/usr/bin/env python3
"""Prepare answer-independent visible-holdout jobs for Experiment 05."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "5.0"
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"
PUBLIC_LABEL = "Light reasoning"
SERVICE_TIER = "standard"
INTEGER_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")


class PreparationError(RuntimeError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def canonical_answer(value: Any, expected: int = 5) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) != expected
        or any(
            not isinstance(item, str)
            or INTEGER_RE.fullmatch(item) is None
            or item == "-0"
            for item in value
        )
    ):
        raise PreparationError("invalid canonical answer")
    return tuple(value)


def confidence(row: dict[str, Any]) -> float:
    value = row.get("confidence", 0.0)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return min(1.0, max(0.0, float(value)))
    return 0.0


def plurality(rows: Iterable[dict[str, Any]]) -> tuple[tuple[str, ...], int, int, float]:
    counts: Counter[tuple[str, ...]] = Counter()
    confidence_sums: defaultdict[tuple[str, ...], float] = defaultdict(float)
    row_count = 0
    for row in rows:
        if row.get("format_valid") is False:
            continue
        answer = canonical_answer(row.get("answer"))
        counts[answer] += 1
        confidence_sums[answer] += confidence(row)
        row_count += 1
    if not counts:
        raise PreparationError("cannot route an empty prediction panel")
    winner = min(
        counts,
        key=lambda answer: (
            -counts[answer],
            -(confidence_sums[answer] / counts[answer]),
            answer,
        ),
    )
    mean_confidence = sum(confidence_sums.values()) / row_count
    return winner, counts[winner], len(counts), mean_confidence


def output_schema(answer_terms: int) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Swarm Seeds 05 visible-holdout continuation",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "block_id", "results"],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "block_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "case_id",
                        "answer",
                        "confidence",
                        "rule_summary",
                        "check_summary",
                    ],
                    "properties": {
                        "case_id": {"type": "string", "minLength": 1, "maxLength": 80},
                        "answer": {
                            "type": "array",
                            "minItems": answer_terms,
                            "maxItems": answer_terms,
                            "items": {
                                "type": "string",
                                "pattern": "^(0|-?[1-9][0-9]*)$",
                            },
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rule_summary": {"type": "string", "maxLength": 220},
                        "check_summary": {"type": "string", "maxLength": 180},
                    },
                },
            },
        },
    }


def render_prompt(
    *,
    common: str,
    lens: dict[str, Any],
    block_id: str,
    case_id: str,
    prefix: list[str],
) -> str:
    holdout_terms = int(lens["holdout_terms"])
    answer_terms = holdout_terms + 5
    example = [f'"term{index}"' for index in range(1, answer_terms + 1)]
    task = {
        "schema_version": "5.2-exploration",
        "experiment_id": "swarm-seeds-05-visible-holdout",
        "block_id": block_id,
        "cases": [{"case_id": case_id, "prefix": prefix}],
        "requested_continuation_terms": answer_terms,
    }
    return (
        common.strip()
        + "\n\nSPECIAL ASSIGNMENT\n"
        + str(lens["instruction"]).strip()
        + f"\n\nPredict exactly the next {answer_terms} terms. "
        + f"The first {holdout_terms} predictions will be checked against terms withheld from you, "
        + "and the remaining five are the forecast under evaluation.\n\n"
        + "TASK BLOCK JSON\n"
        + canonical_bytes(task).decode("utf-8")
        + "\n\nUse this exact output shape:\n"
        + "{\n"
        + '  "schema_version": "5.0",\n'
        + f'  "block_id": "{block_id}",\n'
        + '  "results": [\n'
        + "    {\n"
        + f'      "case_id": "{case_id}",\n'
        + '      "answer": [' + ", ".join(example) + "],\n"
        + '      "confidence": 0.0,\n'
        + '      "rule_summary": "concise reproducible rule",\n'
        + '      "check_summary": "concise supplied-prefix check"\n'
        + "    }\n"
        + "  ]\n"
        + "}\n\nReturn the required JSON object now.\n"
    )


def safe_job_id(parts: Iterable[Any]) -> str:
    raw = "-".join(str(part) for part in parts)
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", raw).strip("-.") or "job"
    if len(safe) <= 100:
        return safe
    return safe[:83] + "-" + sha256_bytes(safe.encode("utf-8"))[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-predictions", type=Path, required=True)
    parser.add_argument("--block", type=Path, action="append", required=True)
    parser.add_argument("--prompt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--support-threshold", type=int, default=5)
    parser.add_argument("--route-cap", type=int, default=16)
    parser.add_argument("--phase", default="visible-holdout-01")
    args = parser.parse_args()

    if not 1 <= args.support_threshold <= 15:
        raise PreparationError("support threshold must be between 1 and 15")
    if not 1 <= args.route_cap <= 24:
        raise PreparationError("route cap must be between 1 and 24")

    base_document = load(args.base_predictions)
    base_rows = [
        row for row in base_document.get("records", []) if not row.get("is_final_output")
    ]
    by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_rows:
        by_case[row["case_id"]].append(row)
    if len(by_case) != 24 or any(len(rows) != 15 for rows in by_case.values()):
        raise PreparationError("expected a complete 15-by-24 base prediction panel")

    public_cases: dict[str, dict[str, Any]] = {}
    source_blocks: list[str] = []
    for path in args.block:
        block = load(path)
        source_blocks.append(block["block_id"])
        for case in block["cases"]:
            case_id = case["case_id"]
            if case_id in public_cases:
                raise PreparationError(f"duplicate public case {case_id}")
            public_cases[case_id] = case
    if set(public_cases) != set(by_case):
        raise PreparationError("public cases and base prediction cases do not match")

    route_candidates: list[dict[str, Any]] = []
    for case_id, rows in by_case.items():
        winner, support, unique_answers, mean_confidence = plurality(rows)
        if support <= args.support_threshold:
            route_candidates.append(
                {
                    "case_id": case_id,
                    "base_answer": list(winner),
                    "plurality_support": support,
                    "unique_answers": unique_answers,
                    "mean_confidence": mean_confidence,
                }
            )
    route_candidates.sort(
        key=lambda row: (
            row["plurality_support"],
            -row["unique_answers"],
            row["mean_confidence"],
            row["case_id"],
        )
    )
    selected = route_candidates[: args.route_cap]

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
        raise PreparationError("visible-holdout catalog must contain eight lenses")
    lens_ids = [lens.get("lens_id") for lens in lenses if isinstance(lens, dict)]
    if len(lens_ids) != 8 or len(set(lens_ids)) != 8:
        raise PreparationError("visible-holdout lens IDs must be unique")
    for lens in lenses:
        if lens.get("holdout_terms") not in (2, 3) or not isinstance(
            lens.get("instruction"), str
        ):
            raise PreparationError("each lens needs a two- or three-term holdout")

    configuration = {
        "phase": args.phase,
        "support_threshold": args.support_threshold,
        "route_cap": args.route_cap,
        "selected_case_ids": [row["case_id"] for row in selected],
        "lenses": lenses,
        "base_predictions_sha256": sha256_file(args.base_predictions),
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
            if len(full_prefix) <= holdout_terms + 5:
                raise PreparationError(f"prefix too short for holdout on {case_id}")
            shortened = full_prefix[:-holdout_terms]
            visible_holdout = full_prefix[-holdout_terms:]
            block_id = f"holdout-{case_id.lower()}-h{holdout_terms}"
            job_id = safe_job_id((args.phase, case_id, lens["lens_id"]))
            prompt = render_prompt(
                common=common,
                lens=lens,
                block_id=block_id,
                case_id=case_id,
                prefix=shortened,
            )
            prompt_path = args.output_dir / "prompts" / f"{job_id}.txt"
            write_text(prompt_path, prompt)
            jobs.append(
                {
                    "job_id": job_id,
                    "phase": args.phase,
                    "method": "Visible Holdout Rule Search",
                    "strategy_id": "VH01",
                    "strategy_sha256": strategy_sha256,
                    "category": "visible_holdout",
                    "block_id": block_id,
                    "role": "proposer",
                    "stage": "holdout_solve",
                    "stage_id": "holdout_solve",
                    "stage_index": 0,
                    "call_index": (route_index - 1) * len(lenses) + lens_index,
                    "role_index": lens_index,
                    "slot": f"H{lens_index:02d}",
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
        "artifact_type": "visible-holdout-answer-independent-route",
        "phase": args.phase,
        "selection_rule": (
            f"Route cases whose deterministic 15-prompt plurality support is at most "
            f"{args.support_threshold}; rank by support ascending, unique answers descending, "
            "mean confidence ascending, and case_id ascending."
        ),
        "route_cap": args.route_cap,
        "candidate_count": len(route_candidates),
        "selected_count": len(selected),
        "selected": selected,
        "uses_answers": False,
        "source_blocks": source_blocks,
        "base_predictions_sha256": sha256_file(args.base_predictions),
    }
    holdout_truth = {
        "schema_version": "5.2-exploration",
        "artifact_type": "visible-holdout-public-term-key",
        "phase": args.phase,
        "note": "These are terms removed from otherwise public prefixes. They are never included in subject prompts or the runner job manifest.",
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
            "artifact_type": "visible-holdout-preparation-summary",
            "phase": args.phase,
            "selected_cases": len(selected),
            "lenses_per_case": len(lenses),
            "logical_jobs": len(jobs),
            "holdout_two_jobs": sum(row["holdout_terms"] == 2 for row in holdout_rows),
            "holdout_three_jobs": sum(row["holdout_terms"] == 3 for row in holdout_rows),
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
