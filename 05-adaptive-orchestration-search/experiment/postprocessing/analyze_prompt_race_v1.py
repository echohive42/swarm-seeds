#!/usr/bin/env python3
"""Analyze one open-ended prompt race without additional model calls."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Sequence


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def answer_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) != 5 or any(not isinstance(item, str) for item in value):
        return None
    return tuple(value)


def plurality(
    lens_ids: Sequence[str],
    case_id: str,
    predictions: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str, ...] | None:
    counts: Counter[tuple[str, ...]] = Counter()
    confidence: defaultdict[tuple[str, ...], float] = defaultdict(float)
    for lens_id in lens_ids:
        row = predictions[(lens_id, case_id)]
        answer = answer_tuple(row.get("answer"))
        if answer is None:
            continue
        counts[answer] += 1
        confidence[answer] += float(row.get("confidence") or 0.0)
    if not counts:
        return None
    return min(
        counts,
        key=lambda answer: (
            -counts[answer],
            -(confidence[answer] / counts[answer]),
            answer,
        ),
    )


def term_score(predicted: tuple[str, ...] | None, truth: tuple[str, ...]) -> int:
    return sum(a == b for a, b in zip(predicted or (), truth))


def score_lenses(
    lens_ids: Sequence[str],
    case_ids: Sequence[str],
    predictions: dict[tuple[str, str], dict[str, Any]],
    truths: dict[str, tuple[str, ...]],
) -> dict[str, int | float]:
    exact = 0
    terms = 0
    for case_id in case_ids:
        predicted = plurality(lens_ids, case_id, predictions)
        truth = truths[case_id]
        exact += predicted == truth
        terms += term_score(predicted, truth)
    return {
        "exact": exact,
        "cases": len(case_ids),
        "exact_accuracy": exact / len(case_ids),
        "correct_terms": terms,
        "terms": 5 * len(case_ids),
        "term_accuracy": terms / (5 * len(case_ids)),
    }


def subset_id(lens_ids: Iterable[str]) -> str:
    joined = "\n".join(sorted(lens_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--strategy-batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--random-subsets", type=int, default=25000)
    args = parser.parse_args()

    prediction_document = load_json(args.predictions)
    answer_rows = load_jsonl(args.answers)
    strategy_batch = load_json(args.strategy_batch)
    model_rows = [row for row in prediction_document["records"] if not row.get("is_final_output")]
    selected_cases = sorted({row["case_id"] for row in model_rows})
    answer_index = {row["case_id"]: row for row in answer_rows if row["case_id"] in selected_cases}
    truths = {case_id: answer_tuple(answer_index[case_id]["next"]) for case_id in selected_cases}
    if any(value is None for value in truths.values()):
        raise RuntimeError("invalid truth answer")
    truths = {key: value for key, value in truths.items() if value is not None}

    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in model_rows:
        key = (row["lens_id"], row["case_id"])
        if key in predictions:
            raise RuntimeError(f"duplicate lens/case prediction: {key}")
        predictions[key] = row
    lens_ids = sorted({row["lens_id"] for row in model_rows})
    if len(selected_cases) != 24 or len(lens_ids) != 30 or len(predictions) != 720:
        raise RuntimeError("expected exactly 24 cases, 30 prompt arms, and 720 predictions")
    if any((lens_id, case_id) not in predictions for lens_id in lens_ids for case_id in selected_cases):
        raise RuntimeError("incomplete prompt/case matrix")

    blocks: dict[str, list[str]] = defaultdict(list)
    for row in model_rows:
        if row["lens_id"] == lens_ids[0]:
            blocks[row["block_id"]].append(row["case_id"])
    blocks = {key: sorted(set(value)) for key, value in sorted(blocks.items())}
    if sorted(map(len, blocks.values())) != [12, 12]:
        raise RuntimeError("expected two 12-case blocks")
    block_ids = list(blocks)

    strategy_lenses = {
        strategy["strategy_id"]: strategy["stages"][0]["lens_ids"]
        for strategy in strategy_batch["strategies"]
    }

    lens_scores = []
    for lens_id in lens_ids:
        all_score = score_lenses([lens_id], selected_cases, predictions, truths)
        block_scores = {
            block_id: score_lenses([lens_id], case_ids, predictions, truths)
            for block_id, case_ids in blocks.items()
        }
        rows = [predictions[(lens_id, case_id)] for case_id in selected_cases]
        lens_scores.append({
            "lens_id": lens_id,
            **all_score,
            "block_exact": {key: value["exact"] for key, value in block_scores.items()},
            "mean_confidence": mean(float(row.get("confidence") or 0.0) for row in rows),
            "mean_latency_ms": mean(float(row.get("latency_ms") or 0.0) for row in rows),
        })
    lens_scores.sort(key=lambda row: (-row["exact"], -row["correct_terms"], row["lens_id"]))

    systems: dict[str, list[str]] = {
        **strategy_lenses,
        "ALL-30": lens_ids,
    }
    system_scores = {
        system_id: {
            "lens_count": len(members),
            "lens_ids": sorted(members),
            "all": score_lenses(members, selected_cases, predictions, truths),
            "blocks": {
                block_id: score_lenses(members, case_ids, predictions, truths)
                for block_id, case_ids in blocks.items()
            },
        }
        for system_id, members in systems.items()
    }

    case_rows = []
    oracle_exact = 0
    for case_id in selected_cases:
        truth = truths[case_id]
        answers = [answer_tuple(predictions[(lens_id, case_id)].get("answer")) for lens_id in lens_ids]
        valid = [answer for answer in answers if answer is not None]
        counts = Counter(valid)
        correct_support = counts[truth]
        pooled = plurality(lens_ids, case_id, predictions)
        present = correct_support > 0
        oracle_exact += present
        hidden = answer_index[case_id]
        case_rows.append({
            "case_id": case_id,
            "block_id": next(key for key, value in blocks.items() if case_id in value),
            "family": hidden["family"],
            "tier": hidden["tier"],
            "unique_answers": len(counts),
            "correct_support": correct_support,
            "correct_support_rate": correct_support / len(lens_ids),
            "plurality_support": max(counts.values()) if counts else 0,
            "pooled_plurality_exact": pooled == truth,
            "oracle_exact": present,
            "pooled_term_score": term_score(pooled, truth),
        })

    family_scores = {}
    for family in sorted({row["family"] for row in case_rows}):
        family_cases = [row["case_id"] for row in case_rows if row["family"] == family]
        family_scores[family] = {
            "cases": len(family_cases),
            "pooled": score_lenses(lens_ids, family_cases, predictions, truths),
            "oracle_exact": sum(row["oracle_exact"] for row in case_rows if row["family"] == family),
        }

    rng = random.Random("swarm-seeds-05-wide-01-subsets-v1")
    sizes = [3, 5, 7, 9, 11, 15, 19, 23, 27, 30]
    subsets: set[tuple[str, ...]] = {
        tuple(sorted(value)) for value in systems.values()
    }
    while len(subsets) < args.random_subsets:
        size = rng.choice(sizes)
        subsets.add(tuple(sorted(rng.sample(lens_ids, size))))

    subset_rows = []
    for subset in subsets:
        b1 = score_lenses(subset, blocks[block_ids[0]], predictions, truths)
        b2 = score_lenses(subset, blocks[block_ids[1]], predictions, truths)
        all_score = score_lenses(subset, selected_cases, predictions, truths)
        subset_rows.append({
            "subset_id": subset_id(subset),
            "lens_count": len(subset),
            "lens_ids": list(subset),
            "block_1_exact": b1["exact"],
            "block_1_terms": b1["correct_terms"],
            "block_2_exact": b2["exact"],
            "block_2_terms": b2["correct_terms"],
            "total_exact": all_score["exact"],
            "total_terms": all_score["correct_terms"],
            "worst_block_exact": min(b1["exact"], b2["exact"]),
        })

    balanced = sorted(
        subset_rows,
        key=lambda row: (
            -row["worst_block_exact"],
            -row["total_exact"],
            -row["total_terms"],
            row["lens_count"],
            row["subset_id"],
        ),
    )
    forward = sorted(
        subset_rows,
        key=lambda row: (
            -row["block_1_exact"],
            -row["block_1_terms"],
            row["lens_count"],
            row["subset_id"],
        ),
    )
    reverse = sorted(
        subset_rows,
        key=lambda row: (
            -row["block_2_exact"],
            -row["block_2_terms"],
            row["lens_count"],
            row["subset_id"],
        ),
    )

    def directional_summary(ranked: list[dict[str, Any]], train_key: str, test_key: str) -> dict[str, Any]:
        chosen = ranked[0]
        top = ranked[:100]
        return {
            "selection_uses_only": train_key,
            "canonical_selected": chosen,
            "top_100_train_winners_test_exact_mean": mean(row[test_key] for row in top),
            "top_100_train_winners_test_exact_median": median(row[test_key] for row in top),
            "top_100_train_winners_test_exact_range": [min(row[test_key] for row in top), max(row[test_key] for row in top)],
        }

    output = {
        "schema_version": "5.1-exploration",
        "artifact_type": "experiment-05-open-prompt-race-analysis",
        "source_predictions_sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
        "case_count": len(selected_cases),
        "prompt_arm_count": len(lens_ids),
        "model_call_count": prediction_document["paid_call_count"],
        "valid_prediction_count": sum(answer_tuple(row.get("answer")) is not None for row in model_rows),
        "candidate_oracle": {
            "exact": oracle_exact,
            "cases": len(selected_cases),
            "exact_accuracy": oracle_exact / len(selected_cases),
        },
        "lens_scores": lens_scores,
        "system_scores": system_scores,
        "family_diagnostics": family_scores,
        "case_diagnostics": case_rows,
        "subset_search": {
            "random_seed": "swarm-seeds-05-wide-01-subsets-v1",
            "subsets_evaluated": len(subset_rows),
            "balanced_in_sample_best": balanced[0],
            "block_1_to_block_2": directional_summary(forward, "block_1_exact", "block_2_exact"),
            "block_2_to_block_1": directional_summary(reverse, "block_2_exact", "block_1_exact"),
            "warning": "The balanced result uses all 24 exploratory answers and is not validation. Directional transfers are small 12-case internal checks only.",
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "wide-01-analysis.json", output)
    with (args.output_dir / "wide-01-lens-scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["lens_id", "exact", "cases", "exact_accuracy", "correct_terms", "term_accuracy", block_ids[0], block_ids[1], "mean_confidence", "mean_latency_ms"])
        for row in lens_scores:
            writer.writerow([row["lens_id"], row["exact"], row["cases"], row["exact_accuracy"], row["correct_terms"], row["term_accuracy"], row["block_exact"][block_ids[0]], row["block_exact"][block_ids[1]], row["mean_confidence"], row["mean_latency_ms"]])
    with (args.output_dir / "wide-01-case-scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(case_rows[0]))
        writer.writeheader()
        writer.writerows(case_rows)
    write_json(args.output_dir / "wide-01-top-subsets.json", {
        "balanced_top_100": balanced[:100],
        "block_1_train_top_100": forward[:100],
        "block_2_train_top_100": reverse[:100],
    })
    print(json.dumps({
        "calls": prediction_document["paid_call_count"],
        "oracle_exact": oracle_exact,
        "pooled_exact": system_scores["ALL-30"]["all"]["exact"],
        "best_lens": lens_scores[0]["lens_id"],
        "best_lens_exact": lens_scores[0]["exact"],
        "subsets_evaluated": len(subset_rows),
        "balanced_subset_exact": balanced[0]["total_exact"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
