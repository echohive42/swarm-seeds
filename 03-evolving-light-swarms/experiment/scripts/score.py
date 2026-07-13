#!/usr/bin/env python3
"""Score and compare Experiment 03 architectures (standard library only).

Input schemas
-------------
``answers.jsonl`` contains one hidden-answer object per line::

    {"case_id":"C001", "next_five":["1","2","3","4","5"],
     "block":"B01", "family":"polynomial", "tier":"hard"}

``predictions.json`` is the controller's normalized output. It contains one row
per completed job (non-completed rows, if present, are ignored)::

    {"records":[
      {"phase":"selection", "generation":2, "genome_id":"G2-03",
       "method":"swarm", "block_id":"B01", "case_id":"C001",
       "role":"solver", "call_index":1, "stage":"proposer",
       "answer":["1","2","3","4","5"], "confidence":0.8,
       "format_valid":true, "input_tokens":100, "output_tokens":40,
       "latency_ms":900}
    ]}

Append-only JSONL containing the same records is also accepted. ``job_id``
should be the stable block-call identity and therefore repeats over the cases
answered by that call. If absent, a deterministic identity is built from
phase/generation/method/block/stage/call_index.

For an evolved architecture set ``genome_id``. ``stage=proposer`` defines a
candidate and ``stage=judge`` defines terminal architecture output (explicit
``role=proposal``/``role=final`` is also accepted). A final job may emit
``next_five`` itself or
select an earlier job with ``selected_job_id`` (``selected_candidate_id`` is an
alias). If more than one final row exists, an explicitly true
``is_final_output`` wins; otherwise the greatest ``stage_index`` wins, then the
lexicographically smallest job ID. Ambiguous multiple explicitly-final rows are
rejected. These rules make terminal-output selection deterministic.

Hidden RuleWeave answers may use ``next`` instead of ``next_five``. Predictions
must be arrays of exactly five canonical decimal strings. JSON
numbers, leading zeroes, plus signs, wrong lengths, missing jobs, and malformed
completed output score zero. Vote10 requires ten proposal rows per case and is
their valid-answer plurality; Vote20 is supported analogously with 20. A
plurality tie is resolved by greater mean confidence among votes for the tied
tuple, then by lexicographically smallest five-string tuple. Invalid proposals
abstain, but remain visible in format/completion counts. Genome proposal
pluralities use all proposal jobs and the same rule.

Genome fitness is lexicographic: more exact cases, fewer harmful overrides,
more correct terms, more format-valid cases, then canonical genome hash. A
harmful override is a final answer that differs from a correct proposal
plurality and is itself wrong. Call limits are hard runner constraints, not a
tunable fitness penalty.

Outputs are ``case_matrix.csv``, ``summary.json``, and ``comparisons.json``.
The paired comparison is final-genome minus baseline. Confidence intervals use
a case bootstrap stratified by frozen block and a fixed seed. McNemar is the
exact two-sided conditional binomial test on discordant exact-score pairs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "experiment-03-score-v1"
DEFAULT_BOOTSTRAP_REPLICATES = 50_000
DEFAULT_BOOTSTRAP_SEED = 20260713
INTEGER_RE = re.compile(r"^-?(?:0|[1-9]\d*)$")
VOTE_SLOTS = {
    "Vote10": tuple(f"S{number:02d}" for number in range(1, 11)),
    "Vote20": tuple(f"S{number:02d}" for number in range(1, 21)),
}


class ScoreError(ValueError):
    """Raised when an input is ambiguous or structurally unsafe to score."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ScoreError(f"non-finite JSON number: {token}")


def parse_json_strict(text: str) -> Any:
    try:
        return json.loads(
            text.strip().lstrip("\ufeff"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except json.JSONDecodeError as error:
        raise ScoreError(f"invalid JSON: {error}") from error


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = parse_json_strict(line)
        except ScoreError as error:
            raise ScoreError(f"{path}:{line_number}: {error}") from error
        if not isinstance(row, dict):
            raise ScoreError(f"{path}:{line_number}: JSONL row must be an object")
        rows.append(row)
    if not rows:
        raise ScoreError(f"{path}: no JSONL objects")
    return rows


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load either normalized {records:[...]} JSON or append-only JSONL."""
    text = path.read_text(encoding="utf-8")
    try:
        top = parse_json_strict(text)
    except ScoreError:
        return load_jsonl(path)
    if isinstance(top, dict) and isinstance(top.get("records"), list):
        records = top["records"]
    elif isinstance(top, list):
        records = top
    elif isinstance(top, dict):
        records = [top]
    else:
        raise ScoreError(f"{path}: expected {{records:[...]}}, array, object, or JSONL")
    if not records or not all(isinstance(record, dict) for record in records):
        raise ScoreError(f"{path}: records must be a non-empty array of objects")
    return records


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prediction_value(value: Any) -> Any:
    """Unwrap only documented structured answer containers, never free text."""
    seen: set[int] = set()
    while isinstance(value, dict):
        identity = id(value)
        if identity in seen:
            return None
        seen.add(identity)
        found = False
        for key in ("next_five", "answer", "prediction", "final_answer", "output"):
            if key in value:
                value = value[key]
                found = True
                break
        if not found:
            return None
    return value


def parse_prediction(value: Any) -> tuple[str, ...] | None:
    value = _prediction_value(value)
    if not isinstance(value, list) or len(value) != 5:
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or INTEGER_RE.fullmatch(item) is None:
            return None
        if item == "-0":
            return None
        result.append(item)
    return tuple(result)


def _first(record: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return default


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise ScoreError(f"{field} must be a non-empty string or integer")
    return str(value)


def load_answers(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = _identifier(_first(row, ("case_id", "id")), "answer case_id")
        if case_id in answers:
            raise ScoreError(f"duplicate hidden answer for case {case_id}")
        truth = parse_prediction(_first(row, ("next_five", "next", "answer", "prediction")))
        if truth is None:
            raise ScoreError(f"hidden answer for {case_id} is not five canonical decimal strings")
        answers[case_id] = {
            "case_id": case_id,
            "truth": truth,
            "block": str(row.get("block", row.get("block_id", "UNSPECIFIED"))),
            "family": str(row.get("family", "UNSPECIFIED")),
            "tier": str(row.get("tier", row.get("difficulty", "UNSPECIFIED"))),
        }
    return answers


def normalize_completed_jobs(
    rows: Sequence[dict[str, Any]], answers: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize completed rows and reject duplicate job/case observations."""
    jobs: list[dict[str, Any]] = []
    completed_pairs: set[tuple[str, str]] = set()
    for source_index, row in enumerate(rows):
        if str(row.get("status", "completed")).lower() != "completed":
            continue
        case_id = _identifier(row.get("case_id"), "job case_id")
        if case_id not in answers:
            raise ScoreError(f"completed job references unknown case {case_id}")
        explicit_job_id = row.get("job_id")
        genome = row.get("genome_id")
        architecture = row.get("architecture_id", row.get("method", genome))
        if architecture is None:
            raise ScoreError(f"completed row {source_index} has no method/architecture_id or genome_id")
        architecture_id = _identifier(architecture, "architecture_id")
        architecture_id = {"vote10": "Vote10", "vote20": "Vote20"}.get(
            architecture_id.lower(), architecture_id
        )
        genome_id = _identifier(genome, "genome_id") if genome is not None else None
        stage_name = str(row.get("stage", "")).strip().lower()
        if stage_name == "proposer":
            role = "proposal"
        elif stage_name == "judge":
            role = "final"
        else:
            role_name = str(row.get("role", row.get("job_type", ""))).strip().lower()
            if role_name in {"proposal", "proposer"}:
                role = "proposal"
            elif role_name in {"final", "judge"}:
                role = "final"
            else:
                role = "intermediate"
        stage_raw = row.get("stage_index", row.get("call_index", 0))
        if isinstance(stage_raw, bool) or not isinstance(stage_raw, int):
            raise ScoreError(f"completed row {source_index} stage_index/call_index must be an integer")
        block_id = str(row.get("block_id", row.get("block", "UNSPECIFIED")))
        fallback_key = [
            row.get("phase"), row.get("generation"), genome_id or architecture_id,
            block_id, stage_name or role, row.get("call_index", stage_raw),
        ]
        job_id = _identifier(
            explicit_job_id if explicit_job_id is not None
            else json.dumps(fallback_key, separators=(",", ":")),
            "job_id",
        )
        pair = (job_id, case_id)
        if pair in completed_pairs:
            raise ScoreError(f"duplicate completed job/case row: {job_id}/{case_id}")
        completed_pairs.add(pair)
        calls_raw = row.get("calls", row.get("call_count", 1))
        calls = calls_raw if isinstance(calls_raw, int) and not isinstance(calls_raw, bool) and calls_raw >= 0 else 1
        prediction = parse_prediction(_first(row, ("output", "next_five", "answer", "prediction")))
        selected = _first(row, ("selected_job_id", "selected_candidate_id"))
        job_format_valid = (
            row.get("format_valid") is not False
            and (prediction is not None or selected is not None)
        )
        # The controller's schema validator may reject an otherwise extractable
        # answer because the completed response violated its full output schema.
        # Such output must remain a scored format failure.
        if row.get("format_valid") is False:
            prediction = None
        slot_raw = row.get("slot", row.get("slot_id", row.get("call_index", job_id)))
        confidence_raw = row.get("confidence", 0.0)
        confidence = (
            float(confidence_raw)
            if not isinstance(confidence_raw, bool)
            and isinstance(confidence_raw, (int, float))
            and math.isfinite(float(confidence_raw))
            else 0.0
        )
        jobs.append({
            "job_id": job_id,
            "case_id": case_id,
            "architecture_id": architecture_id,
            "genome_id": genome_id,
            "role": role,
            "slot": str(slot_raw),
            "confidence": confidence,
            "block_id": block_id,
            "call_key": job_id,
            "stage_index": stage_raw,
            "is_final_output": row.get("is_final_output") is True,
            "prediction": prediction,
            "job_format_valid": job_format_valid,
            "selected_job_id": str(selected) if selected is not None else None,
            "calls": calls,
            "input_tokens": _nonnegative_number(row.get("input_tokens")),
            "output_tokens": _nonnegative_number(row.get("output_tokens")),
            "cost_usd": _nonnegative_number(row.get("cost_usd")),
            "latency_ms": _nonnegative_number(row.get("latency_ms")),
        })
    return jobs


def _nonnegative_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    return number if math.isfinite(number) and number >= 0.0 else 0.0


def _slot_key(slot: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"[A-Za-z]+(\d+)", slot)
    return (0, int(match.group(1)), slot) if match else (1, 0, slot)


def deterministic_plurality(jobs: Sequence[dict[str, Any]]) -> tuple[str, ...] | None:
    """Plurality with frozen count, mean-confidence, lexicographic tie-break."""
    valid = [job for job in jobs if job.get("prediction") is not None]
    if not valid:
        return None
    counts = Counter(job["prediction"] for job in valid)
    confidence_sums: dict[tuple[str, ...], float] = defaultdict(float)
    for job in valid:
        confidence_sums[job["prediction"]] += job["confidence"]
    means = {prediction: confidence_sums[prediction] / counts[prediction] for prediction in counts}
    return min(counts, key=lambda prediction: (-counts[prediction], -means[prediction], prediction))


def _selected_final(finals: Sequence[dict[str, Any]], architecture: str, case_id: str) -> dict[str, Any] | None:
    explicit = [job for job in finals if job["is_final_output"]]
    if len(explicit) > 1:
        raise ScoreError(f"{architecture}/{case_id} has multiple is_final_output jobs")
    if explicit:
        return explicit[0]
    if not finals:
        return None
    return sorted(finals, key=lambda job: (-job["stage_index"], job["job_id"]))[0]


def _resolve_prediction(final: dict[str, Any] | None, all_jobs: Sequence[dict[str, Any]]) -> tuple[str, ...] | None:
    if final is None or not final["job_format_valid"]:
        return None
    if final["prediction"] is not None:
        return final["prediction"]
    selected_job_id = final["selected_job_id"]
    if selected_job_id is None:
        return None
    matches = [job for job in all_jobs if job["job_id"] == selected_job_id]
    if len(matches) != 1:
        return None
    return matches[0]["prediction"]


def score_prediction(prediction: tuple[str, ...] | None, truth: tuple[str, ...]) -> dict[str, Any]:
    per_term = [int(prediction is not None and prediction[index] == truth[index]) for index in range(5)]
    return {
        "prediction": prediction,
        "format_compliant": int(prediction is not None),
        "exact": int(prediction == truth),
        "per_term": per_term,
        "term_correct": sum(per_term),
        "term_accuracy": sum(per_term) / 5.0,
    }


def _method_sort_key(method: str) -> tuple[int, str]:
    fixed = {"Vote10": 0, "Vote20": 1}
    return (fixed.get(method, 2), method)


def build_case_scores(
    answers: dict[str, dict[str, Any]], jobs: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    by_arch_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    genome_flags: dict[str, bool] = {}
    for job in jobs:
        # The controller labels Vote10 rows with the sentinel genome_id
        # ``VOTE10``. Baseline semantics come from method/architecture_id and
        # must take precedence over that sentinel.
        method = (
            job["architecture_id"]
            if job["architecture_id"] in VOTE_SLOTS
            else job["genome_id"] or job["architecture_id"]
        )
        by_arch_case[(method, job["case_id"])].append(job)
        genome_flags[method] = genome_flags.get(method, False) or (
            job["genome_id"] is not None and job["architecture_id"] not in VOTE_SLOTS
        )

    methods = sorted({method for method, _ in by_arch_case}, key=_method_sort_key)
    cases: list[dict[str, Any]] = []
    for case_id, answer in sorted(answers.items(), key=lambda item: item[0]):
        case = {**answer, "methods": {}}
        observed_blocks = {
            job["block_id"] for (method, job_case), grouped in by_arch_case.items()
            if job_case == case_id for job in grouped if job["block_id"] != "UNSPECIFIED"
        }
        if len(observed_blocks) > 1:
            raise ScoreError(f"case {case_id} has inconsistent block_id values: {sorted(observed_blocks)}")
        if case["block"] == "UNSPECIFIED" and observed_blocks:
            case["block"] = next(iter(observed_blocks))
        elif observed_blocks and case["block"] not in observed_blocks:
            raise ScoreError(f"case {case_id} hidden-answer block disagrees with prediction block")
        for method in methods:
            method_jobs = by_arch_case.get((method, case_id), [])
            proposals = [job for job in method_jobs if job["role"] == "proposal"]
            proposal_plurality = deterministic_plurality(proposals)
            if method in VOTE_SLOTS:
                proposal_by_slot: dict[str, dict[str, Any]] = {}
                for proposal in proposals:
                    if proposal["slot"] in proposal_by_slot:
                        raise ScoreError(f"{method}/{case_id} has duplicate completed slot {proposal['slot']}")
                    proposal_by_slot[proposal["slot"]] = proposal
                expected = len(VOTE_SLOTS[method])
                used_proposals = sorted(proposal_by_slot.values(), key=lambda job: _slot_key(job["slot"]))
                # An incomplete or over-complete fixed baseline is a scored
                # architecture failure, not a variable-budget plurality.
                prediction = deterministic_plurality(used_proposals) if len(used_proposals) == expected else None
                proposal_plurality = deterministic_plurality(used_proposals)
                terminal_job_id = None
                completed_slots = len(used_proposals)
                valid_proposals = sum(proposal["prediction"] is not None for proposal in used_proposals)
            else:
                final = _selected_final(
                    [job for job in method_jobs if job["role"] == "final"], method, case_id
                )
                prediction = _resolve_prediction(final, method_jobs)
                terminal_job_id = final["job_id"] if final is not None else None
                completed_slots = len(proposals)
                valid_proposals = sum(proposal["prediction"] is not None for proposal in proposals)
            scored = score_prediction(prediction, answer["truth"])
            plurality_score = score_prediction(proposal_plurality, answer["truth"])
            override = int(
                method not in VOTE_SLOTS
                and proposal_plurality is not None
                and prediction != proposal_plurality
            )
            harmful_override = int(override and plurality_score["exact"] == 1 and scored["exact"] == 0)
            useful_override = int(override and plurality_score["exact"] == 0 and scored["exact"] == 1)
            resources = {
                "calls": sum(job["calls"] for job in method_jobs),
                "input_tokens": sum(job["input_tokens"] for job in method_jobs),
                "output_tokens": sum(job["output_tokens"] for job in method_jobs),
                "cost_usd": sum(job["cost_usd"] for job in method_jobs),
                "latency_ms": sum(job["latency_ms"] for job in method_jobs),
            }
            resource_events = {
                job["call_key"]: {
                    "calls": job["calls"], "input_tokens": job["input_tokens"],
                    "output_tokens": job["output_tokens"], "cost_usd": job["cost_usd"],
                    "latency_ms": job["latency_ms"], "format_valid": job["job_format_valid"],
                }
                for job in method_jobs
            }
            case["methods"][method] = {
                **scored,
                "proposal_plurality": proposal_plurality,
                "proposal_plurality_exact": plurality_score["exact"],
                "override": override,
                "harmful_override": harmful_override,
                "useful_override": useful_override,
                "terminal_job_id": terminal_job_id,
                "completed_proposals": completed_slots,
                "valid_proposals": valid_proposals,
                "_resource_events": resource_events,
                **resources,
            }
        cases.append(case)
    return cases, genome_flags


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ScoreError("cannot take a percentile of an empty sample")
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


def confidence_interval(distribution: Sequence[float], level: float = 0.95) -> list[float]:
    alpha = (1.0 - level) / 2.0
    return [percentile(distribution, alpha), percentile(distribution, 1.0 - alpha)]


def stratified_bootstrap_means(
    cases: Sequence[dict[str, Any]], values: Sequence[float], replicates: int, seed: int
) -> list[float]:
    if len(cases) != len(values) or not cases:
        raise ScoreError("bootstrap cases and values must be non-empty and aligned")
    if replicates < 1:
        raise ScoreError("bootstrap replicates must be positive")
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(cases):
        blocks[str(case["block"])].append(index)
    rng = random.Random(seed)
    distribution: list[float] = []
    for _ in range(replicates):
        sample: list[float] = []
        for block in sorted(blocks):
            indices = blocks[block]
            sample.extend(values[rng.choice(indices)] for _ in indices)
        distribution.append(statistics.fmean(sample))
    return distribution


def exact_mcnemar(left: Sequence[int], right: Sequence[int]) -> dict[str, Any]:
    if len(left) != len(right):
        raise ScoreError("McNemar inputs are not paired")
    left_only = sum(a == 1 and b == 0 for a, b in zip(left, right))
    right_only = sum(a == 0 and b == 1 for a, b in zip(left, right))
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(left_only, right_only) + 1))
        p_value = min(1.0, 2.0 * tail / (2 ** discordant))
    return {
        "test": "exact two-sided McNemar",
        "left_only": left_only,
        "right_only": right_only,
        "discordant": discordant,
        "p_value": p_value,
    }


def _aggregate_method(
    cases: Sequence[dict[str, Any]], method: str, genome: bool, replicates: int, seed: int
) -> dict[str, Any]:
    rows = [case["methods"][method] for case in cases]
    exact = [row["exact"] for row in rows]
    terms = [row["term_accuracy"] for row in rows]
    formats = [row["format_compliant"] for row in rows]
    exact_boot = stratified_bootstrap_means(cases, exact, replicates, seed)
    term_boot = stratified_bootstrap_means(cases, terms, replicates, seed + 1)
    n = len(cases)
    harmful = sum(row["harmful_override"] for row in rows)
    unique_resources: dict[str, dict[str, Any]] = {}
    for row in rows:
        for call_key, resource in row["_resource_events"].items():
            if call_key in unique_resources:
                existing = unique_resources[call_key]
                numeric_keys = ("calls", "input_tokens", "output_tokens", "cost_usd", "latency_ms")
                if any(existing[key] != resource[key] for key in numeric_keys):
                    raise ScoreError(f"shared call {call_key!r} has inconsistent repeated telemetry")
                existing["format_valid"] = bool(existing["format_valid"] and resource["format_valid"])
            else:
                unique_resources[call_key] = dict(resource)
    result: dict[str, Any] = {
        "n": n,
        "case_count": n,
        "term_count": 5 * n,
        "exact_accuracy": statistics.fmean(exact),
        "exact_ci95": confidence_interval(exact_boot),
        "term_accuracy": statistics.fmean(terms),
        "term_ci95": confidence_interval(term_boot),
        "format_rate": statistics.fmean(formats),
        "format_valid": sum(formats),
        "exact_cases": sum(exact),
        "term_correct": sum(row["term_correct"] for row in rows),
        "overrides": sum(row["override"] for row in rows),
        "harmful_overrides": harmful,
        "useful_overrides": sum(row["useful_override"] for row in rows),
        "calls": sum(resource["calls"] for resource in unique_resources.values()),
        "input_tokens": sum(resource["input_tokens"] for resource in unique_resources.values()),
        "output_tokens": sum(resource["output_tokens"] for resource in unique_resources.values()),
        "cost_usd": sum(resource["cost_usd"] for resource in unique_resources.values()),
        "latency_ms": sum(resource["latency_ms"] for resource in unique_resources.values()),
        "completed_calls": len(unique_resources),
        "malformed_calls": sum(not resource["format_valid"] for resource in unique_resources.values()),
    }
    if genome:
        result["fitness_key_without_hash"] = [
            result["exact_cases"], -harmful, result["term_correct"], result["format_valid"]
        ]
        result["fitness_order"] = (
            "lexicographic max: exact_cases, -harmful_overrides, term_correct, "
            "format_valid; canonical genome hash is the final external tie-break"
        )
    return result


def summarize(
    cases: Sequence[dict[str, Any]], genome_flags: dict[str, bool], replicates: int, seed: int
) -> dict[str, Any]:
    methods = sorted(cases[0]["methods"], key=_method_sort_key) if cases else []
    method_summaries = {
        method: _aggregate_method(cases, method, genome_flags.get(method, False), replicates, seed + index * 101)
        for index, method in enumerate(methods)
    }
    genome_scores = [
        {
            "genome_id": method,
            "exact_correct": method_summaries[method]["exact_cases"],
            "exact_cases": method_summaries[method]["exact_cases"],
            "term_correct": method_summaries[method]["term_correct"],
            "format_valid": method_summaries[method]["format_valid"],
            "case_count": method_summaries[method]["case_count"],
            "term_count": method_summaries[method]["term_count"],
            "harmful_overrides": method_summaries[method]["harmful_overrides"],
            "fitness_key_without_hash": method_summaries[method]["fitness_key_without_hash"],
        }
        for method in methods if genome_flags.get(method, False)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "n_cases": len(cases),
        "bootstrap": {
            "method": "paired case bootstrap stratified within block; percentile interval",
            "replicates": replicates,
            "seed": seed,
        },
        "fitness_definition": (
            "lexicographic max: exact_cases, -harmful_overrides, term_correct, "
            "format_valid, then canonical genome hash"
        ),
        "methods": method_summaries,
        "genome_scores": genome_scores,
        "scores": genome_scores,
    }


def compare_methods(
    cases: Sequence[dict[str, Any]], left: str, right: str, replicates: int, seed: int
) -> dict[str, Any]:
    differences = [case["methods"][left]["exact"] - case["methods"][right]["exact"] for case in cases]
    distribution = stratified_bootstrap_means(cases, differences, replicates, seed)
    left_scores = [case["methods"][left]["exact"] for case in cases]
    right_scores = [case["methods"][right]["exact"] for case in cases]
    mcnemar = exact_mcnemar(left_scores, right_scores)
    return {
        "contrast": f"{left} minus {right}",
        "left": left,
        "right": right,
        "n": len(cases),
        "estimate": statistics.fmean(differences),
        "ci95": confidence_interval(distribution, 0.95),
        "ci90": confidence_interval(distribution, 0.90),
        "left_only_wins": mcnemar["left_only"],
        "right_only_wins": mcnemar["right_only"],
        "both_correct": sum(a == 1 and b == 1 for a, b in zip(left_scores, right_scores)),
        "both_wrong": sum(a == 0 and b == 0 for a, b in zip(left_scores, right_scores)),
        "mcnemar": mcnemar,
        "superiority_supported": confidence_interval(distribution, 0.95)[0] > 0.0,
    }


def comparisons(
    cases: Sequence[dict[str, Any]], final_genome: str | None, baselines: Sequence[str],
    replicates: int, seed: int,
) -> dict[str, Any]:
    methods = set(cases[0]["methods"]) if cases else set()
    if final_genome is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "primary": None,
            "comparisons": [],
            "warning": "--final-genome was not supplied; no confirmatory comparison was selected",
        }
    if final_genome not in methods:
        raise ScoreError(f"final genome {final_genome!r} is absent from completed jobs")
    selected_baselines = list(baselines) or [name for name in ("Vote10", "Vote20") if name in methods]
    if not selected_baselines:
        raise ScoreError("no baseline supplied or found")
    missing = [baseline for baseline in selected_baselines if baseline not in methods]
    if missing:
        raise ScoreError(f"baseline(s) absent from completed jobs: {', '.join(missing)}")
    items = [
        compare_methods(cases, final_genome, baseline, replicates, seed + index * 1009)
        for index, baseline in enumerate(selected_baselines)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "direction": "positive favors final_genome",
        "bootstrap_replicates": replicates,
        "bootstrap_seed": seed,
        "primary": items[0],
        "comparisons": items,
    }


def _json_prediction(value: tuple[str, ...] | None) -> str:
    return "" if value is None else json.dumps(list(value), separators=(",", ":"))


def write_case_matrix(path: Path, cases: Sequence[dict[str, Any]]) -> None:
    methods = sorted(cases[0]["methods"], key=_method_sort_key) if cases else []
    fields = ["case_id", "block", "family", "tier", "truth"]
    metric_fields = (
        "prediction", "exact", "term_accuracy", "term_correct", "format_compliant",
        "proposal_plurality", "proposal_plurality_exact", "override", "harmful_override",
        "useful_override", "terminal_job_id", "completed_proposals", "valid_proposals",
        "calls", "input_tokens", "output_tokens", "cost_usd", "latency_ms",
    )
    fields.extend(f"{method}.{metric}" for method in methods for metric in metric_fields)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            output: dict[str, Any] = {
                "case_id": case["case_id"], "block": case["block"],
                "family": case["family"], "tier": case["tier"],
                "truth": _json_prediction(case["truth"]),
            }
            for method in methods:
                result = case["methods"][method]
                for metric in metric_fields:
                    value = result[metric]
                    if metric in {"prediction", "proposal_plurality"}:
                        value = _json_prediction(value)
                    output[f"{method}.{metric}"] = value
            writer.writerow(output)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_score(
    answers_path: Path, predictions_path: Path, out_dir: Path, final_genome: str | None,
    baselines: Sequence[str], replicates: int, seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    answers = load_answers(load_records(answers_path))
    jobs = normalize_completed_jobs(load_records(predictions_path), answers)
    cases, genome_flags = build_case_scores(answers, jobs)
    if not cases or not cases[0]["methods"]:
        raise ScoreError("no scoreable completed architectures")
    summary = summarize(cases, genome_flags, replicates, seed)
    summary["inputs"] = {
        "answers_sha256": file_sha256(answers_path),
        "predictions_sha256": file_sha256(predictions_path),
        "completed_jobs": len(jobs),
    }
    comparison_output = comparisons(cases, final_genome, baselines, replicates, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_case_matrix(out_dir / "case_matrix.csv", cases)
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "comparisons.json", comparison_output)
    return summary, comparison_output


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def self_test() -> None:
    truth_a = ["1", "2", "3", "4", "5"]
    truth_b = ["10", "20", "30", "40", "50"]
    wrong_a = ["1", "2", "3", "4", "9"]
    with tempfile.TemporaryDirectory(prefix="experiment-03-score-") as directory:
        root = Path(directory)
        answers_path = root / "answers.jsonl"
        jobs_path = root / "jobs.jsonl"
        output = root / "results"
        _write_jsonl(answers_path, [
            {"case_id": "C1", "next": truth_a, "family": "F", "tier": "easy"},
            {"case_id": "C2", "next": truth_b, "family": "F", "tier": "hard"},
        ])
        jobs: list[dict[str, Any]] = []
        # C1 Vote10: a 5--5, equal-confidence tie; lexicographic truth wins.
        for number in range(1, 11):
            answer = truth_a if number % 2 else wrong_a
            jobs.append({
                "job_id": f"B1-V{number}", "case_id": "C1", "method": "Vote10",
                "genome_id": "VOTE10", "role": "solver", "stage": "proposer",
                "call_index": number, "status": "completed",
                "output": {"next_five": answer}, "block_id": "B1", "input_tokens": 100,
            })
        for number in range(1, 11):
            jobs.append({
                "job_id": f"B1-V{number}", "case_id": "C2", "method": "Vote10",
                "genome_id": "VOTE10", "role": "solver", "stage": "proposer",
                "call_index": number, "status": "completed",
                "output": {"next_five": truth_a}, "block_id": "B1", "input_tokens": 100,
            })
        # Genome C1 harmful override: correct proposal plurality, wrong final.
        for number, answer in enumerate((truth_a, truth_a, wrong_a), 1):
            jobs.append({
                "job_id": f"C1-GP{number}", "case_id": "C1", "genome_id": "G1",
                "role": "proposal", "slot": f"P{number:02d}", "status": "completed",
                "output": {"next_five": answer}, "block_id": "B1",
            })
        jobs.append({
            "job_id": "C1-GF", "case_id": "C1", "genome_id": "G1", "role": "final",
            "stage_index": 2, "is_final_output": True, "status": "completed",
            "output": {"next_five": wrong_a}, "block_id": "B1",
        })
        # Genome C2 selects a proposal by ID; later stage wins terminal selection.
        jobs.extend([
            {"job_id": "C2-GP1", "case_id": "C2", "genome_id": "G1", "role": "proposal",
             "slot": "P01", "status": "completed", "output": {"next_five": truth_b}, "block_id": "B1"},
            {"job_id": "C2-GF0", "case_id": "C2", "genome_id": "G1", "role": "final",
             "stage_index": 1, "status": "completed", "output": {"next_five": truth_a}, "block_id": "B1"},
            {"job_id": "C2-GF1", "case_id": "C2", "genome_id": "G1", "role": "final",
             "stage_index": 2, "status": "completed", "selected_job_id": "C2-GP1", "block_id": "B1"},
            {"job_id": "ignored", "case_id": "C2", "genome_id": "G1", "role": "proposal",
             "status": "failed", "output": {"next_five": truth_a}},
        ])
        write_json(jobs_path, {"records": jobs})
        summary, comparison = run_score(
            answers_path, jobs_path, output, "G1", ["Vote10"], replicates=250, seed=1234
        )
        assert summary["methods"]["Vote10"]["exact_cases"] == 1
        assert summary["methods"]["Vote10"]["calls"] == 10
        assert summary["methods"]["Vote10"]["input_tokens"] == 1000
        assert summary["methods"]["G1"]["exact_cases"] == 1
        assert summary["methods"]["G1"]["harmful_overrides"] == 1
        assert summary["methods"]["G1"]["term_correct"] == 9
        assert summary["genome_scores"][0]["format_valid"] == 2
        assert summary["methods"]["G1"]["fitness_key_without_hash"] == [1, -1, 9, 2]
        assert comparison["primary"]["estimate"] == 0.0
        assert comparison["primary"]["left_only_wins"] == 1
        assert comparison["primary"]["right_only_wins"] == 1
        assert comparison["primary"]["mcnemar"]["p_value"] == 1.0
        assert parse_prediction(["01", "2", "3", "4", "5"]) is None
        assert parse_prediction([1, "2", "3", "4", "5"]) is None
        first = stratified_bootstrap_means(
            [{"block": "B"}, {"block": "B"}], [0.0, 1.0], 10, 99
        )
        second = stratified_bootstrap_means(
            [{"block": "B"}, {"block": "B"}], [0.0, 1.0], 10, 99
        )
        assert first == second
        assert {path.name for path in output.iterdir()} == {
            "case_matrix.csv", "summary.json", "comparisons.json"
        }
        with (output / "case_matrix.csv").open(encoding="utf-8", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == 2
    print("self-test passed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, help="hidden answer JSONL")
    parser.add_argument("--predictions", type=Path, help="normalized predictions JSON or JSONL")
    parser.add_argument("--jobs", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--out-dir", type=Path, help="directory for the three scored outputs")
    parser.add_argument("--final-genome", help="frozen evolved genome ID for final comparison")
    parser.add_argument(
        "--baseline", action="append", default=[],
        help="baseline method; repeat to compare against multiple baselines (default: present Vote10/Vote20)",
    )
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    predictions = args.predictions or args.jobs
    if args.answers is None or predictions is None or args.out_dir is None:
        raise ScoreError("--answers, --predictions, and --out-dir are required unless --self-test is used")
    summary, comparison = run_score(
        args.answers, predictions, args.out_dir, args.final_genome, args.baseline,
        args.bootstrap_replicates, args.bootstrap_seed,
    )
    print(json.dumps({
        "case_matrix": str(args.out_dir / "case_matrix.csv"),
        "summary": str(args.out_dir / "summary.json"),
        "comparisons": str(args.out_dir / "comparisons.json"),
        "n_cases": summary["n_cases"],
        "primary": comparison.get("primary"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ScoreError) as error:
        print(f"score.py: error: {error}", file=sys.stderr)
        raise SystemExit(2)
