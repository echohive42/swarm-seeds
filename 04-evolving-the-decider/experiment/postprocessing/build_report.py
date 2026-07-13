#!/usr/bin/env python3
"""Build the deterministic Experiment 04 analysis and publication SVGs.

This script uses only the Python standard library. It deliberately waits for the
complete eight-round, validation, and hidden-final evidence before writing any
release artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


EXPERIMENT = Path(__file__).resolve().parents[1]
SEED = EXPERIMENT.parent
RESULTS = EXPERIMENT / "results"
GENOMES = EXPERIMENT / "genomes"
RUNS = EXPERIMENT / "runs"
DEFAULT_IMAGES = SEED / "images"
ROUNDS = 8
FINAL_N = 96
FINAL_METHODS = (
    "generalist_vote10",
    "diversified_vote10",
    "best_initial_founder",
    "evolved_champion",
)
METHOD_LABELS = {
    "generalist_vote10": "Generalist Vote10",
    "diversified_vote10": "Diversified Vote10",
    "best_initial_founder": "Best initial founder",
    "evolved_champion": "Evolved champion",
}
SYSTEMS = (
    "vote_10p",
    "judge_9p1j",
    "gated_7p2c1j",
    "dual_8p2j",
    "verified_7p2v1j",
    "deliberative_6p2c2j",
)
SYSTEM_LABELS = {
    "vote_10p": "Vote 10P",
    "judge_9p1j": "Judge 9P+1J",
    "gated_7p2c1j": "Gated 7P+2C+1J",
    "dual_8p2j": "Dual 8P+2J",
    "verified_7p2v1j": "Verified 7P+2V+1J",
    "deliberative_6p2c2j": "Deliberative 6P+2C+2J",
}
COLORS = {
    "ink": "#152238",
    "muted": "#526174",
    "grid": "#D8E1EB",
    "pale": "#F4F7FA",
    "white": "#FFFFFF",
    "blue": "#277DA1",
    "cyan": "#4CC9C0",
    "green": "#43AA8B",
    "gold": "#F9C74F",
    "orange": "#F9844A",
    "red": "#E05D5D",
    "purple": "#8B6BBE",
    "gray": "#7D8A99",
}
SYSTEM_COLORS = {
    "vote_10p": COLORS["blue"],
    "judge_9p1j": COLORS["orange"],
    "gated_7p2c1j": COLORS["green"],
    "dual_8p2j": COLORS["purple"],
    "verified_7p2v1j": COLORS["cyan"],
    "deliberative_6p2c2j": COLORS["gold"],
}


class ReportError(ValueError):
    """Raised when release inputs violate the registered experiment shape."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"missing required release input: {relative(path)}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"invalid JSON in {relative(path)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"expected a JSON object: {relative(path)}")
    return value


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(EXPERIMENT.resolve()).as_posix()
    except ValueError as exc:
        raise ReportError("release source escaped the experiment directory") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise ReportError(f"missing required release input: {relative(path)}") from exc
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def exact_int(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReportError(f"{label} must be an integer >= {minimum}")
    return value


def exact_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ReportError(f"{label} must be a finite number")
    return float(value)


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def pp(value: float) -> str:
    return f"{100 * value:+.1f} pp"


def as_ci(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ReportError(f"{label} must contain two bounds")
    low, high = (exact_float(item, label) for item in value)
    if low > high:
        raise ReportError(f"{label} bounds are reversed")
    return [low, high]


def method_row(summary: dict[str, Any], method: str) -> dict[str, Any]:
    methods = summary.get("methods")
    if not isinstance(methods, dict) or not isinstance(methods.get(method), dict):
        raise ReportError(f"summary lacks method {method}")
    return methods[method]


def population_system_counts(path: Path) -> dict[str, int]:
    document = load_json(path)
    slots = document.get("slots")
    if not isinstance(slots, list) or len(slots) != 6:
        raise ReportError(f"{relative(path)} must contain six survivor slots")
    counts: Counter[str] = Counter()
    for slot in slots:
        try:
            system = slot["genome"]["genes"]["decision_system_id"]
        except (KeyError, TypeError) as exc:
            raise ReportError(f"invalid genome in {relative(path)}") from exc
        if system not in SYSTEMS:
            raise ReportError(f"unknown decision system {system!r}")
        counts[system] += 1
    return {system: counts[system] for system in SYSTEMS}


def accepted_children(path: Path) -> int:
    receipts = load_json(path).get("comparison_receipts")
    if not isinstance(receipts, list) or len(receipts) != 6:
        raise ReportError(f"{relative(path)} must contain six comparison receipts")
    if any(not isinstance(item, dict) for item in receipts):
        raise ReportError(f"invalid replacement receipt in {relative(path)}")
    decisions = [item.get("decision") for item in receipts]
    if any(item not in {"replace_parent", "keep_parent_exact_tie", "keep_better_parent"} for item in decisions):
        raise ReportError(f"invalid replacement decision in {relative(path)}")
    return decisions.count("replace_parent")


def final_matrix(path: Path, methods: Iterable[str]) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = set(reader.fieldnames or [])
    except FileNotFoundError as exc:
        raise ReportError(f"missing required release input: {relative(path)}") from exc
    if len(rows) != FINAL_N:
        raise ReportError(f"final case matrix has {len(rows)} rows, expected {FINAL_N}")
    if not {"case_id", "block"} <= fields:
        raise ReportError("final case matrix lacks case_id or block")
    case_ids = [row["case_id"] for row in rows]
    if any(not case_id for case_id in case_ids) or len(set(case_ids)) != FINAL_N:
        raise ReportError("final case matrix case IDs must be nonempty and unique")
    blocks = Counter(row["block"] for row in rows)
    if len(blocks) != 8 or set(blocks.values()) != {12}:
        raise ReportError("final case matrix must contain eight 12-case blocks")
    metrics: dict[str, dict[str, int]] = {}
    for method in methods:
        needed = {
            f"{method}.exact", f"{method}.proposal_plurality_exact", f"{method}.override",
            f"{method}.useful_override", f"{method}.harmful_override",
        }
        missing = needed - fields
        if missing:
            raise ReportError(f"final case matrix lacks fields for {method}: {sorted(missing)}")
        values: dict[str, list[int]] = {}
        for field in ("exact", "proposal_plurality_exact", "override", "useful_override", "harmful_override"):
            key = f"{method}.{field}"
            try:
                observed = [int(row[key]) for row in rows]
            except ValueError as exc:
                raise ReportError(f"{key} contains a non-integer") from exc
            if any(value not in {0, 1} for value in observed):
                raise ReportError(f"{key} must be binary")
            values[field] = observed
        if any(
            useful and (not override or exact != 1 or plurality != 0)
            for exact, plurality, override, useful in zip(
                values["exact"], values["proposal_plurality_exact"], values["override"], values["useful_override"]
            )
        ):
            raise ReportError(f"{method} has an inconsistent useful override")
        if any(
            harmful and (not override or exact != 0 or plurality != 1)
            for exact, plurality, override, harmful in zip(
                values["exact"], values["proposal_plurality_exact"], values["override"], values["harmful_override"]
            )
        ):
            raise ReportError(f"{method} has an inconsistent harmful override")
        metrics[method] = {
            "exact_cases": sum(values["exact"]),
            "proposal_plurality_exact_cases": sum(values["proposal_plurality_exact"]),
            "overrides": sum(values["override"]),
            "useful_overrides": sum(values["useful_override"]),
            "harmful_overrides": sum(values["harmful_override"]),
        }
    return rows, metrics


def operational_stats(paths: list[Path]) -> dict[str, Any]:
    attempts: dict[str, list[dict[str, Any]]] = {}
    closures: dict[str, str] = {}
    statuses: Counter[str] = Counter()
    duration_ms = 0
    usage: Counter[str] = Counter()
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as exc:
            raise ReportError(f"missing required release input: {relative(path)}") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReportError(f"invalid JSONL at {relative(path)}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ReportError(f"non-object ledger row at {relative(path)}:{line_number}")
            job_id = str(row.get("job_id", ""))
            if not job_id:
                raise ReportError(f"ledger row lacks job_id at {relative(path)}:{line_number}")
            event_type = row.get("event_type")
            if event_type == "attempt":
                status = str(row.get("status", ""))
                if status not in {"valid_output", "schema_invalid", "infrastructure_failure", "protocol_violation"}:
                    raise ReportError(f"unknown attempt status {status!r}")
                attempts.setdefault(job_id, []).append(row)
                statuses[status] += 1
                duration_ms += exact_int(row.get("duration_ms"), "attempt duration_ms")
                observed_usage = row.get("usage") or {}
                if not isinstance(observed_usage, dict):
                    raise ReportError("attempt usage must be an object or null")
                for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
                    usage[key] += exact_int(observed_usage.get(key, 0) or 0, f"attempt {key}")
            elif event_type == "job_closed":
                outcome = str(row.get("outcome", ""))
                if outcome not in {"valid_output", "schema_invalid_exhausted", "protocol_violation", "infrastructure_exhausted"}:
                    raise ReportError(f"unknown terminal outcome {outcome!r}")
                if job_id in closures:
                    raise ReportError(f"duplicate closure for {job_id}")
                closures[job_id] = outcome
            else:
                raise ReportError(f"unknown ledger event type {event_type!r}")
    if set(attempts) != set(closures):
        raise ReportError("attempt ledgers do not contain exactly one closure per paid job")
    for job_id, events in attempts.items():
        numbers = [exact_int(row.get("attempt_number"), "attempt number", 1) for row in events]
        if numbers != list(range(1, len(events) + 1)):
            raise ReportError(f"non-contiguous attempts for {job_id}")
    return {
        "registered_call_identities": len(attempts),
        "total_attempts": sum(len(events) for events in attempts.values()),
        "retry_attempts": sum(len(events) - 1 for events in attempts.values()),
        "jobs_retried": sum(len(events) > 1 for events in attempts.values()),
        "attempt_status_counts": dict(sorted(statuses.items())),
        "malformed_attempts": statuses["schema_invalid"],
        "infrastructure_failure_attempts": statuses["infrastructure_failure"],
        "protocol_violation_attempts": statuses["protocol_violation"],
        "valid_output_jobs": sum(item == "valid_output" for item in closures.values()),
        "schema_invalid_exhausted_jobs": sum(item == "schema_invalid_exhausted" for item in closures.values()),
        "infrastructure_exhausted_jobs": sum(item == "infrastructure_exhausted" for item in closures.values()),
        "protocol_violation_jobs": sum(item == "protocol_violation" for item in closures.values()),
        "input_tokens_all_attempts": usage["input_tokens"],
        "cached_input_tokens_all_attempts": usage["cached_input_tokens"],
        "output_tokens_all_attempts": usage["output_tokens"],
        "total_tokens_all_attempts": usage["total_tokens"],
        "latency_ms_all_attempts": duration_ms,
    }


def source_receipts(paths: Iterable[Path]) -> list[dict[str, str]]:
    return [
        {"path": relative(path), "sha256": sha256_file(path)}
        for path in sorted(set(paths), key=relative)
    ]


def build_analysis() -> tuple[dict[str, Any], list[Path]]:
    source_paths: list[Path] = []
    search: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []

    initial_population = GENOMES / "round-00-parents.json"
    source_paths.append(initial_population)
    composition = [{"round": 0, "counts": population_system_counts(initial_population)}]

    for round_number in range(1, ROUNDS + 1):
        summary_path = RESULTS / "search" / f"round-{round_number:02d}" / "summary.json"
        matrix_path = RESULTS / "search" / f"round-{round_number:02d}" / "case_matrix.csv"
        survivors_path = GENOMES / f"round-{round_number:02d}-survivors.json"
        summary = load_json(summary_path)
        if exact_int(summary.get("n_cases"), f"round {round_number} n_cases") != 24:
            raise ReportError(f"round {round_number} must contain 24 fresh cases")
        methods = summary.get("methods")
        if not isinstance(methods, dict) or len(methods) != 12:
            raise ReportError(f"round {round_number} must score 12 candidates")
        exact_values = [exact_int(row.get("exact_cases"), "search exact cases") for row in methods.values()]
        best = max(exact_values)
        best_ids = sorted(method for method, row in methods.items() if int(row["exact_cases"]) == best)
        trajectory.append({
            "round": round_number,
            "fresh_cases": 24,
            "candidate_count": 12,
            "best_exact_cases": best,
            "best_accuracy": best / 24,
            "mean_exact_cases": sum(exact_values) / 12,
            "mean_accuracy": sum(exact_values) / (12 * 24),
            "best_genome_ids_by_exact_score": best_ids,
            "accepted_children": accepted_children(survivors_path),
        })
        composition.append({"round": round_number, "counts": population_system_counts(survivors_path)})
        search.append(summary)
        source_paths.extend((summary_path, matrix_path, survivors_path))

    validation_path = RESULTS / "validation" / "summary.json"
    validation_matrix_path = RESULTS / "validation" / "case_matrix.csv"
    champion_path = GENOMES / "champion-freeze.json"
    validation = load_json(validation_path)
    champion_freeze = load_json(champion_path)
    if exact_int(validation.get("n_cases"), "validation n_cases") != 72:
        raise ReportError("validation must contain 72 cases")
    champion = champion_freeze.get("champion_genome")
    founder = champion_freeze.get("best_founder_genome")
    if not isinstance(champion, dict) or not isinstance(founder, dict):
        raise ReportError("champion freeze lacks champion or best founder")
    champion_id = str(champion.get("genome_id"))
    founder_id = str(founder.get("genome_id"))
    champion_validation = method_row(validation, champion_id)
    source_paths.extend((validation_path, validation_matrix_path, champion_path))

    final_summary_path = RESULTS / "final" / "summary.json"
    final_comparisons_path = RESULTS / "final" / "comparisons.json"
    final_matrix_path = RESULTS / "final" / "case_matrix.csv"
    final = load_json(final_summary_path)
    comparisons = load_json(final_comparisons_path)
    if exact_int(final.get("n_cases"), "final n_cases") != FINAL_N:
        raise ReportError(f"hidden final must contain {FINAL_N} cases")
    if set(final.get("methods", {})) != set(FINAL_METHODS):
        raise ReportError("hidden final must contain exactly the four registered methods")
    primary = comparisons.get("primary")
    if not isinstance(primary, dict) or exact_int(primary.get("n"), "primary paired n") != FINAL_N:
        raise ReportError("primary comparison must pair all 96 hidden-final cases")
    if primary.get("left") != "evolved_champion" or primary.get("right") != "diversified_vote10":
        raise ReportError("primary comparison is not champion minus diversified Vote10")
    estimate = exact_float(primary.get("estimate"), "primary estimate")
    primary_ci = as_ci(primary.get("ci95"), "primary ci95")
    includes_zero = primary_ci[0] <= 0 <= primary_ci[1]
    superiority = bool(estimate > 0 and primary_ci[0] > 0)
    if includes_zero and bool(primary.get("superiority_supported")):
        raise ReportError("scorer claims superiority although the paired interval includes zero")
    matrix_rows, matrix_metrics = final_matrix(final_matrix_path, FINAL_METHODS)
    source_paths.extend((final_summary_path, final_comparisons_path, final_matrix_path))

    method_results: dict[str, Any] = {}
    for method in FINAL_METHODS:
        row = method_row(final, method)
        matrix = matrix_metrics[method]
        summary_exact = exact_int(row.get("exact_cases"), f"{method} exact_cases")
        if summary_exact != matrix["exact_cases"]:
            raise ReportError(f"{method} exact count differs between summary and case matrix")
        summary_accuracy = exact_float(row.get("exact_accuracy"), f"{method} exact_accuracy")
        if not math.isclose(summary_accuracy, summary_exact / FINAL_N, rel_tol=0, abs_tol=1e-12):
            raise ReportError(f"{method} exact accuracy differs from its exact count")
        for summary_key, matrix_key in (
            ("overrides", "overrides"),
            ("useful_overrides", "useful_overrides"),
            ("harmful_overrides", "harmful_overrides"),
        ):
            if exact_int(row.get(summary_key), f"{method} {summary_key}") != matrix[matrix_key]:
                raise ReportError(f"{method} {summary_key} differs between summary and case matrix")
        method_results[method] = {
            "label": METHOD_LABELS[method],
            "exact_cases": summary_exact,
            "n": FINAL_N,
            "exact_accuracy": summary_accuracy,
            "exact_ci95": as_ci(row.get("exact_ci95"), f"{method} exact_ci95"),
            "term_correct": exact_int(row.get("term_correct"), f"{method} term_correct"),
            "term_count": exact_int(row.get("term_count"), f"{method} term_count"),
            "term_accuracy": exact_float(row.get("term_accuracy"), f"{method} term_accuracy"),
            "proposal_plurality_exact_cases": matrix["proposal_plurality_exact_cases"],
            "proposal_plurality_accuracy": matrix["proposal_plurality_exact_cases"] / FINAL_N,
            "overrides": matrix["overrides"],
            "useful_overrides": matrix["useful_overrides"],
            "harmful_overrides": matrix["harmful_overrides"],
            "net_override_value": matrix["useful_overrides"] - matrix["harmful_overrides"],
            "completed_calls": exact_int(row.get("completed_calls"), f"{method} completed_calls"),
            "input_tokens": exact_float(row.get("input_tokens", 0), f"{method} input_tokens"),
            "output_tokens": exact_float(row.get("output_tokens", 0), f"{method} output_tokens"),
            "latency_ms": exact_float(row.get("latency_ms", 0), f"{method} latency_ms"),
            "malformed_calls": exact_int(row.get("malformed_calls", 0), f"{method} malformed_calls"),
        }

    comparison_rows = comparisons.get("comparisons")
    expected_pairs = (
        ("evolved_champion", "diversified_vote10"),
        ("evolved_champion", "best_initial_founder"),
        ("evolved_champion", "generalist_vote10"),
    )
    if not isinstance(comparison_rows, list) or len(comparison_rows) != len(expected_pairs):
        raise ReportError("hidden final must contain the three registered paired comparisons")
    paired: list[dict[str, Any]] = []
    if primary != comparison_rows[0]:
        raise ReportError("primary comparison differs from the first registered comparison")
    for item, expected_pair in zip(comparison_rows, expected_pairs):
        if not isinstance(item, dict):
            raise ReportError("invalid paired comparison")
        left, right = expected_pair
        if item.get("left") != left or item.get("right") != right:
            raise ReportError(f"registered comparison must be {left} minus {right}")
        if exact_int(item.get("n"), "paired comparison n") != FINAL_N:
            raise ReportError("every paired comparison must use all 96 final cases")
        left_scores = [int(row[f"{left}.exact"]) for row in matrix_rows]
        right_scores = [int(row[f"{right}.exact"]) for row in matrix_rows]
        observed = {
            "left_only_wins": sum(a == 1 and b == 0 for a, b in zip(left_scores, right_scores)),
            "right_only_wins": sum(a == 0 and b == 1 for a, b in zip(left_scores, right_scores)),
            "both_correct": sum(a == 1 and b == 1 for a, b in zip(left_scores, right_scores)),
            "both_wrong": sum(a == 0 and b == 0 for a, b in zip(left_scores, right_scores)),
        }
        for key, value in observed.items():
            if exact_int(item.get(key), key) != value:
                raise ReportError(f"{item.get('contrast')} {key} differs from the case matrix")
        ci = as_ci(item.get("ci95"), "comparison ci95")
        diff = exact_float(item.get("estimate"), "comparison estimate")
        matrix_diff = sum(a - b for a, b in zip(left_scores, right_scores)) / FINAL_N
        if not math.isclose(diff, matrix_diff, rel_tol=0, abs_tol=1e-12):
            raise ReportError(f"{item.get('contrast')} estimate differs from the case matrix")
        paired.append({
            "contrast": str(item.get("contrast")),
            "left": str(item.get("left")),
            "right": str(item.get("right")),
            "estimate": diff,
            "ci95": ci,
            "interval_includes_zero": ci[0] <= 0 <= ci[1],
            "superiority_supported": bool(diff > 0 and ci[0] > 0),
            "left_only_wins": exact_int(item.get("left_only_wins"), "left_only_wins"),
            "right_only_wins": exact_int(item.get("right_only_wins"), "right_only_wins"),
            "both_correct": exact_int(item.get("both_correct"), "both_correct"),
            "both_wrong": exact_int(item.get("both_wrong"), "both_wrong"),
            "mcnemar_exact_two_sided_p": exact_float(item.get("mcnemar", {}).get("p_value"), "McNemar p"),
        })

    attempt_paths = [RUNS / "search" / f"round-{number:02d}" / "runner" / "attempts.jsonl" for number in range(1, 9)]
    attempt_paths.append(RUNS / "validation" / "runner" / "attempts.jsonl")
    attempt_paths.extend(
        RUNS / "final" / label / "runner" / "attempts.jsonl"
        for label in ("evolved_champion", "best_initial_founder", "generalist_vote10", "diversified_vote10")
    )
    operations = operational_stats(attempt_paths)
    if operations["registered_call_identities"] != 2600:
        raise ReportError(
            f"operational ledger has {operations['registered_call_identities']} logical call identities, expected 2600"
        )
    source_paths.extend(attempt_paths)

    if superiority:
        primary_finding = (
            f"The evolved champion led diversified Vote10 by {pp(estimate)}, and the paired 95% interval "
            f"[{pp(primary_ci[0])}, {pp(primary_ci[1])}] excluded zero."
        )
    elif includes_zero:
        primary_finding = (
            f"The evolved champion differed from diversified Vote10 by {pp(estimate)}, but the paired "
            f"95% interval [{pp(primary_ci[0])}, {pp(primary_ci[1])}] included zero, so superiority was not established."
        )
    else:
        primary_finding = (
            f"The evolved champion trailed diversified Vote10 by {100 * abs(estimate):.1f} pp; the paired 95% interval "
            f"[{pp(primary_ci[0])}, {pp(primary_ci[1])}] excluded zero. Champion superiority was not established."
        )

    analysis: dict[str, Any] = {
        "schema_version": "experiment-04-analysis-v1",
        "headline": {
            "finding": primary_finding,
            "primary_contrast": "evolved_champion minus diversified_vote10",
            "estimate": estimate,
            "ci95": primary_ci,
            "interval_includes_zero": includes_zero,
            "superiority_supported": superiority,
        },
        "experiment": {
            "question": "Can symbolic evolution improve how ten Luna Light calls decide together?",
            "model": "gpt-5.6-luna",
            "public_reasoning_label": "Light reasoning",
            "provider_reasoning_effort": "low",
            "service_tier": "Standard",
            "fixed_rounds": 8,
            "early_stopping": False,
            "registered_logical_call_identities": 2600,
            "actual_model_attempts": operations["total_attempts"],
            "search_cases": 192,
            "validation_cases": 72,
            "hidden_final_cases": 96,
        },
        "evolution": {
            "round_trajectory": trajectory,
            "survivor_decision_system_composition": composition,
            "accepted_children_total": sum(item["accepted_children"] for item in trajectory),
            "champion": {
                "genome_id": champion_id,
                "decision_system_id": champion["genes"]["decision_system_id"],
                "judge_policy_id": champion["genes"]["judge_policy_id"],
                "worker_lens_ids": champion["genes"]["worker_lens_ids"],
                "validation_exact_cases": exact_int(champion_validation.get("exact_cases"), "champion validation exact"),
                "validation_n": 72,
                "validation_accuracy": exact_float(champion_validation.get("exact_accuracy"), "champion validation accuracy"),
            },
            "best_initial_founder": {
                "genome_id": founder_id,
                "decision_system_id": founder["genes"]["decision_system_id"],
                "judge_policy_id": founder["genes"]["judge_policy_id"],
            },
            "interpretation": (
                "Each round used a different balanced 24-case sample. The trajectory shows the observed search process, "
                "not repeated measurement on one fixed benchmark. Validation alone selected the champion."
            ),
        },
        "hidden_final": {
            "methods": method_results,
            "paired_comparisons": paired,
            "primary_case_overlap": {
                "champion_only": exact_int(primary.get("left_only_wins"), "primary left wins"),
                "diversified_vote10_only": exact_int(primary.get("right_only_wins"), "primary right wins"),
                "both_correct": exact_int(primary.get("both_correct"), "primary both correct"),
                "both_wrong": exact_int(primary.get("both_wrong"), "primary both wrong"),
            },
        },
        "operations": operations,
        "artifact_notes": [
            {
                "severity": "warning",
                "field": "methods.*.fitness_key_without_hash",
                "statement": (
                    "Generated score summaries retain an obsolete four-part convenience field from Experiment 03. "
                    "The authoritative five-part protocol_fitness_key, genome_scores, freezes, and selection receipts "
                    "are internally consistent and drove every selection, so this label defect does not change results."
                ),
            }
        ],
        "conclusion": {
            "superiority_claim_allowed": superiority,
            "statement": primary_finding,
            "boundary": (
                "This is one Luna Light condition, one synthetic sequence grammar, six bounded decision systems, "
                "and one deterministic evolutionary schedule. It does not establish a universal orchestration rule."
            ),
        },
    }
    analysis["source_artifacts"] = source_receipts(source_paths)
    return analysis, source_paths


def markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# Experiment 04: Evolving the Decider",
        "",
        analysis["headline"]["finding"],
        "",
        "## What was tested",
        "",
        "Six decision systems competed under the same budget: ten Luna Light calls per 12-case block. "
        "The genome could change the worker lenses, judge policy, and whether the group used plain voting, "
        "one judge, gated criticism, two judges, verification, or deliberation. The search ran all eight "
        "registered rounds with no early stopping.",
        "",
        "The registered budget was 1,920 logical call identities for search, 360 for validation, and 320 for the hidden final, for 2,600 logical call identities total. Registered retries are counted separately as model attempts.",
        "",
        "## Eight-round search",
        "",
        "| Round | Best exact | Candidate mean | Children accepted | Survivor decision systems |",
        "|---:|---:|---:|---:|---|",
    ]
    compositions = {item["round"]: item["counts"] for item in analysis["evolution"]["survivor_decision_system_composition"]}
    for item in analysis["evolution"]["round_trajectory"]:
        counts = compositions[item["round"]]
        systems = ", ".join(
            f"{SYSTEM_LABELS[system]} x{counts[system]}" for system in SYSTEMS if counts[system]
        )
        lines.append(
            f"| {item['round']} | {item['best_exact_cases']}/24 ({pct(item['best_accuracy'])}) | "
            f"{item['mean_exact_cases']:.2f}/24 ({pct(item['mean_accuracy'])}) | "
            f"{item['accepted_children']}/6 | {systems} |"
        )
    champion = analysis["evolution"]["champion"]
    founder = analysis["evolution"]["best_initial_founder"]
    lines.extend([
        "",
        analysis["evolution"]["interpretation"],
        "",
        f"Across all rounds, {analysis['evolution']['accepted_children_total']} of 48 child challenges replaced their parents.",
        "",
        "## Validation selection",
        "",
        f"Validation selected `{champion['genome_id']}` with {champion['validation_exact_cases']}/72 exact "
        f"({pct(champion['validation_accuracy'])}). Its decision system was `{champion['decision_system_id']}` "
        f"with judge policy `{champion['judge_policy_id']}`.",
        "",
        f"The frozen best initial founder was `{founder['genome_id']}`, using `{founder['decision_system_id']}`.",
        "",
        "## Hidden final",
        "",
        "All four methods used the same ten-call budget on the same 96 hidden cases.",
        "",
        "| Method | Exact | 95% interval | Proposer plurality | Overrides | Useful | Harmful | Calls | Tokens in/out | Latency | Malformed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for method in FINAL_METHODS:
        row = analysis["hidden_final"]["methods"][method]
        low, high = row["exact_ci95"]
        lines.append(
            f"| {row['label']} | {row['exact_cases']}/96 ({pct(row['exact_accuracy'])}) | "
            f"{pct(low)} to {pct(high)} | {row['proposal_plurality_exact_cases']}/96 "
            f"({pct(row['proposal_plurality_accuracy'])}) | {row['overrides']} | "
            f"{row['useful_overrides']} | {row['harmful_overrides']} | {row['completed_calls']} | "
            f"{int(row['input_tokens']):,}/{int(row['output_tokens']):,} | "
            f"{row['latency_ms'] / 1000:.1f}s | {row['malformed_calls']} |"
        )
    lines.extend([
        "",
        "## Paired comparisons",
        "",
        "| Contrast | Difference | 95% interval | Only-left / only-right | McNemar p | Conclusion |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for row in analysis["hidden_final"]["paired_comparisons"]:
        low, high = row["ci95"]
        conclusion = "superiority supported" if row["superiority_supported"] else "superiority not established"
        lines.append(
            f"| {row['contrast']} | {pp(row['estimate'])} | {pp(low)} to {pp(high)} | "
            f"{row['left_only_wins']} / {row['right_only_wins']} | "
            f"{row['mcnemar_exact_two_sided_p']:.4f} | {conclusion} |"
        )
    operations = analysis["operations"]
    lines.extend([
        "",
        "## Operational record",
        "",
        f"The ledger contains {operations['registered_call_identities']:,} logical call identities and "
        f"{operations['total_attempts']:,} actual model attempts. It records "
        f"{operations['retry_attempts']} retry attempts across {operations['jobs_retried']} jobs, "
        f"{operations['malformed_attempts']} malformed attempts, "
        f"{operations['infrastructure_failure_attempts']} infrastructure-failure attempts, "
        f"{operations['schema_invalid_exhausted_jobs']} schema-invalid exhausted jobs, and "
        f"{operations['protocol_violation_jobs']} protocol-violation jobs. Across all attempts, the runner recorded "
        f"{operations['input_tokens_all_attempts']:,} input tokens, {operations['output_tokens_all_attempts']:,} output tokens, "
        f"and {operations['latency_ms_all_attempts'] / 1000:.1f} seconds of summed call latency.",
        "",
        "## Artifact note",
        "",
        analysis["artifact_notes"][0]["statement"],
        "",
        "## Interpretation",
        "",
        analysis["conclusion"]["statement"],
        "",
        "The evolutionary trajectory is evidence that the controller explored and retained different decision systems. "
        "It is not, by itself, evidence that evolution generalized. The hidden paired comparison is the relevant test.",
        "",
        analysis["conclusion"]["boundary"],
        "",
        "## Charts",
        "",
        "- `../../images/final-exact-accuracy.svg`",
        "- `../../images/eight-round-trajectory.svg`",
        "- `../../images/decision-system-evolution.svg`",
        "",
    ])
    result = "\n".join(lines)
    if "\u2013" in result or "\u2014" in result:
        raise ReportError("analysis Markdown contains forbidden dash punctuation")
    return result


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


class SVG:
    def __init__(self, width: int, height: int, title: str, description: str, digest: str):
        self.width = width
        self.height = height
        self.parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">',
            f'<title id="chart-title">{esc(title)}</title>',
            f'<desc id="chart-desc">{esc(description)}</desc>',
            f'<metadata>source-digest:{digest}</metadata>',
            "<style>text{font-family:Inter,Arial,sans-serif;fill:#152238}"
            ".title{font-size:28px;font-weight:750}.subtitle{font-size:14px;fill:#526174}"
            ".axis{font-size:12px;fill:#526174}.label{font-size:13px;font-weight:650}"
            ".value{font-size:12px;font-weight:750}.note{font-size:11px;fill:#526174}"
            ".legend{font-size:12px;font-weight:650}</style>",
            f'<rect width="{width}" height="{height}" fill="{COLORS["white"]}"/>',
        ]

    @staticmethod
    def attrs(values: dict[str, Any]) -> str:
        return " ".join(f'{key.replace("_", "-")}="{esc(value)}"' for key, value in values.items())

    def rect(self, x: float, y: float, width: float, height: float, **attrs: Any) -> None:
        self.parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(width, 0):.2f}" '
            f'height="{max(height, 0):.2f}" {self.attrs(attrs)}/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, **attrs: Any) -> None:
        self.parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {self.attrs(attrs)}/>'
        )

    def circle(self, x: float, y: float, radius: float, **attrs: Any) -> None:
        self.parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" {self.attrs(attrs)}/>')

    def polyline(self, points: Iterable[tuple[float, float]], **attrs: Any) -> None:
        joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.parts.append(f'<polyline points="{joined}" {self.attrs(attrs)}/>')

    def text(self, x: float, y: float, value: Any, css: str = "axis", anchor: str = "start", **attrs: Any) -> None:
        self.parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" class="{css}" text-anchor="{anchor}" '
            f'{self.attrs(attrs)}>{esc(value)}</text>'
        )

    def finish(self) -> str:
        document = "\n".join(self.parts + ["</svg>", ""])
        if "\u2013" in document or "\u2014" in document:
            raise ReportError("SVG contains forbidden dash punctuation")
        ET.fromstring(document)
        return document


def chart_heading(svg: SVG, title: str, subtitle: str, source: str) -> None:
    svg.text(62, 48, title, "title")
    svg.text(62, 75, subtitle, "subtitle")
    svg.text(62, svg.height - 20, f"Source: {source}", "note")


def accuracy_axis(svg: SVG, left: float, top: float, width: float, height: float, maximum: float = 1.0) -> None:
    for step in range(6):
        value = maximum * step / 5
        y = top + height * (1 - value / maximum)
        svg.line(left, y, left + width, y, stroke=COLORS["grid"], stroke_width=1)
        svg.text(left - 12, y + 4, pct(value), "axis", "end")
    svg.line(left, top, left, top + height, stroke=COLORS["ink"], stroke_width=1.2)
    svg.line(left, top + height, left + width, top + height, stroke=COLORS["ink"], stroke_width=1.2)


def final_accuracy_svg(analysis: dict[str, Any], digest: str) -> str:
    svg = SVG(1200, 720, "Hidden-final exact accuracy", "Four ten-call methods on 96 paired cases.", digest)
    chart_heading(
        svg,
        "Hidden-final exact accuracy",
        "Same 96 paired cases; whiskers show block-stratified 95% intervals",
        "results/final/summary.json and comparisons.json",
    )
    left, top, width, height = 120, 140, 1010, 400
    accuracy_axis(svg, left, top, width, height)
    slot = width / 4
    method_colors = (COLORS["gray"], COLORS["blue"], COLORS["gold"], COLORS["green"])
    for index, (method, color) in enumerate(zip(FINAL_METHODS, method_colors)):
        row = analysis["hidden_final"]["methods"][method]
        center = left + slot * (index + 0.5)
        estimate = row["exact_accuracy"]
        low, high = row["exact_ci95"]
        y = top + height * (1 - estimate)
        high_y, low_y = top + height * (1 - high), top + height * (1 - low)
        svg.rect(center - 48, y, 96, top + height - y, fill=color, rx=5)
        svg.line(center, high_y, center, low_y, stroke=COLORS["ink"], stroke_width=2.5)
        svg.line(center - 13, high_y, center + 13, high_y, stroke=COLORS["ink"], stroke_width=2.5)
        svg.line(center - 13, low_y, center + 13, low_y, stroke=COLORS["ink"], stroke_width=2.5)
        svg.circle(center, y, 5, fill=COLORS["ink"])
        svg.text(center, high_y - 12, pct(estimate), "value", "middle")
        svg.text(center, top + height + 29, row["label"], "label", "middle")
        svg.text(center, top + height + 50, f"{row['exact_cases']}/96 exact", "axis", "middle")
    primary = analysis["headline"]
    note = (
        f"Champion minus diversified Vote10: {pp(primary['estimate'])}; 95% interval "
        f"[{pp(primary['ci95'][0])}, {pp(primary['ci95'][1])}]. "
        + ("Superiority supported." if primary["superiority_supported"] else "Superiority not established.")
    )
    svg.rect(185, 626, 830, 42, fill=COLORS["pale"], rx=8)
    svg.text(600, 652, note, "label", "middle")
    return svg.finish()


def trajectory_svg(analysis: dict[str, Any], digest: str) -> str:
    trajectory = analysis["evolution"]["round_trajectory"]
    svg = SVG(1200, 720, "Eight-round search trajectory", "Best and mean exact accuracy on fresh cases by round.", digest)
    chart_heading(
        svg,
        "Eight fixed evolutionary rounds",
        "Each round used a fresh balanced 24-case sample; labels show accepted child challenges",
        "results/search/round-01 through round-08",
    )
    left, top, width, height = 120, 140, 1010, 410
    accuracy_axis(svg, left, top, width, height)
    slot = width / 8
    xs = [left + slot * (index + 0.5) for index in range(8)]
    best_points = [(x, top + height * (1 - item["best_accuracy"])) for x, item in zip(xs, trajectory)]
    mean_points = [(x, top + height * (1 - item["mean_accuracy"])) for x, item in zip(xs, trajectory)]
    svg.polyline(best_points, fill="none", stroke=COLORS["green"], stroke_width=3.5)
    svg.polyline(mean_points, fill="none", stroke=COLORS["blue"], stroke_width=3.5)
    for x, item, (_, best_y), (_, mean_y) in zip(xs, trajectory, best_points, mean_points):
        svg.circle(x, best_y, 7, fill=COLORS["green"], stroke=COLORS["white"], stroke_width=2)
        svg.circle(x, mean_y, 6, fill=COLORS["blue"], stroke=COLORS["white"], stroke_width=2)
        svg.text(x, best_y - 13, pct(item["best_accuracy"]), "value", "middle")
        svg.text(x, top + height + 27, f"Round {item['round']}", "label", "middle")
        svg.text(x, top + height + 47, f"{item['accepted_children']}/6 accepted", "axis", "middle")
    svg.line(795, 104, 829, 104, stroke=COLORS["green"], stroke_width=4)
    svg.text(840, 109, "Best candidate", "legend")
    svg.line(956, 104, 990, 104, stroke=COLORS["blue"], stroke_width=4)
    svg.text(1001, 109, "Candidate mean", "legend")
    svg.text(
        600,
        630,
        "Connected points describe the search path across different samples, not repeated tests on one fixed set.",
        "note",
        "middle",
    )
    return svg.finish()


def composition_svg(analysis: dict[str, Any], digest: str) -> str:
    composition = analysis["evolution"]["survivor_decision_system_composition"]
    svg = SVG(1200, 740, "Decision-system evolution", "Composition of six persistent survivor slots across eight rounds.", digest)
    chart_heading(
        svg,
        "How the six survivor slots changed",
        "Founders at round 0, then survivor composition after each paired replacement round",
        "genomes/round-00-parents.json and round-01 through round-08 survivors",
    )
    left, top, width, height = 125, 145, 1000, 390
    slot = width / 9
    bar_width = 66
    for count in range(7):
        y = top + height * (1 - count / 6)
        svg.line(left, y, left + width, y, stroke=COLORS["grid"], stroke_width=1)
        svg.text(left - 13, y + 4, str(count), "axis", "end")
    for index, item in enumerate(composition):
        x = left + slot * (index + 0.5) - bar_width / 2
        y = top + height
        for system in SYSTEMS:
            count = item["counts"][system]
            segment = height * count / 6
            y -= segment
            if count:
                svg.rect(x, y, bar_width, segment, fill=SYSTEM_COLORS[system], stroke=COLORS["white"], stroke_width=1)
        label = "Founders" if item["round"] == 0 else f"Round {item['round']}"
        svg.text(x + bar_width / 2, top + height + 28, label, "label", "middle")
    legend_y = 596
    for index, system in enumerate(SYSTEMS):
        column, row = index % 3, index // 3
        x, y = 145 + column * 345, legend_y + row * 35
        svg.rect(x, y - 13, 18, 18, fill=SYSTEM_COLORS[system], rx=3)
        svg.text(x + 28, y + 1, SYSTEM_LABELS[system], "legend")
    svg.text(84, top + height / 2, "Survivor slots", "axis", "middle", transform=f"rotate(-90 84 {top + height / 2})")
    return svg.finish()


def digest_for_charts(analysis: dict[str, Any]) -> str:
    reduced = dict(analysis)
    reduced.pop("source_artifacts", None)
    return hashlib.sha256(json.dumps(reduced, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def documents() -> tuple[dict[str, str], dict[str, str]]:
    analysis, _ = build_analysis()
    analysis_text = canonical_json(analysis)
    markdown_text = markdown(analysis)
    digest = digest_for_charts(analysis)
    charts = {
        "final-exact-accuracy.svg": final_accuracy_svg(analysis, digest),
        "eight-round-trajectory.svg": trajectory_svg(analysis, digest),
        "decision-system-evolution.svg": composition_svg(analysis, digest),
    }
    return {"analysis.json": analysis_text, "analysis.md": markdown_text}, charts


def validate_text(path: Path, expected: str, xml: bool = False) -> None:
    if not path.exists():
        raise ReportError(f"missing generated artifact: {path.name}")
    actual = path.read_text(encoding="utf-8")
    if xml:
        ET.fromstring(actual)
    if actual != expected:
        raise ReportError(f"stale or non-deterministic generated artifact: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="rebuild in memory and byte-check existing outputs")
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    args = parser.parse_args(argv)
    reports, charts = documents()
    if args.check:
        for name, content in reports.items():
            validate_text(RESULTS / name, content)
        for name, content in charts.items():
            validate_text(args.images_dir / name, content, xml=True)
        print(f"validated {len(reports)} reports and {len(charts)} deterministic SVG charts")
        return 0

    RESULTS.mkdir(parents=True, exist_ok=True)
    args.images_dir.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        (RESULTS / name).write_text(content, encoding="utf-8")
        print(RESULTS / name)
    for name, content in charts.items():
        path = args.images_dir / name
        path.write_text(content, encoding="utf-8")
        ET.fromstring(content)
        print(path)
    for name, content in reports.items():
        validate_text(RESULTS / name, content)
    for name, content in charts.items():
        validate_text(args.images_dir / name, content, xml=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ReportError, ValueError) as exc:
        print(f"build_report.py: error: {exc}", file=sys.stderr)
        raise SystemExit(2)
