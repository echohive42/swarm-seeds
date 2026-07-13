#!/usr/bin/env python3
"""Experiment 04 scoring adapter over the audited Experiment 03 scorer."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "4.0"
_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "03-evolving-light-swarms"
    / "experiment"
    / "scripts"
    / "score.py"
)


def _load_impl():
    spec = importlib.util.spec_from_file_location("experiment03_score", _SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified scorer: {_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()
_IMPL.SCHEMA_VERSION = SCHEMA_VERSION
ScoreError = _IMPL.ScoreError


def protocol_fitness(cases: Sequence[dict[str, Any]], method: str) -> dict[str, Any]:
    """Return the registered five-part lexicographic Experiment 04 fitness."""
    rows = [(case, case["methods"][method]) for case in cases]
    block_exact: dict[str, int] = defaultdict(int)
    for case, row in rows:
        block_exact[str(case["block"])] += int(row["exact"])
    key = [
        sum(int(row["exact"]) for _, row in rows),
        min(block_exact.values()) if block_exact else 0,
        -sum(int(row["harmful_override"]) for _, row in rows),
        sum(int(row["term_correct"]) for _, row in rows),
        sum(int(row["format_compliant"]) for _, row in rows),
    ]
    return {
        "protocol_fitness_key": key,
        "block_exact_cases": dict(sorted(block_exact.items())),
        "weakest_block_exact": key[1],
        "fitness_order": (
            "lexicographic max: exact_cases, weakest_block_exact, "
            "-harmful_overrides, term_correct, format_valid"
        ),
    }


def run_score(
    answers_path: Path,
    predictions_path: Path,
    out_dir: Path,
    final_genome: str | None,
    baselines: Sequence[str],
    replicates: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    answers = _IMPL.load_answers(_IMPL.load_records(answers_path))
    prediction_rows = _IMPL.load_records(predictions_path)
    jobs = _IMPL.normalize_completed_jobs(prediction_rows, answers)
    cases, genome_flags = _IMPL.build_case_scores(answers, jobs)
    if not cases or not cases[0]["methods"]:
        raise ScoreError("no scoreable completed architectures")
    summary = _IMPL.summarize(cases, genome_flags, replicates, seed)
    summary["schema_version"] = SCHEMA_VERSION
    summary["fitness_definition"] = (
        "lexicographic max: exact_cases, weakest_block_exact, "
        "-harmful_overrides, term_correct, format_valid"
    )
    summary["inputs"] = {
        "answers_sha256": _IMPL.file_sha256(answers_path),
        "predictions_sha256": _IMPL.file_sha256(predictions_path),
        "completed_jobs": len(jobs),
    }
    summary["protocol_fitness"] = {}
    for method in sorted(cases[0]["methods"]):
        fitness = protocol_fitness(cases, method)
        summary["protocol_fitness"][method] = fitness
        summary["methods"][method].update(fitness)
    # E03 correctly de-duplicates resources by job ID, but E04 deliberately
    # appends zero-call aggregate records. Keep operational call counts limited
    # to the ten paid identities rather than counting those deterministic rows.
    paid: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for job in jobs:
        method = (
            job["architecture_id"]
            if job["architecture_id"] in _IMPL.VOTE_SLOTS
            else job["genome_id"] or job["architecture_id"]
        )
        if job["calls"] > 0:
            paid[method][job["call_key"]] = job
    for method, method_summary in summary["methods"].items():
        method_summary["completed_calls"] = len(paid[method])
        method_summary["malformed_calls"] = sum(
            not job["job_format_valid"] for job in paid[method].values()
        )
    for row in summary["genome_scores"]:
        fitness = summary["protocol_fitness"][row["genome_id"]]
        row.update(fitness)
        row["fitness_key_without_hash"] = fitness["protocol_fitness_key"]
    summary["scores"] = summary["genome_scores"]

    comparison_output = _IMPL.comparisons(cases, final_genome, baselines, replicates, seed)
    comparison_output["schema_version"] = SCHEMA_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    _IMPL.write_case_matrix(out_dir / "case_matrix.csv", cases)
    _IMPL.write_json(out_dir / "summary.json", summary)
    _IMPL.write_json(out_dir / "comparisons.json", comparison_output)
    return summary, comparison_output


def self_test() -> None:
    _IMPL.self_test()
    case = {
        "block": "B1",
        "methods": {
            "G": {"exact": 1, "harmful_override": 0, "term_correct": 5, "format_compliant": 1}
        },
    }
    assert protocol_fitness([case], "G")["protocol_fitness_key"] == [1, 1, 0, 5, 1]
    print("score.py Experiment 04 adapter self-test: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    args = _IMPL.build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    predictions = args.predictions or args.jobs
    if args.answers is None or predictions is None or args.out_dir is None:
        raise ScoreError("--answers, --predictions, and --out-dir are required unless --self-test is used")
    summary, comparison = run_score(
        args.answers,
        predictions,
        args.out_dir,
        args.final_genome,
        args.baseline,
        args.bootstrap_replicates,
        args.bootstrap_seed,
    )
    print(json.dumps({
        "case_matrix": str(args.out_dir / "case_matrix.csv"),
        "summary": str(args.out_dir / "summary.json"),
        "comparisons": str(args.out_dir / "comparisons.json"),
        "n_cases": summary["n_cases"],
        "primary": comparison.get("primary"),
    }, indent=2, sort_keys=True))
    return 0


def __getattr__(name: str):
    return getattr(_IMPL, name)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ScoreError) as error:
        print(f"score.py: error: {error}", file=sys.stderr)
        raise SystemExit(2)
