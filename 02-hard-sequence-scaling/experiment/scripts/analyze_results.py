#!/usr/bin/env python3
"""Deterministic statistical analysis for Experiment 02 scored results."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "experiment-02-analysis-v1"
DEFAULT_REPLICATES = 50_000
DEFAULT_SEED = 20260713
SIGN_FLIP_ASSIGNMENTS = 100_000
EQUIVALENCE_MARGIN = 0.10
METHOD_ORDER = ("Direct expected", "Vote10", "Swarm10", "Vote20", "Tournament20")


class AnalysisError(ValueError):
    pass


def percentile(values: list[float], probability: float) -> float:
    """R-7/NumPy-linear percentile, implemented without dependencies."""
    if not values:
        raise AnalysisError("percentile of empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def interval(values: list[float], level: float) -> list[float]:
    alpha = (1.0 - level) / 2.0
    return [percentile(values, alpha), percentile(values, 1.0 - alpha)]


def exact_mcnemar(left: Iterable[Any], right: Iterable[Any]) -> dict[str, Any]:
    """Two-sided exact McNemar test using the conditional binomial law."""
    pairs = [(bool(a), bool(b)) for a, b in zip(left, right)]
    left_only = sum(a and not b for a, b in pairs)
    right_only = sum(b and not a for a, b in pairs)
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(0, min(left_only, right_only) + 1))
        p_value = min(1.0, 2.0 * tail / (2 ** discordant))
    return {
        "left_only": left_only,
        "right_only": right_only,
        "discordant": discordant,
        "p_value": p_value,
        "test": "exact two-sided McNemar",
    }


def holm_adjust(items: Iterable[tuple[str, float]]) -> dict[str, float]:
    """Holm step-down family-wise p-value adjustment."""
    ordered = sorted(((key, float(value)) for key, value in items), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[key] = running
    return adjusted


def paired_sign_flip(
    differences: Iterable[float], *, seed: int = DEFAULT_SEED,
    assignments: int = SIGN_FLIP_ASSIGNMENTS,
) -> dict[str, Any]:
    """Two-sided paired sign-flip permutation test with frozen randomness."""
    nonzero = [float(value) for value in differences if float(value) != 0.0]
    observed = abs(sum(nonzero))
    if not nonzero:
        return {"p_value": 1.0, "test": "paired sign-flip", "assignments": 1, "exact": True}
    if len(nonzero) <= 20:
        total = 1 << len(nonzero)
        extreme = 0
        for mask in range(total):
            statistic = sum(value if mask & (1 << index) else -value for index, value in enumerate(nonzero))
            extreme += abs(statistic) >= observed - 1e-15
        p_value = extreme / total
        return {"p_value": p_value, "test": "paired sign-flip", "assignments": total, "exact": True}
    if assignments < 100_000:
        raise AnalysisError("random sign-flip analysis requires at least 100,000 assignments")
    rng = random.Random(seed)
    extreme = 0
    for _ in range(assignments):
        statistic = sum(value if rng.getrandbits(1) else -value for value in nonzero)
        extreme += abs(statistic) >= observed - 1e-15
    return {
        "p_value": (extreme + 1) / (assignments + 1),
        "test": "paired sign-flip", "assignments": assignments,
        "exact": False, "seed": seed,
    }


def _is_binary(values: Iterable[Any]) -> bool:
    values = list(values)
    return bool(values) and all(isinstance(value, (bool, int)) and value in (0, 1) for value in values)


def _method_sort_key(method: str) -> tuple[int, str]:
    return (METHOD_ORDER.index(method), method) if method in METHOD_ORDER else (len(METHOD_ORDER), method)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _method_metrics(method: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    exact = _numeric(method.get("exact"))
    term = _numeric(method.get("term_accuracy"))
    fmt = _numeric(method.get("format_compliant"))
    if exact is not None:
        metrics["exact_accuracy"] = exact
    if term is not None:
        metrics["term_accuracy"] = term
    if fmt is not None:
        metrics["format_rate"] = fmt
    per_term = method.get("per_term")
    if isinstance(per_term, list) and len(per_term) == 5:
        for index, value in enumerate(per_term, start=1):
            numeric = _numeric(value)
            if numeric is not None:
                metrics[f"term_{index}_accuracy"] = numeric
    cost = method.get("cost")
    if isinstance(cost, dict):
        for key, value in cost.items():
            numeric = _numeric(value)
            if numeric is not None:
                metrics[f"cost.{key}"] = numeric
    return metrics


def _case_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        for method, result in case.get("methods", {}).items():
            if not isinstance(result, dict):
                continue
            rows.append({
                "case_id": str(case.get("case_id")),
                "block": str(case.get("block", "UNSPECIFIED")),
                "reasoning": str(case.get("reasoning", "Light reasoning")),
                "method": method,
                "deployment_calls": int(result.get("deployment_calls", 1)),
                "metrics": _method_metrics(result),
            })
    return rows


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else float("nan")


def stratified_indices(cases: list[dict[str, Any]], rng: random.Random) -> list[int]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(cases):
        blocks[str(case["block"])].append(index)
    sampled: list[int] = []
    for block in sorted(blocks):
        indices = blocks[block]
        sampled.extend(rng.choice(indices) for _ in indices)
    return sampled


def stratified_bootstrap(
    cases: list[dict[str, Any]],
    statistic: Callable[[list[dict[str, Any]]], float],
    *,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> list[float]:
    rng = random.Random(seed)
    distribution: list[float] = []
    for _ in range(replicates):
        indices = stratified_indices(cases, rng)
        distribution.append(float(statistic([cases[index] for index in indices])))
    return distribution


def _build_case_matrix(cases: list[dict[str, Any]], reasoning: str) -> list[dict[str, Any]]:
    selected = [case for case in cases if str(case.get("reasoning")) == reasoning]
    matrix: list[dict[str, Any]] = []
    for case in sorted(selected, key=lambda row: (str(row.get("block")), str(row.get("case_id")))):
        methods = {
            name: _method_metrics(result)
            for name, result in case.get("methods", {}).items()
            if isinstance(result, dict)
        }
        matrix.append({"case_id": str(case["case_id"]), "block": str(case["block"]), "methods": methods, "raw": case})
    return matrix


def _bootstrap_distributions(
    matrix: list[dict[str, Any]], methods: list[str], metrics: list[str], replicates: int, seed: int
) -> dict[tuple[str, str], list[float]]:
    rng = random.Random(seed)
    output = {(method, metric): [] for method in methods for metric in metrics}
    for _ in range(replicates):
        indices = stratified_indices(matrix, rng)
        for method in methods:
            for metric in metrics:
                values = [
                    matrix[index]["methods"][method][metric]
                    for index in indices
                    if method in matrix[index]["methods"] and metric in matrix[index]["methods"][method]
                ]
                if values:
                    output[(method, metric)].append(statistics.fmean(values))
    return output


def _summary(estimate: float, distribution: list[float]) -> dict[str, Any]:
    return {"estimate": estimate, "ci95": interval(distribution, 0.95)}


def _comparison_key(reasoning: str, left: str, right: str) -> str:
    return f"{reasoning}|{left}|{right}"


def _cross_reasoning_matrix(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = str(case["case_id"])
        row = joined.setdefault(case_id, {"case_id": case_id, "block": str(case["block"]), "values": {}})
        if row["block"] != str(case["block"]):
            raise AnalysisError(f"case {case_id} has inconsistent blocks across reasoning levels")
        row["values"][str(case["reasoning"])] = {
            method: _method_metrics(result).get("exact_accuracy")
            for method, result in case.get("methods", {}).items()
            if isinstance(result, dict) and "exact_accuracy" in _method_metrics(result)
        }
    return sorted(joined.values(), key=lambda row: (row["block"], row["case_id"]))


def _effect_summary(
    matrix: list[dict[str, Any]], effect: Callable[[dict[str, Any]], float],
    *, replicates: int, seed: int,
) -> tuple[list[float], list[float]]:
    differences = [float(effect(case)) for case in matrix]
    distribution = stratified_bootstrap(
        matrix, lambda sample: statistics.fmean(effect(case) for case in sample),
        replicates=replicates, seed=seed,
    )
    return differences, distribution


def _classification(ci95: list[float], ci90: list[float]) -> str:
    if ci95[0] > 0.0:
        return "right superior"
    if ci90[0] > -EQUIVALENCE_MARGIN and ci90[1] < EQUIVALENCE_MARGIN:
        return "practically equivalent"
    return "inconclusive"


def _confirmatory_analysis(cases: list[dict[str, Any]], replicates: int, seed: int) -> dict[str, Any]:
    matrix = _cross_reasoning_matrix(cases)
    required_reasonings = {"Light reasoning", "Medium reasoning"}
    if not matrix or any(not required_reasonings.issubset(case["values"]) for case in matrix):
        return {"primary": None, "secondary": [], "reasoning_over_routing": None,
                "warning": "complete Light reasoning and Medium reasoning pairs unavailable"}

    def within(reasoning: str, left: str, right: str) -> Callable[[dict[str, Any]], float]:
        return lambda case: case["values"][reasoning][right] - case["values"][reasoning][left]

    def between(method: str) -> Callable[[dict[str, Any]], float]:
        return lambda case: case["values"]["Medium reasoning"][method] - case["values"]["Light reasoning"][method]

    multi = ("Vote10", "Swarm10", "Vote20", "Tournament20")

    def reasoning_lift(case: dict[str, Any]) -> float:
        return statistics.fmean(
            case["values"]["Medium reasoning"][method] - case["values"]["Light reasoning"][method]
            for method in multi
        )

    def routing_lift(case: dict[str, Any]) -> float:
        return statistics.fmean((
            case["values"]["Light reasoning"]["Swarm10"] - case["values"]["Light reasoning"]["Vote10"],
            case["values"]["Medium reasoning"]["Swarm10"] - case["values"]["Medium reasoning"]["Vote10"],
            case["values"]["Light reasoning"]["Tournament20"] - case["values"]["Light reasoning"]["Vote20"],
            case["values"]["Medium reasoning"]["Tournament20"] - case["values"]["Medium reasoning"]["Vote20"],
        ))

    def composite(case: dict[str, Any]) -> float:
        return reasoning_lift(case) - routing_lift(case)

    needed = set(METHOD_ORDER)
    if any(any(not needed.issubset(case["values"][reasoning]) for reasoning in required_reasonings) for case in matrix):
        return {"primary": None, "secondary": [], "reasoning_over_routing": None,
                "warning": "complete five-method case vectors unavailable"}

    primary_effect = within("Medium reasoning", "Vote20", "Tournament20")
    primary_differences, primary_boot = _effect_summary(
        matrix, primary_effect, replicates=replicates, seed=seed + 7001
    )
    primary_left = [case["values"]["Medium reasoning"]["Vote20"] for case in matrix]
    primary_right = [case["values"]["Medium reasoning"]["Tournament20"] for case in matrix]
    mcnemar = exact_mcnemar(primary_left, primary_right)
    both_correct = sum(a == 1 and b == 1 for a, b in zip(primary_left, primary_right))
    both_incorrect = sum(a == 0 and b == 0 for a, b in zip(primary_left, primary_right))
    primary_ci95 = interval(primary_boot, 0.95)
    primary_ci90 = interval(primary_boot, 0.90)
    primary: dict[str, Any] = {
        "left": "Medium reasoning Vote20", "right": "Medium reasoning Tournament20",
        "metric": "exact_accuracy", "n_pairs": len(matrix),
        "difference": statistics.fmean(primary_differences),
        "ci95": primary_ci95, "ci90": primary_ci90,
        "classification": _classification(primary_ci95, primary_ci90),
        "vote20_only_wins": mcnemar["left_only"],
        "tournament20_only_wins": mcnemar["right_only"],
        "both_correct": both_correct, "both_incorrect": both_incorrect,
        "mcnemar": mcnemar,
    }

    specs: list[tuple[str, str, str, Callable[[dict[str, Any]], float], str]] = [
        ("S01", "Light reasoning Direct expected", "Medium reasoning Direct expected", between("Direct expected"), "sign_flip"),
        ("S02", "Light reasoning Vote10", "Medium reasoning Vote10", between("Vote10"), "mcnemar"),
        ("S03", "Light reasoning Vote20", "Medium reasoning Vote20", between("Vote20"), "mcnemar"),
        ("S04", "Light reasoning Swarm10", "Medium reasoning Swarm10", between("Swarm10"), "mcnemar"),
        ("S05", "Light reasoning Tournament20", "Medium reasoning Tournament20", between("Tournament20"), "mcnemar"),
        ("S06", "Light reasoning Vote10", "Light reasoning Swarm10", within("Light reasoning", "Vote10", "Swarm10"), "mcnemar"),
        ("S07", "Medium reasoning Vote10", "Medium reasoning Swarm10", within("Medium reasoning", "Vote10", "Swarm10"), "mcnemar"),
        ("S08", "Light reasoning Vote20", "Light reasoning Tournament20", within("Light reasoning", "Vote20", "Tournament20"), "mcnemar"),
        ("S09", "Light reasoning Vote10", "Light reasoning Vote20", within("Light reasoning", "Vote10", "Vote20"), "mcnemar"),
        ("S10", "Medium reasoning Vote10", "Medium reasoning Vote20", within("Medium reasoning", "Vote10", "Vote20"), "mcnemar"),
        ("S11", "Routing lift", "Reasoning lift", composite, "sign_flip"),
    ]
    secondary: list[dict[str, Any]] = []
    raw_p: list[tuple[str, float]] = []
    for index, (identifier, left, right, effect, test_name) in enumerate(specs):
        differences, boot = _effect_summary(matrix, effect, replicates=replicates, seed=seed + 8000 + index)
        result: dict[str, Any] = {
            "id": identifier, "left": left, "right": right, "n_pairs": len(matrix),
            "difference": statistics.fmean(differences), "ci95": interval(boot, 0.95),
        }
        if test_name == "sign_flip":
            test = paired_sign_flip(differences, seed=seed + 9000 + index)
        else:
            # The registered binary contrast has right-left differences in {-1,0,1}.
            test = exact_mcnemar([value < 0 for value in differences], [value > 0 for value in differences])
        result["test"] = test
        result["raw_p"] = test["p_value"]
        raw_p.append((identifier, test["p_value"]))
        secondary.append(result)
    adjusted = holm_adjust(raw_p)
    for result in secondary:
        result["holm_adjusted_p"] = adjusted[result["id"]]
        result["holm_significant_0_05"] = result["holm_adjusted_p"] <= 0.05

    composite_differences = [composite(case) for case in matrix]
    reasoning_routing = {
        "reasoning_lift": statistics.fmean(reasoning_lift(case) for case in matrix),
        "routing_lift": statistics.fmean(routing_lift(case) for case in matrix),
        "difference": statistics.fmean(composite_differences),
    }

    # Preregistered block sensitivity for the primary contrast.
    block_effects: dict[str, float] = {}
    block_nets: dict[str, int] = {}
    for block in sorted({case["block"] for case in matrix}):
        values = [primary_effect(case) for case in matrix if case["block"] == block]
        block_effects[block] = statistics.fmean(values)
        block_nets[block] = int(sum(values))
    leave_out = {
        block: statistics.fmean(primary_effect(case) for case in matrix if case["block"] != block)
        for block in block_effects
    }
    rng = random.Random(seed + 10001)
    unstratified = []
    for _ in range(replicates):
        unstratified.append(statistics.fmean(primary_effect(rng.choice(matrix)) for _ in matrix))
    blocks = sorted(block_effects)
    whole_block = []
    for _ in range(replicates):
        selected_blocks = [rng.choice(blocks) for _ in blocks]
        selected_cases = [case for block in selected_blocks for case in matrix if case["block"] == block]
        whole_block.append(statistics.fmean(primary_effect(case) for case in selected_cases))
    abs_net = sum(abs(value) for value in block_nets.values())
    primary_sign = 1 if primary["difference"] > 0 else -1 if primary["difference"] < 0 else 0
    direction_change = any(
        (1 if value > 0 else -1 if value < 0 else 0) != primary_sign for value in leave_out.values()
    )
    concentration = bool(abs_net and max(abs(value) for value in block_nets.values()) / abs_net >= 0.75)
    spread = max(block_effects.values()) - min(block_effects.values()) >= 0.30
    whole_ci95, whole_ci90 = interval(whole_block, 0.95), interval(whole_block, 0.90)
    classification_change = _classification(primary_ci95, primary_ci90) != _classification(whole_ci95, whole_ci90)
    primary["block_sensitivity"] = {
        "block_effects": block_effects, "block_net_wins": block_nets,
        "leave_one_block_out": leave_out,
        "unstratified_ci95": interval(unstratified, 0.95),
        "whole_block_ci95": whole_ci95, "whole_block_ci90": whole_ci90,
        "whole_block_classification": _classification(whole_ci95, whole_ci90),
        "direction_changes_leave_one_out": direction_change,
        "one_block_at_least_75pct_abs_net": concentration,
        "classification_changes_whole_block": classification_change,
        "block_effect_spread_at_least_30pp": spread,
        "block_sensitive": direction_change or concentration or classification_change or spread,
    }
    return {"primary": primary, "secondary": secondary, "reasoning_over_routing": reasoning_routing}


def analyze(scored: dict[str, Any], *, replicates: int = DEFAULT_REPLICATES, seed: int = DEFAULT_SEED,
            require_four_blocks: bool = True) -> dict[str, Any]:
    cases = scored.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AnalysisError("scored input contains no cases")
    if replicates <= 0:
        raise AnalysisError("bootstrap replicates must be positive")
    reasonings = sorted({str(case.get("reasoning")) for case in cases})
    if require_four_blocks:
        if set(reasonings) != {"Light reasoning", "Medium reasoning"}:
            raise AnalysisError("final analysis requires exactly Light reasoning and Medium reasoning")
        identities_by_reasoning: dict[str, set[str]] = defaultdict(set)
        for case in cases:
            reasoning = str(case.get("reasoning"))
            case_id = str(case.get("case_id"))
            if case_id in identities_by_reasoning[reasoning]:
                raise AnalysisError(f"duplicate final case row: {reasoning}/{case_id}")
            identities_by_reasoning[reasoning].add(case_id)
            if set(case.get("methods", {})) != set(METHOD_ORDER):
                raise AnalysisError(f"{reasoning}/{case_id} does not contain exactly the five frozen methods")
        if any(len(ids) != 48 for ids in identities_by_reasoning.values()):
            raise AnalysisError("final analysis requires exactly 48 unique cases per reasoning arm")
        if identities_by_reasoning["Light reasoning"] != identities_by_reasoning["Medium reasoning"]:
            raise AnalysisError("Light and Medium reasoning do not contain the same 48 paired cases")
        for reasoning in reasonings:
            counts = Counter(str(case.get("block")) for case in cases if str(case.get("reasoning")) == reasoning)
            if counts != Counter({block: 12 for block in ("B01", "B02", "B03", "B04")}):
                raise AnalysisError(f"{reasoning} does not have exactly 12 cases in each frozen block")
    output_methods: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    blocks_output: list[dict[str, Any]] = []
    leave_one_out: list[dict[str, Any]] = []
    warnings: list[str] = []

    for reasoning_index, reasoning in enumerate(reasonings):
        matrix = _build_case_matrix(cases, reasoning)
        block_names = sorted({case["block"] for case in matrix})
        if require_four_blocks and len(block_names) != 4:
            raise AnalysisError(f"{reasoning} has {len(block_names)} blocks; final analysis requires four")
        methods = sorted({name for case in matrix for name in case["methods"]}, key=_method_sort_key)
        metrics = sorted({metric for case in matrix for values in case["methods"].values() for metric in values})
        distributions = _bootstrap_distributions(
            matrix, methods, metrics, replicates, seed + reasoning_index * 1_000_003
        )

        for method in methods:
            available = [case for case in matrix if method in case["methods"]]
            if len(available) != len(matrix):
                warnings.append(f"{reasoning}/{method} present for {len(available)}/{len(matrix)} cases")
            raw_result = next((case["raw"]["methods"][method] for case in available), {})
            method_result: dict[str, Any] = {
                "reasoning": reasoning,
                "method": method,
                "n_cases": len(available),
                "deployment_calls": int(raw_result.get("deployment_calls", 1)),
            }
            cost: dict[str, Any] = {}
            per_term: list[dict[str, Any]] = []
            for metric in metrics:
                values = [case["methods"][method][metric] for case in available if metric in case["methods"][method]]
                distribution = distributions.get((method, metric), [])
                if not values or not distribution:
                    continue
                summary = _summary(statistics.fmean(values), distribution)
                if metric.startswith("cost."):
                    cost[metric.split(".", 1)[1]] = summary
                elif metric.startswith("term_") and metric.endswith("_accuracy") and metric.split("_")[1].isdigit():
                    per_term.append({"position": int(metric.split("_")[1]), **summary})
                else:
                    method_result[metric] = summary
            if cost:
                method_result["cost"] = cost
            if per_term:
                method_result["per_term_accuracy"] = sorted(per_term, key=lambda row: row["position"])
            exact_summary = method_result.get("exact_accuracy")
            if isinstance(exact_summary, dict) and exact_summary.get("estimate", 0) > 0:
                accuracy = exact_summary["estimate"]
                method_result["calls_per_exact_correct_case"] = method_result["deployment_calls"] / (12 * accuracy)
                if "total_tokens" in cost:
                    method_result["tokens_per_exact_correct_case"] = cost["total_tokens"]["estimate"] / (12 * accuracy)
            output_methods.append(method_result)

        for left, right in itertools.combinations(methods, 2):
            paired = [case for case in matrix if left in case["methods"] and right in case["methods"]]
            if not paired:
                continue
            paired_metrics = ["exact_accuracy", "term_accuracy", "format_rate"]
            paired_metrics.extend(sorted(metric for metric in metrics if metric.startswith("cost.")))
            for metric in paired_metrics:
                eligible = [case for case in paired if metric in case["methods"][left] and metric in case["methods"][right]]
                if not eligible:
                    continue
                left_values = [case["methods"][left][metric] for case in eligible]
                right_values = [case["methods"][right][metric] for case in eligible]
                differences = [b - a for a, b in zip(left_values, right_values)]
                left_boot = distributions[(left, metric)]
                right_boot = distributions[(right, metric)]
                paired_boot = [b - a for a, b in zip(left_boot, right_boot)]
                result: dict[str, Any] = {
                    "reasoning": reasoning, "left": left, "right": right,
                    "metric": metric, "n_pairs": len(eligible),
                    "difference": statistics.fmean(differences),
                    "ci95": interval(paired_boot, 0.95),
                    "ci90": interval(paired_boot, 0.90),
                }
                if metric.startswith("cost."):
                    left_estimate, right_estimate = statistics.fmean(left_values), statistics.fmean(right_values)
                    if left_estimate > 0 and right_estimate > 0:
                        log_boot = [
                            math.log(b / a) for a, b in zip(left_boot, right_boot) if a > 0 and b > 0
                        ]
                        result["log_cost_ratio"] = math.log(right_estimate / left_estimate)
                        if log_boot:
                            result["log_cost_ratio_ci95"] = interval(log_boot, 0.95)
                else:
                    result["equivalence_margin"] = EQUIVALENCE_MARGIN
                    result["equivalent_10pp"] = (
                        result["ci90"][0] > -EQUIVALENCE_MARGIN
                        and result["ci90"][1] < EQUIVALENCE_MARGIN
                    )
                if metric == "exact_accuracy" and left != "Direct expected" and right != "Direct expected" \
                        and _is_binary(left_values) and _is_binary(right_values):
                    test = exact_mcnemar(left_values, right_values)
                    result["mcnemar"] = test
                comparisons.append(result)

        for block in block_names:
            block_cases = [case for case in matrix if case["block"] == block]
            method_values: dict[str, Any] = {}
            for method in methods:
                present = [case for case in block_cases if method in case["methods"]]
                if present:
                    method_values[method] = {
                        metric: statistics.fmean(case["methods"][method][metric] for case in present if metric in case["methods"][method])
                        for metric in ("exact_accuracy", "term_accuracy", "format_rate")
                        if any(metric in case["methods"][method] for case in present)
                    }
            blocks_output.append({
                "reasoning": reasoning, "block": block, "n_cases": len(block_cases), "methods": method_values,
            })

        for omitted in block_names:
            retained = [case for case in matrix if case["block"] != omitted]
            method_values = {}
            for method in methods:
                values = [case["methods"][method]["exact_accuracy"] for case in retained if method in case["methods"]]
                if values:
                    method_values[method] = statistics.fmean(values)
            comparison_values = []
            for left, right in itertools.combinations(methods, 2):
                pair_diffs = [
                    case["methods"][right]["exact_accuracy"] - case["methods"][left]["exact_accuracy"]
                    for case in retained if left in case["methods"] and right in case["methods"]
                ]
                if pair_diffs:
                    comparison_values.append({"left": left, "right": right, "difference": statistics.fmean(pair_diffs)})
            leave_one_out.append({
                "reasoning": reasoning, "omitted_block": omitted,
                "n_cases": len(retained), "exact_accuracy": method_values,
                "comparisons": comparison_values,
            })

    confirmatory = _confirmatory_analysis(cases, replicates, seed)

    return {
        "schema_version": SCHEMA_VERSION,
        "bootstrap": {
            "method": "case bootstrap stratified by the four frozen blocks",
            "replicates": replicates, "seed": seed, "ci_method": "percentile",
            "quantile_probabilities": {"ci95": [0.025, 0.975], "ci90": [0.05, 0.95]},
            "derived_seeds": {
                "method_summaries_by_reasoning": {
                    reasoning: seed + index * 1_000_003 for index, reasoning in enumerate(reasonings)
                },
                "primary": seed + 7001,
                "confirmatory_secondary": {
                    f"S{index + 1:02d}": seed + 8000 + index for index in range(11)
                },
                "sign_flip": {"S01": seed + 9000, "S11": seed + 9010},
                "unstratified_and_whole_block_sensitivity": seed + 10001,
            },
        },
        "equivalence": {"confidence_level": 0.90, "margin": EQUIVALENCE_MARGIN},
        "methods": output_methods,
        "comparisons": comparisons,
        "blocks": blocks_output,
        "leave_one_block_out": leave_one_out,
        "primary": confirmatory["primary"],
        "confirmatory_secondary": confirmatory["secondary"],
        "reasoning_over_routing": confirmatory["reasoning_over_routing"],
        "multiple_testing": {"method": "Holm", "family": "11 preregistered confirmatory secondary comparisons"},
        "operational_reliability": scored.get("operational_reliability", {}),
        "warnings": warnings,
    }


def self_test() -> None:
    test = exact_mcnemar([1, 1, 1, 0], [0, 0, 0, 0])
    assert test["left_only"] == 3 and test["right_only"] == 0
    assert test["p_value"] == 0.25
    adjusted = holm_adjust([("a", 0.01), ("b", 0.03), ("c", 0.2)])
    assert adjusted == {"a": 0.03, "b": 0.06, "c": 0.2}
    assert percentile([0.0, 1.0], 0.5) == 0.5

    cases = []
    for block in range(1, 5):
        for index in range(12):
            exact = (block + index) % 2 == 0
            for reasoning in ("Light reasoning", "Medium reasoning"):
                medium = reasoning == "Medium reasoning"
                methods = {
                    "Direct expected": {"exact": 0.5 if medium else 0.25, "term_accuracy": 0.5, "format_compliant": 1.0, "per_term": [0.5] * 5, "deployment_calls": 1, "cost": {"total_tokens": 100}},
                    "Vote10": {"exact": exact, "term_accuracy": float(exact), "format_compliant": True, "per_term": [float(exact)] * 5, "deployment_calls": 10, "cost": {"total_tokens": 1000}},
                    "Swarm10": {"exact": exact or medium, "term_accuracy": float(exact or medium), "format_compliant": True, "per_term": [float(exact or medium)] * 5, "deployment_calls": 10, "cost": {"total_tokens": 900}},
                    "Vote20": {"exact": True, "term_accuracy": 1.0, "format_compliant": True, "per_term": [1.0] * 5, "deployment_calls": 20, "cost": {"total_tokens": 2000}},
                    "Tournament20": {"exact": medium, "term_accuracy": float(medium), "format_compliant": True, "per_term": [float(medium)] * 5, "deployment_calls": 20, "cost": {"total_tokens": 1800}},
                }
                cases.append({"case_id": f"C{block}{index}", "block": f"B{block:02d}", "reasoning": reasoning, "methods": methods})
    first = analyze({"cases": cases}, replicates=300, seed=7)
    second = analyze({"cases": cases}, replicates=300, seed=7)
    assert first == second
    assert first["bootstrap"]["replicates"] == 300
    assert len(first["blocks"]) == 8
    vote20 = next(row for row in first["methods"] if row["method"] == "Vote20")
    assert vote20["exact_accuracy"]["estimate"] == 1.0
    assert first["primary"]["left"] == "Medium reasoning Vote20"
    assert len(first["confirmatory_secondary"]) == 11
    assert any(row["metric"] == "cost.total_tokens" and "log_cost_ratio_ci95" in row for row in first["comparisons"])
    print("analyze_results.py self-test: ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", help="scored JSON from score_results.py")
    parser.add_argument("--output", help="output analysis JSON; stdout if omitted")
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--allow-nonfinal-blocks", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.scored:
        parser.error("--scored is required unless --self-test is used")
    try:
        scored = json.loads(Path(args.scored).read_text(encoding="utf-8"))
        result = analyze(
            scored, replicates=args.replicates, seed=args.seed,
            require_four_blocks=not args.allow_nonfinal_blocks,
        )
    except (OSError, json.JSONDecodeError, AnalysisError) as error:
        print(f"analysis error: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
