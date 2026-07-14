#!/usr/bin/env python3
"""Build a reusable research archive from completed search and validation calls."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "results" / "exploration"
ANSWER_PATHS = (
    ROOT / "benchmark" / "hidden" / "search_answers.jsonl",
    ROOT / "benchmark" / "hidden" / "validation_answers.jsonl",
)
PREDICTION_PATHS = (
    ROOT / "runs" / "search" / "batch-01" / "predictions.json",
    ROOT / "runs" / "search" / "batch-02" / "predictions.json",
    ROOT / "runs" / "search" / "batch-03" / "predictions.json",
    ROOT / "runs" / "validation" / "wave-01" / "predictions.json",
    ROOT / "runs" / "validation" / "wave-02" / "predictions.json",
)
REVIEW_ROLES = {"critic", "verifier", "judge", "auditor", "challenger", "juror", "integrator"}


class ArchiveError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_truth() -> dict[str, dict[str, Any]]:
    truth: dict[str, dict[str, Any]] = {}
    for path in ANSWER_PATHS:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            case_id = row["case_id"]
            if case_id in truth:
                raise ArchiveError(f"duplicate answer for {case_id}")
            split = "search" if case_id.startswith("S") else "validation"
            case_number = int(case_id[1:])
            truth[case_id] = {
                "answer": tuple(row.get("next_five", row.get("next"))),
                "family": row["family"],
                "tier": row["tier"],
                "block": f"{split}-b{((case_number - 1) // 12) + 1:02d}",
                "split": split,
            }
    if len(truth) != 144:
        raise ArchiveError(f"expected 144 research answers, found {len(truth)}")
    return truth


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def select(
    hypotheses: dict[tuple[str, ...], dict[str, Any]], support_field: str
) -> tuple[str, ...] | None:
    if not hypotheses:
        return None
    return min(
        hypotheses,
        key=lambda answer: (
            -len(hypotheses[answer][support_field]),
            -mean(hypotheses[answer]["confidences"]),
            answer,
        ),
    )


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    truth = load_truth()
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_record_counts: dict[str, int] = {}
    for path in PREDICTION_PATHS:
        document = json.loads(path.read_text(encoding="utf-8"))
        source_record_counts[path.relative_to(ROOT).as_posix()] = len(document["records"])
        for row in document["records"]:
            answer = row.get("answer")
            case_id = row.get("case_id")
            if (
                case_id in truth
                and row.get("format_valid") is True
                and isinstance(answer, list)
                and len(answer) == 5
                and all(isinstance(term, str) for term in answer)
            ):
                records[case_id].append(row)

    archive_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    family_tier = defaultdict(lambda: Counter(cases=0, oracle=0, raw=0, strategy=0, lens=0))
    totals = Counter(cases=0, oracle=0, proposer_oracle=0, raw=0, strategy=0, lens=0)

    for case_id in sorted(truth):
        metadata = truth[case_id]
        hypotheses: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
            lambda: {
                "jobs": set(), "strategies": set(), "lenses": set(), "roles": set(),
                "phases": set(), "stages": set(), "confidences": [], "role_counts": Counter(),
            }
        )
        for row in records[case_id]:
            answer = tuple(row["answer"])
            item = hypotheses[answer]
            item["jobs"].add(row["job_id"])
            item["strategies"].add(row["architecture_id"])
            item["lenses"].add(row.get("lens_id", "unknown"))
            item["roles"].add(row.get("role", "unknown"))
            item["phases"].add(row.get("phase", "unknown"))
            item["stages"].add(row.get("stage", "unknown"))
            item["confidences"].append(float(row.get("confidence", 0.0)))
            item["role_counts"][row.get("role", "unknown")] += 1

        correct = metadata["answer"]
        oracle = correct in hypotheses
        proposer_oracle = oracle and hypotheses[correct]["role_counts"]["proposer"] > 0
        raw_choice = select(hypotheses, "jobs")
        strategy_choice = select(hypotheses, "strategies")
        lens_choice = select(hypotheses, "lenses")
        totals.update(
            cases=1,
            oracle=int(oracle),
            proposer_oracle=int(proposer_oracle),
            raw=int(raw_choice == correct),
            strategy=int(strategy_choice == correct),
            lens=int(lens_choice == correct),
        )
        cell = family_tier[(metadata["family"], metadata["tier"])]
        cell.update(
            cases=1,
            oracle=int(oracle),
            raw=int(raw_choice == correct),
            strategy=int(strategy_choice == correct),
            lens=int(lens_choice == correct),
        )

        ordered = sorted(
            hypotheses,
            key=lambda answer: (
                -len(hypotheses[answer]["jobs"]),
                -mean(hypotheses[answer]["confidences"]),
                answer,
            ),
        )
        correct_rank = ordered.index(correct) + 1 if oracle else None
        case_rows.append({
            "case_id": case_id,
            "split": metadata["split"],
            "block": metadata["block"],
            "family": metadata["family"],
            "tier": metadata["tier"],
            "valid_record_count": len(records[case_id]),
            "unique_hypothesis_count": len(hypotheses),
            "oracle_exact": int(oracle),
            "proposer_oracle_exact": int(proposer_oracle),
            "correct_support_rank": correct_rank if correct_rank is not None else "",
            "raw_plurality_exact": int(raw_choice == correct),
            "strategy_plurality_exact": int(strategy_choice == correct),
            "lens_plurality_exact": int(lens_choice == correct),
        })

        for answer in ordered:
            item = hypotheses[answer]
            role_counts = item["role_counts"]
            archive_rows.append({
                "case_id": case_id,
                "split": metadata["split"],
                "block": metadata["block"],
                "family": metadata["family"],
                "tier": metadata["tier"],
                "answer": list(answer),
                "is_exact": answer == correct,
                "job_support": len(item["jobs"]),
                "strategy_support": len(item["strategies"]),
                "lens_support": len(item["lenses"]),
                "proposer_support": role_counts["proposer"],
                "reviewer_support": sum(role_counts[role] for role in REVIEW_ROLES),
                "final_support": role_counts["final"],
                "mean_confidence": mean(item["confidences"]),
                "max_confidence": max(item["confidences"]),
                "strategies": sorted(item["strategies"]),
                "lenses": sorted(item["lenses"]),
                "roles": sorted(item["roles"]),
                "phases": sorted(item["phases"]),
                "stages": sorted(item["stages"]),
            })

    summary = {
        "schema_version": "5.0",
        "artifact_type": "experiment-05-candidate-archive-summary",
        "scope": "completed search and two-wave validation only; partial hidden-final calls excluded",
        "case_count": totals["cases"],
        "valid_case_prediction_records": sum(len(rows) for rows in records.values()),
        "unique_hypotheses": len(archive_rows),
        "oracle_exact_cases": totals["oracle"],
        "oracle_exact_accuracy": totals["oracle"] / totals["cases"],
        "proposer_oracle_exact_cases": totals["proposer_oracle"],
        "raw_plurality_exact_cases": totals["raw"],
        "raw_plurality_exact_accuracy": totals["raw"] / totals["cases"],
        "strategy_plurality_exact_cases": totals["strategy"],
        "lens_plurality_exact_cases": totals["lens"],
        "missing_correct_hypothesis_cases": [
            row["case_id"] for row in case_rows if not row["oracle_exact"]
        ],
        "family_tier": {
            f"{family}:{tier}": dict(counts)
            for (family, tier), counts in sorted(family_tier.items())
        },
        "inputs": {
            "answers": {path.relative_to(ROOT).as_posix(): sha256(path) for path in ANSWER_PATHS},
            "predictions": {path.relative_to(ROOT).as_posix(): sha256(path) for path in PREDICTION_PATHS},
            "source_record_counts": source_record_counts,
        },
    }
    return archive_rows, case_rows, summary


def main() -> int:
    archive_rows, case_rows, summary = build()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "candidate_archive.jsonl").open("w", encoding="utf-8") as handle:
        for row in archive_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (OUTPUT_DIR / "candidate_archive_cases.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(case_rows[0]))
        writer.writeheader()
        writer.writerows(case_rows)
    (OUTPUT_DIR / "candidate_archive_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ArchiveError) as exc:
        print(f"build_candidate_archive.py: error: {exc}")
        raise SystemExit(2)
