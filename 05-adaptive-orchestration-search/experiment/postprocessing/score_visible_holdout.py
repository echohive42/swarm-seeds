#!/usr/bin/env python3
"""Score visible-holdout candidates and deterministic selectors on open development cases."""

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


def plurality(
    rows: Iterable[dict[str, Any]], *, weight_key: str | None = None
) -> tuple[str, ...]:
    scores: defaultdict[tuple[str, ...], float] = defaultdict(float)
    counts: Counter[tuple[str, ...]] = Counter()
    confidence_sums: defaultdict[tuple[str, ...], float] = defaultdict(float)
    for row in rows:
        answer = tuple(row["future_answer"] if "future_answer" in row else row["answer"])
        weight = float(row.get(weight_key, 1.0)) if weight_key else 1.0
        scores[answer] += weight
        counts[answer] += 1
        confidence_sums[answer] += confidence(row)
    if not scores:
        raise ScoringError("cannot select from an empty row set")
    return min(
        scores,
        key=lambda answer: (
            -scores[answer],
            -counts[answer],
            -(confidence_sums[answer] / counts[answer]),
            answer,
        ),
    )


def policy_answer(
    policy: str, survivors: list[dict[str, Any]], base: tuple[str, ...]
) -> tuple[str, ...]:
    if not survivors:
        return base
    if policy == "any_survivor_plurality":
        return plurality(survivors)
    if policy == "longest_holdout_plurality":
        maximum = max(row["holdout_terms"] for row in survivors)
        return plurality(row for row in survivors if row["holdout_terms"] == maximum)
    if policy == "holdout_weighted_plurality":
        return plurality(survivors, weight_key="holdout_terms")
    if policy == "two_survivor_gate":
        return plurality(survivors) if len(survivors) >= 2 else base
    if policy == "cross_horizon_gate":
        horizons: defaultdict[tuple[str, ...], set[int]] = defaultdict(set)
        for row in survivors:
            horizons[tuple(row["future_answer"])].add(row["holdout_terms"])
        eligible = [
            row
            for row in survivors
            if horizons[tuple(row["future_answer"])] == {2, 3}
        ]
        return plurality(eligible) if eligible else base
    raise ScoringError(f"unknown policy {policy}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-predictions", type=Path, required=True)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--holdout-truth", type=Path, required=True)
    parser.add_argument("--runner-dir", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    truth_rows = load_jsonl(args.answers)
    truth = {row["case_id"]: tuple(row["next"]) for row in truth_rows}
    metadata = {row["case_id"]: row for row in truth_rows}

    base_document = load(args.base_predictions)
    base_by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_document.get("records", []):
        if not row.get("is_final_output"):
            answer = canonical_answer(row.get("answer"), 5)
            base_by_case[row["case_id"]].append(
                {**row, "answer": list(answer), "future_answer": list(answer)}
            )
    if len(base_by_case) != 24 or any(len(rows) != 15 for rows in base_by_case.values()):
        raise ScoringError("expected a complete 15-by-24 base panel")
    base_final = {case_id: plurality(rows) for case_id, rows in base_by_case.items()}

    job_manifest = load(args.job_manifest)
    jobs = job_manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ScoringError("job manifest contains no jobs")
    job_index = {job["job_id"]: job for job in jobs}
    if len(job_index) != len(jobs):
        raise ScoringError("duplicate job IDs")

    holdout_document = load(args.holdout_truth)
    holdout_rows = holdout_document.get("rows")
    if not isinstance(holdout_rows, list) or len(holdout_rows) != len(jobs):
        raise ScoringError("holdout key and job manifest do not align")
    holdout_index = {row["job_id"]: row for row in holdout_rows}
    if set(holdout_index) != set(job_index):
        raise ScoringError("holdout key job IDs do not match the job manifest")

    candidates: list[dict[str, Any]] = []
    for job_id, job in job_index.items():
        result_path = args.runner_dir / "jobs" / job_id / "result.json"
        if not result_path.is_file():
            raise ScoringError(f"missing terminal result for {job_id}")
        result = load(result_path)
        if result.get("outcome") != "valid_output":
            raise ScoringError(f"non-valid terminal result for {job_id}")
        document = result.get("document")
        if not isinstance(document, dict) or document.get("block_id") != job["expected_block_id"]:
            raise ScoringError(f"invalid document identity for {job_id}")
        items = document.get("results")
        if not isinstance(items, list) or len(items) != 1:
            raise ScoringError(f"invalid result count for {job_id}")
        item = items[0]
        key = holdout_index[job_id]
        holdout_terms = int(key["holdout_terms"])
        answer = canonical_answer(item.get("answer"), holdout_terms + 5)
        visible_holdout = tuple(key["visible_holdout"])
        survived = answer[:holdout_terms] == visible_holdout
        future = answer[holdout_terms:]
        candidates.append(
            {
                "job_id": job_id,
                "case_id": key["case_id"],
                "lens_id": key["lens_id"],
                "holdout_terms": holdout_terms,
                "holdout_weight": holdout_terms,
                "visible_holdout": list(visible_holdout),
                "predicted_holdout": list(answer[:holdout_terms]),
                "future_answer": list(future),
                "survived": survived,
                "confidence": item.get("confidence", 0.0),
                "rule_summary": item.get("rule_summary"),
                "check_summary": item.get("check_summary"),
                "future_exact": future == truth[key["case_id"]],
                "response_sha256": result.get("response_sha256"),
            }
        )

    by_case: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_case[row["case_id"]].append(row)
    routed_cases = sorted(by_case)
    if any(len(rows) != 8 for rows in by_case.values()):
        raise ScoringError("each routed case must have eight candidates")

    policies = (
        "any_survivor_plurality",
        "longest_holdout_plurality",
        "holdout_weighted_plurality",
        "two_survivor_gate",
        "cross_horizon_gate",
    )
    policy_results: dict[str, Any] = {}
    policy_answers: dict[str, dict[str, tuple[str, ...]]] = {}
    for policy in policies:
        final = dict(base_final)
        for case_id, rows in by_case.items():
            survivors = [row for row in rows if row["survived"]]
            final[case_id] = policy_answer(policy, survivors, base_final[case_id])
        exact = sum(final[case_id] == truth[case_id] for case_id in final)
        terms = sum(
            sum(left == right for left, right in zip(final[case_id], truth[case_id]))
            for case_id in final
        )
        useful = sum(
            base_final[case_id] != truth[case_id] and final[case_id] == truth[case_id]
            for case_id in routed_cases
        )
        harmful = sum(
            base_final[case_id] == truth[case_id] and final[case_id] != truth[case_id]
            for case_id in routed_cases
        )
        policy_results[policy] = {
            "exact": exact,
            "cases": len(final),
            "exact_accuracy": exact / len(final),
            "correct_terms": terms,
            "terms": 5 * len(final),
            "term_accuracy": terms / (5 * len(final)),
            "useful_overrides": useful,
            "harmful_overrides": harmful,
        }
        policy_answers[policy] = final

    base_exact = sum(base_final[case_id] == truth[case_id] for case_id in base_final)
    survivor_oracle = sum(
        truth[case_id]
        in {tuple(row["future_answer"]) for row in rows if row["survived"]}
        for case_id, rows in by_case.items()
    )
    all_candidate_oracle = sum(
        truth[case_id] in {tuple(row["future_answer"]) for row in rows}
        for case_id, rows in by_case.items()
    )

    lens_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "holdout_survivors": 0, "future_exact": 0, "both": 0}
    )
    case_stats: dict[str, Any] = {}
    for row in candidates:
        stats = lens_stats[row["lens_id"]]
        stats["calls"] += 1
        stats["holdout_survivors"] += int(row["survived"])
        stats["future_exact"] += int(row["future_exact"])
        stats["both"] += int(row["survived"] and row["future_exact"])
    for case_id, rows in sorted(by_case.items()):
        survivors = [row for row in rows if row["survived"]]
        case_stats[case_id] = {
            "family": metadata[case_id]["family"],
            "base_exact": base_final[case_id] == truth[case_id],
            "survivor_count": len(survivors),
            "surviving_future_answers": sorted(
                {tuple(row["future_answer"]) for row in survivors}
            ),
            "survivor_contains_truth": truth[case_id]
            in {tuple(row["future_answer"]) for row in survivors},
            "all_candidates_contain_truth": truth[case_id]
            in {tuple(row["future_answer"]) for row in rows},
            "policy_exact": {
                policy: policy_answers[policy][case_id] == truth[case_id]
                for policy in policies
            },
        }

    result = {
        "schema_version": "5.2-exploration",
        "artifact_type": "visible-holdout-open-development-score",
        "status": "open_development_not_validation",
        "base_fifteen": {
            "exact": base_exact,
            "cases": len(base_final),
            "exact_accuracy": base_exact / len(base_final),
        },
        "routed_cases": routed_cases,
        "routed_count": len(routed_cases),
        "candidate_calls": len(candidates),
        "holdout_survivors": sum(row["survived"] for row in candidates),
        "survivor_oracle_on_routed_cases": {
            "exact": survivor_oracle,
            "cases": len(routed_cases),
            "exact_accuracy": survivor_oracle / len(routed_cases),
        },
        "all_candidate_oracle_on_routed_cases": {
            "exact": all_candidate_oracle,
            "cases": len(routed_cases),
            "exact_accuracy": all_candidate_oracle / len(routed_cases),
        },
        "policies": policy_results,
        "lens_stats": dict(sorted(lens_stats.items())),
        "case_stats": case_stats,
        "candidate_records": candidates,
        "interpretation_rule": "This score uses already-open B13/B14 cases and is development evidence only. Any promoted selector must be frozen before a new fresh gate.",
        "sha256": {
            "base_predictions": sha256(args.base_predictions),
            "job_manifest": sha256(args.job_manifest),
            "holdout_truth": sha256(args.holdout_truth),
            "answers": sha256(args.answers),
        },
    }
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "base_exact": base_exact,
                "best_policy": max(
                    policy_results,
                    key=lambda name: (
                        policy_results[name]["exact"],
                        policy_results[name]["term_accuracy"],
                        -policy_results[name]["harmful_overrides"],
                        name,
                    ),
                ),
                "policy_exact": {
                    key: value["exact"] for key, value in policy_results.items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
