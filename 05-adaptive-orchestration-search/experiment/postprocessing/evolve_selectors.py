#!/usr/bin/env python3
"""Race thousands of generic linear selectors over the saved candidate archive."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "results" / "exploration" / "candidate_archive.jsonl"
OUTPUT = ROOT / "results" / "exploration" / "selector_search.json"
SEED = 20_260_714
POPULATION = 5_000
FEATURES = (
    "job_share",
    "strategy_share",
    "lens_share",
    "proposer_share",
    "reviewer_share",
    "mean_confidence",
    "max_confidence",
    "lens_per_job",
    "cross_role",
    "reviewer_ratio",
    "consensus_diversity",
    "inverse_job_support",
)


class SearchError(RuntimeError):
    pass


def load_cases() -> dict[str, dict[str, Any]]:
    raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in ARCHIVE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        raw[row["case_id"]].append(row)
    cases: dict[str, dict[str, Any]] = {}
    for case_id, rows in raw.items():
        totals = {
            "jobs": sum(row["job_support"] for row in rows),
            "strategies": sum(row["strategy_support"] for row in rows),
            "lenses": sum(row["lens_support"] for row in rows),
            "proposers": sum(row["proposer_support"] for row in rows),
            "reviewers": sum(row["reviewer_support"] for row in rows),
        }
        candidates = []
        for row in rows:
            job_support = row["job_support"]
            lens_support = row["lens_support"]
            proposer_support = row["proposer_support"]
            reviewer_support = row["reviewer_support"]
            job_share = job_support / totals["jobs"]
            lens_share = lens_support / totals["lenses"]
            vector = (
                job_share,
                row["strategy_support"] / totals["strategies"],
                lens_share,
                proposer_support / totals["proposers"] if totals["proposers"] else 0.0,
                reviewer_support / totals["reviewers"] if totals["reviewers"] else 0.0,
                row["mean_confidence"],
                row["max_confidence"],
                lens_support / job_support,
                float(proposer_support > 0 and reviewer_support > 0),
                reviewer_support / job_support,
                job_share * lens_share,
                1.0 / job_support,
            )
            candidates.append({
                "answer": tuple(row["answer"]),
                "exact": bool(row["is_exact"]),
                "vector": vector,
            })
        cases[case_id] = {
            "family": rows[0]["family"],
            "tier": rows[0]["tier"],
            "split": rows[0]["split"],
            "candidates": candidates,
        }
    if len(cases) != 144:
        raise SearchError(f"expected 144 cases, found {len(cases)}")
    return cases


def panels(cases: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    cells: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for case_id, row in cases.items():
        cells[(row["family"], row["tier"])][row["split"]].append(case_id)
    panel24, panel48, development, holdout = [], [], [], []
    for cell, split_rows in sorted(cells.items()):
        search = sorted(split_rows["search"])
        validation = sorted(split_rows["validation"])
        if len(search) != 3 or len(validation) != 3:
            raise SearchError(f"cell {cell} is not balanced 3 plus 3")
        choose_search = int(hashlib.sha256(f"{cell[0]}:{cell[1]}".encode()).hexdigest(), 16) % 2 == 0
        first = search[0] if choose_search else validation[0]
        panel24.append(first)
        panel48.extend((search[0], validation[0]))
        development.extend((search[0], search[1], validation[0], validation[1]))
        holdout.extend((search[2], validation[2]))
    return {
        "panel24": sorted(panel24),
        "panel48": sorted(panel48),
        "development96": sorted(development),
        "holdout48": sorted(holdout),
    }


def choose(policy: tuple[int, ...], case: dict[str, Any]) -> dict[str, Any]:
    def key(candidate: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
        score = sum(weight * value for weight, value in zip(policy, candidate["vector"]))
        return (-score, candidate["answer"])
    return min(case["candidates"], key=key)


def evaluate(
    policy: tuple[int, ...], case_ids: Iterable[str], cases: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    by_family: Counter[str] = Counter()
    family_total: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    tier_total: Counter[str] = Counter()
    exact = 0
    signature = []
    for case_id in case_ids:
        case = cases[case_id]
        selected = choose(policy, case)
        correct = int(selected["exact"])
        exact += correct
        by_family[case["family"]] += correct
        family_total[case["family"]] += 1
        by_tier[case["tier"]] += correct
        tier_total[case["tier"]] += 1
        signature.append(selected["answer"])
    return {
        "exact": exact,
        "cases": len(signature),
        "accuracy": exact / len(signature),
        "worst_family_accuracy": min(by_family[key] / family_total[key] for key in family_total),
        "worst_tier_accuracy": min(by_tier[key] / tier_total[key] for key in tier_total),
        "family_accuracy": {key: by_family[key] / family_total[key] for key in sorted(family_total)},
        "tier_accuracy": {key: by_tier[key] / tier_total[key] for key in sorted(tier_total)},
        "signature_sha256": hashlib.sha256(
            json.dumps(signature, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def fitness(policy: tuple[int, ...], result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        result["exact"],
        result["worst_family_accuracy"],
        result["worst_tier_accuracy"],
        -sum(abs(value) for value in policy),
        policy,
    )


def population() -> list[tuple[int, ...]]:
    seeds = [
        (8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (4, 0, 4, 0, 0, 0, 0, 0, 0, 0, 4, 0),
        (2, 1, 3, 2, 3, 1, 0, 2, 2, 1, 3, -1),
    ]
    rng = random.Random(SEED)
    seen = set(seeds)
    while len(seen) < POPULATION:
        policy = tuple(rng.randint(-8, 8) for _ in FEATURES)
        if any(value > 0 for value in policy):
            seen.add(policy)
    return list(seen)


def race(
    policies: list[tuple[int, ...]], case_ids: list[str], keep: int,
    cases: dict[str, dict[str, Any]]
) -> list[tuple[int, ...]]:
    scored = [(fitness(policy, result := evaluate(policy, case_ids, cases)), policy, result)
              for policy in policies]
    scored.sort(reverse=True)
    survivors: list[tuple[int, ...]] = []
    signatures = set()
    for _, policy, result in scored:
        signature = result["signature_sha256"]
        if signature in signatures:
            continue
        signatures.add(signature)
        survivors.append(policy)
        if len(survivors) == keep:
            break
    return survivors


def main() -> int:
    cases = load_cases()
    split = panels(cases)
    policies = population()
    stage_counts = [{"stage": "initial", "policies": len(policies)}]
    for name, keep in (("panel24", 800), ("panel48", 160), ("development96", 25)):
        policies = race(policies, split[name], keep, cases)
        stage_counts.append({"stage": name, "cases": len(split[name]), "policies": len(policies)})
    ranked = []
    for rank, policy in enumerate(policies, 1):
        ranked.append({
            "development_rank": rank,
            "weights": dict(zip(FEATURES, policy)),
            "l1_complexity": sum(abs(value) for value in policy),
            "development": evaluate(policy, split["development96"], cases),
            "untouched_internal_holdout": evaluate(policy, split["holdout48"], cases),
        })
    document = {
        "schema_version": "5.0",
        "artifact_type": "experiment-05-offline-selector-race",
        "status": "exploratory_not_confirmatory",
        "selector_inputs_exclude": ["truth", "family", "tier", "generator program"],
        "features": list(FEATURES),
        "seed": SEED,
        "stage_counts": stage_counts,
        "panels": split,
        "selection_note": "Holdout scores were computed only after the 25 development survivors were frozen and did not alter their order.",
        "top_development_policies": ranked,
        "archive_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "stage_counts": stage_counts,
        "best_development": ranked[0]["development"],
        "best_development_policy_holdout": ranked[0]["untouched_internal_holdout"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, SearchError) as exc:
        print(f"evolve_selectors.py: error: {exc}")
        raise SystemExit(2)
