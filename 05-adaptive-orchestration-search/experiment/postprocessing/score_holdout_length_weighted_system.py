#!/usr/bin/env python3
"""Score the frozen visible-holdout system with public-suffix-length weights."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import score_verified_holdout_system as base


unit_plurality = base.plurality


def length_weighted_plurality(
    rows: Iterable[dict[str, Any]], answer_key: str
) -> tuple[str, ...]:
    materialized = list(rows)
    if answer_key == "answer":
        return unit_plurality(materialized, answer_key)

    scores: defaultdict[tuple[str, ...], int] = defaultdict(int)
    counts: Counter[tuple[str, ...]] = Counter()
    longest: defaultdict[tuple[str, ...], int] = defaultdict(int)
    depths: defaultdict[tuple[str, ...], set[int]] = defaultdict(set)
    stages: defaultdict[tuple[str, ...], set[int]] = defaultdict(set)
    for row in materialized:
        answer = base.canonical_answer(row.get(answer_key), 5)
        holdout_terms = int(row.get("holdout_terms", 0))
        if holdout_terms < 1:
            raise base.ScoringError("verified candidates require a positive holdout length")
        scores[answer] += holdout_terms
        counts[answer] += 1
        longest[answer] = max(longest[answer], holdout_terms)
        depths[answer].add(holdout_terms)
        stages[answer].add(int(row.get("source_stage", 0)))
    if not scores:
        raise base.ScoringError("cannot select from an empty candidate set")
    return min(
        scores,
        key=lambda answer: (
            -scores[answer],
            -longest[answer],
            -len(depths[answer]),
            -len(stages[answer]),
            -counts[answer],
            answer,
        ),
    )


def main() -> int:
    base.plurality = length_weighted_plurality
    status = base.main()
    try:
        output_index = sys.argv.index("--output") + 1
        output_path = Path(sys.argv[output_index])
    except (ValueError, IndexError) as exc:
        raise base.ScoringError("--output is required") from exc
    result = base.load(output_path)
    result["artifact_type"] = "holdout-length-weighted-frozen-system-score"
    result["verified_selection"]["selector"] = (
        "sum of recovered public holdout terms descending, longest recovered holdout "
        "descending, distinct holdout depths descending, source-stage diversity "
        "descending, raw support descending, canonical tuple ascending"
    )
    result["verified_selection"]["uses_self_reported_confidence"] = False
    result["verified_selection"]["weight_definition"] = (
        "Each verified candidate receives one vote unit per public suffix term it "
        "predicted exactly before its five hidden continuation terms."
    )
    base.write_json(output_path, result)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
