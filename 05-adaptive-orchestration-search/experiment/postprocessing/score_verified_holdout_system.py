#!/usr/bin/env python3
"""Score the frozen base-plus-verified-holdout orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


INTEGER_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")


class ScoringError(RuntimeError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


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


def canonical_answer(value: Any, expected: int) -> tuple[str, ...]:
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
        raise ScoringError(f"invalid {expected}-term canonical answer")
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


def plurality(rows: Iterable[dict[str, Any]], answer_key: str) -> tuple[str, ...]:
    counts: Counter[tuple[str, ...]] = Counter()
    confidence_sums: defaultdict[tuple[str, ...], float] = defaultdict(float)
    for row in rows:
        answer = canonical_answer(row.get(answer_key), 5)
        counts[answer] += 1
        confidence_sums[answer] += confidence(row)
    if not counts:
        raise ScoringError("cannot select from an empty candidate set")
    return min(
        counts,
        key=lambda answer: (
            -counts[answer],
            -(confidence_sums[answer] / counts[answer]),
            answer,
        ),
    )


def load_verified_candidates(
    manifest_path: Path, holdout_path: Path, runner_dir: Path, stage_index: int
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifest = load(manifest_path)
    jobs = manifest.get("jobs")
    keys = load(holdout_path).get("rows")
    if not isinstance(jobs, list) or not isinstance(keys, list):
        raise ScoringError("invalid holdout source artifacts")
    job_index = {job["job_id"]: job for job in jobs}
    key_index = {row["job_id"]: row for row in keys}
    if len(job_index) != len(jobs) or set(job_index) != set(key_index):
        raise ScoringError("holdout source job IDs do not align")

    rows: list[dict[str, Any]] = []
    for job_id, job in job_index.items():
        key = key_index[job_id]
        result_path = runner_dir / "jobs" / job_id / "result.json"
        if not result_path.is_file():
            raise ScoringError(f"missing result for {job_id}")
        result = load(result_path)
        if result.get("outcome") != "valid_output":
            raise ScoringError(f"non-valid result for {job_id}")
        document = result.get("document")
        items = document.get("results") if isinstance(document, dict) else None
        if (
            document.get("block_id") != job["expected_block_id"]
            or not isinstance(items, list)
            or len(items) != 1
            or items[0].get("case_id") != key["case_id"]
        ):
            raise ScoringError(f"result identity mismatch for {job_id}")
        holdout_terms = int(key["holdout_terms"])
        answer = canonical_answer(items[0].get("answer"), holdout_terms + 5)
        if answer[:holdout_terms] != tuple(key["visible_holdout"]):
            continue
        rows.append(
            {
                "case_id": key["case_id"],
                "future_answer": list(answer[holdout_terms:]),
                "confidence": items[0].get("confidence", 0.0),
                "lens_id": key["lens_id"],
                "holdout_terms": holdout_terms,
                "source_stage": stage_index,
                "job_id": job_id,
            }
        )
    return rows, {
        "manifest": sha256(manifest_path),
        "holdout": sha256(holdout_path),
        "attempt_ledger": sha256(runner_dir / "attempts.jsonl"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-predictions", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, action="append", required=True)
    parser.add_argument("--source-holdout", type=Path, action="append", required=True)
    parser.add_argument("--source-runner", type=Path, action="append", required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not (
        len(args.source_manifest)
        == len(args.source_holdout)
        == len(args.source_runner)
        == 3
    ):
        raise ScoringError("the frozen system requires exactly three holdout stages")

    truth_rows = load_jsonl(args.answers)
    truth = {row["case_id"]: tuple(row["next"]) for row in truth_rows}
    metadata = {row["case_id"]: row for row in truth_rows}

    base_document = load(args.base_predictions)
    base_by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    block_by_case: dict[str, str] = {}
    for row in base_document.get("records", []):
        if row.get("is_final_output"):
            continue
        answer = canonical_answer(row.get("answer"), 5)
        base_by_case[row["case_id"]].append({**row, "answer": list(answer)})
        block_by_case[row["case_id"]] = row["block_id"]
    if len(base_by_case) != 24 or any(len(rows) != 15 for rows in base_by_case.values()):
        raise ScoringError("expected a complete 15-by-24 base panel")
    base_final = {
        case_id: plurality(rows, "answer") for case_id, rows in base_by_case.items()
    }

    candidates: list[dict[str, Any]] = []
    source_hashes: list[dict[str, str]] = []
    for stage_index, (manifest, holdout, runner) in enumerate(
        zip(args.source_manifest, args.source_holdout, args.source_runner), 1
    ):
        rows, hashes = load_verified_candidates(manifest, holdout, runner, stage_index)
        if any(row["case_id"] not in base_by_case for row in rows):
            raise ScoringError("holdout source contains a non-base case")
        candidates.extend(rows)
        source_hashes.append(hashes)

    candidates_by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        candidates_by_case[row["case_id"]].append(row)
    final = dict(base_final)
    for case_id, rows in candidates_by_case.items():
        final[case_id] = plurality(rows, "future_answer")

    cases = sorted(base_by_case)
    exact = sum(final[case_id] == truth[case_id] for case_id in cases)
    base_exact = sum(base_final[case_id] == truth[case_id] for case_id in cases)
    terms = sum(
        sum(left == right for left, right in zip(final[case_id], truth[case_id]))
        for case_id in cases
    )
    useful = sum(
        base_final[case_id] != truth[case_id] and final[case_id] == truth[case_id]
        for case_id in cases
    )
    harmful = sum(
        base_final[case_id] == truth[case_id] and final[case_id] != truth[case_id]
        for case_id in cases
    )
    oracle = sum(
        base_final[case_id] == truth[case_id]
        or truth[case_id]
        in {
            canonical_answer(row["future_answer"], 5)
            for row in candidates_by_case.get(case_id, [])
        }
        for case_id in cases
    )

    panel_exact: defaultdict[str, int] = defaultdict(int)
    family_exact: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"exact": 0, "cases": 0}
    )
    case_decisions: dict[str, Any] = {}
    for case_id in cases:
        block_id = block_by_case[case_id]
        parent = block_id[:-1] if block_id.endswith(("a", "b")) else block_id
        panel_exact[parent] += int(final[case_id] == truth[case_id])
        family = metadata[case_id]["family"]
        family_exact[family]["cases"] += 1
        family_exact[family]["exact"] += int(final[case_id] == truth[case_id])
        candidate_counts = Counter(
            canonical_answer(row["future_answer"], 5)
            for row in candidates_by_case.get(case_id, [])
        )
        case_decisions[case_id] = {
            "family": family,
            "base_answer": list(base_final[case_id]),
            "final_answer": list(final[case_id]),
            "truth": list(truth[case_id]),
            "base_exact": base_final[case_id] == truth[case_id],
            "final_exact": final[case_id] == truth[case_id],
            "verified_candidate_count": sum(candidate_counts.values()),
            "unique_verified_candidates": len(candidate_counts),
            "winning_verified_support": candidate_counts.get(final[case_id], 0),
            "override": final[case_id] != base_final[case_id],
        }

    result = {
        "schema_version": "5.2-exploration",
        "artifact_type": "verified-holdout-frozen-system-score",
        "status": "target_reached" if exact / len(cases) >= 0.8 else "target_not_reached",
        "registered_system": {
            "exact": exact,
            "cases": len(cases),
            "exact_accuracy": exact / len(cases),
            "correct_terms": terms,
            "terms": 5 * len(cases),
            "term_accuracy": terms / (5 * len(cases)),
        },
        "base_fifteen": {
            "exact": base_exact,
            "cases": len(cases),
            "exact_accuracy": base_exact / len(cases),
        },
        "verified_selection": {
            "candidate_count": len(candidates),
            "cases_with_verified_candidates": len(candidates_by_case),
            "useful_overrides": useful,
            "harmful_overrides": harmful,
            "selector": "support descending, mean reported confidence descending, canonical tuple ascending",
        },
        "candidate_oracle_including_base": {
            "exact": oracle,
            "cases": len(cases),
            "exact_accuracy": oracle / len(cases),
        },
        "panel_exact": dict(sorted(panel_exact.items())),
        "family_exact": dict(sorted(family_exact.items())),
        "case_decisions": case_decisions,
        "sha256": {
            "base_predictions": sha256(args.base_predictions),
            "answers": sha256(args.answers),
            "sources": source_hashes,
        },
    }
    write_json(args.output, result)
    print(json.dumps(result["registered_system"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
