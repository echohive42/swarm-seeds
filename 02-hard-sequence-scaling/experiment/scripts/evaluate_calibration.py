#!/usr/bin/env python3
"""Evaluate the frozen Experiment 02 development and calibration gates.

The report deliberately contains aggregates only. It never reads final truth,
never emits case-level predictions, and never chooses a benchmark based on a
desired method or reasoning contrast. Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "experiment-02-calibration-gate-v1"
MODEL = "gpt-5.6-luna"
EXPECTED_CASES = 12
EXPECTED_SLOTS = tuple(f"S{i:02d}" for i in range(1, 21))
EASIEST_TIER = "hard"
HARDEST_TIER = "stress"
TIERS = ("hard", "very-hard", "stress")
TERMINAL_STATUSES = {"semantic_response", "malformed_output"}
INFRASTRUCTURE_STATUS = "infrastructure_failure"
REQUIRED_DISABLED_FEATURES = {
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "enable_mcp_apps",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "skill_mcp_dependency_install",
    "standalone_web_search",
    "tool_suggest",
    "unified_exec",
    "workspace_dependencies",
}

PREFLIGHT_TRUE_FIELDS = (
    "model_catalog_verified",
    "runner_fixture_passed",
    "prompt_via_stdin",
    "ignore_user_config",
    "ephemeral_sessions",
    "fresh_empty_workdirs",
    "read_only_sandbox",
    "stage_output_schemas",
    "stdout_jsonl_preserved",
    "stderr_preserved",
    "exit_status_preserved",
    "standard_library_only",
    "no_resume_code_path",
    "retry_requires_no_agent_message",
)

PIPELINE_TRUE_FIELDS = (
    "swarm10_fixture_passed",
    "routing_graph_valid",
    "reasoning_isolation_valid",
    "clean_room_replay_identical",
    "malformed_fixture_rejected",
    "retry_identity_preserved",
    "packet_manifest_reproducible",
    "raw_jsonl_reproduces_agent_messages",
    "stderr_exit_joinable",
    "no_packet_over_input_limit",
    "no_silent_response_truncation",
    "no_answer_key_used_for_pipeline_checks",
    "command_contract_all_calls",
)


class GateError(ValueError):
    """Raised when a gate input cannot be evaluated safely."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise GateError(f"invalid JSONL at {path.name}:{line_number}") from exc
    return rows


def load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return load_jsonl(path)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def assert_not_final_input(path: Path, label: str) -> None:
    """Reject final inputs before opening them.

    The calibration gate has no reason to access any path whose basename says
    final. This check happens before file contents are read.
    """

    if "final" in path.name.lower():
        raise GateError(f"{label} must not be a final-split file")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError(f"cannot load required module {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def support_modules() -> tuple[Any, Any]:
    directory = Path(__file__).resolve().parent
    return (
        _load_module(directory / "validate_outputs.py", "experiment02_validate_outputs"),
        _load_module(directory / "run_manifest.py", "experiment02_run_manifest"),
    )


def check(check_id: str, passed: bool, observed: Any, required: Any) -> dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "observed": observed, "required": required}


def checks_pass(checks: Iterable[dict[str, Any]]) -> bool:
    return all(item.get("passed") is True for item in checks)


def manifest_call_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    calls = manifest.get("calls")
    if not isinstance(calls, list):
        raise GateError("run manifest calls must be an array")
    output: dict[str, dict[str, Any]] = {}
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("call_id"), str):
            raise GateError("run manifest contains an invalid call")
        if call["call_id"] in output:
            raise GateError("run manifest contains a duplicate call ID")
        output[call["call_id"]] = call
    return output


def selected_attempts(
    manifest: dict[str, Any], events: list[Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Validate retry lineage and select one substantive terminal attempt per call."""

    calls = manifest_call_map(manifest)
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unknown_events = 0
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("call_id"), str):
            raise GateError("attempt log contains an event without a call ID")
        call_id = event["call_id"]
        if call_id not in calls:
            unknown_events += 1
            continue
        event_type = event.get("event_type")
        if event_type == "attempt":
            attempts[call_id].append(event)
        elif event_type == "call_closed":
            closes[call_id].append(event)
        else:
            raise GateError("attempt log contains an unknown event type")

    selected: dict[str, dict[str, Any]] = {}
    lineage_errors = 0
    retries = 0
    initial_infrastructure_failures = 0
    unresolved = 0
    for call_id, call in calls.items():
        rows = sorted(attempts.get(call_id, []), key=lambda item: item.get("attempt_number", -1))
        numbers = [item.get("attempt_number") for item in rows]
        if numbers != list(range(1, len(rows) + 1)) or not 1 <= len(rows) <= 3:
            lineage_errors += 1
            unresolved += 1
            continue
        prompt_hashes = {item.get("prompt_identity_sha256") for item in rows}
        request_hashes = {item.get("request_sha256") for item in rows}
        if prompt_hashes != {call.get("prompt_identity_sha256")} or len(request_hashes) != 1:
            lineage_errors += 1
        if rows and rows[0].get("status") == INFRASTRUCTURE_STATUS:
            initial_infrastructure_failures += 1
        retries += max(0, len(rows) - 1)
        terminal_rows = [item for item in rows if item.get("status") in TERMINAL_STATUSES]
        if len(terminal_rows) != 1 or rows[-1] is not terminal_rows[0]:
            lineage_errors += 1
            unresolved += 1
            continue
        if any(item.get("status") != INFRASTRUCTURE_STATUS for item in rows[:-1]):
            lineage_errors += 1
        if any(isinstance(item.get("response_text"), str) and item["response_text"].strip()
               for item in rows[:-1]):
            lineage_errors += 1
        close_rows = closes.get(call_id, [])
        if len(close_rows) != 1:
            lineage_errors += 1
            unresolved += 1
            continue
        close = close_rows[0]
        if close.get("outcome") != terminal_rows[0].get("status"):
            lineage_errors += 1
        if close.get("selected_attempt") != terminal_rows[0].get("attempt_number"):
            lineage_errors += 1
        if not isinstance(terminal_rows[0].get("response_text"), str):
            lineage_errors += 1
            unresolved += 1
            continue
        selected[call_id] = terminal_rows[0]

    summary = {
        "planned_calls": len(calls),
        "terminal_calls": len(selected),
        "unresolved_calls": unresolved,
        "unknown_event_count": unknown_events,
        "lineage_error_count": lineage_errors,
        "retry_attempt_count": retries,
        "initial_infrastructure_failure_count": initial_infrastructure_failures,
    }
    return selected, summary


def extract_document(
    validator: Any, attempt: dict[str, Any], call: dict[str, Any]
) -> tuple[Any | None, dict[str, Any]]:
    text = attempt.get("response_text")
    try:
        document, normalizations = validator.parse_json_strict(text)
    except Exception:
        return None, {
            "parseable": False,
            "mapped": False,
            "unknown_ids": 0,
            "duplicate_ids": 0,
            "missing_ids": EXPECTED_CASES,
            "valid_items": 0,
            "normalization_count": 0,
        }
    expected = list(call.get("case_ids", []))
    results = document.get("results") if isinstance(document, dict) else None
    observed = [item.get("case_id") for item in results
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)] \
        if isinstance(results, list) else []
    counts = Counter(observed)
    duplicates = sum(count - 1 for count in counts.values() if count > 1)
    unknown = sum(count for case_id, count in counts.items() if case_id not in set(expected))
    missing = len(set(expected) - set(observed))
    valid_items = 0
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict) or item.get("case_id") not in set(expected):
                continue
            errors = validator.validate_result_item(item, call.get("output_schema", "solver"))
            if not errors:
                valid_items += 1
    mapped = bool(observed) and duplicates == 0 and unknown == 0 and missing == 0 and len(observed) == EXPECTED_CASES
    return document, {
        "parseable": True,
        "mapped": mapped,
        "unknown_ids": unknown,
        "duplicate_ids": duplicates,
        "missing_ids": missing,
        "valid_items": valid_items,
        "normalization_count": len(normalizations),
    }


def validate_auxiliary_reports(
    preflight: dict[str, Any], pipeline: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    preflight_checks = [
        check(f"preflight.{field}", preflight.get(field) is True, preflight.get(field), True)
        for field in PREFLIGHT_TRUE_FIELDS
    ]
    disabled = set(preflight.get("disabled_features", [])) if isinstance(preflight.get("disabled_features"), list) else set()
    preflight_checks.extend([
        check("preflight.requested_model", preflight.get("requested_model") == MODEL,
              preflight.get("requested_model"), MODEL),
        check("preflight.timeout_seconds", preflight.get("timeout_seconds") == 300,
              preflight.get("timeout_seconds"), 300),
        check("preflight.candidate_concurrency", preflight.get("candidate_concurrency") == 20,
              preflight.get("candidate_concurrency"), 20),
        check("preflight.disabled_features", REQUIRED_DISABLED_FEATURES <= disabled,
              len(REQUIRED_DISABLED_FEATURES & disabled), len(REQUIRED_DISABLED_FEATURES)),
        check("preflight.cli_version_present", isinstance(preflight.get("codex_cli_version"), str)
              and bool(preflight["codex_cli_version"].strip()), bool(preflight.get("codex_cli_version")), True),
    ])
    pipeline_checks = [
        check(f"pipeline.{field}", pipeline.get(field) is True, pipeline.get(field), True)
        for field in PIPELINE_TRUE_FIELDS
    ]
    return (
        {"passed": checks_pass(preflight_checks), "checks": preflight_checks,
         "codex_cli_version": preflight.get("codex_cli_version"),
         "requested_model": preflight.get("requested_model"),
         "usage_telemetry_status": preflight.get("usage_telemetry_status", "unavailable")},
        {"passed": checks_pass(pipeline_checks), "checks": pipeline_checks},
    )


def evaluate_development(
    manifest: dict[str, Any], events: list[Any], validator: Any
) -> dict[str, Any]:
    calls = manifest_call_map(manifest)
    selected, lineage = selected_attempts(manifest, events)
    role_counts = Counter((call.get("condition_label"), call.get("architecture"), call.get("role"))
                          for call in calls.values())
    expected_counts = {
        ("light", "independent", "solver"): 1,
        ("medium", "independent", "solver"): 1,
        ("medium", "tournament20", "explorer"): 8,
        ("medium", "tournament20", "breaker"): 4,
        ("medium", "tournament20", "verifier"): 4,
        ("medium", "tournament20", "synthesizer"): 2,
        ("medium", "tournament20", "red_team"): 1,
        ("medium", "tournament20", "judge"): 1,
    }
    mapped_stage_calls = 0
    fully_valid_stage_calls = 0
    nonjudge_fully_valid_calls = 0
    independent_valid_calls = 0
    judge_valid_records = 0
    judge_calls = 0
    unknown_ids = duplicate_ids = missing_ids = 0
    for call_id, attempt in selected.items():
        call = calls[call_id]
        _document, mapping = extract_document(validator, attempt, call)
        unknown_ids += mapping["unknown_ids"]
        duplicate_ids += mapping["duplicate_ids"]
        missing_ids += mapping["missing_ids"]
        if mapping["mapped"]:
            mapped_stage_calls += 1
        if mapping["mapped"] and mapping["valid_items"] == EXPECTED_CASES:
            fully_valid_stage_calls += 1
            if not (call.get("architecture") == "tournament20" and call.get("role") == "judge"):
                nonjudge_fully_valid_calls += 1
            if call.get("architecture") == "independent":
                independent_valid_calls += 1
        if call.get("architecture") == "tournament20" and call.get("role") == "judge":
            judge_calls += 1
            judge_valid_records += mapping["valid_items"]

    checks = [
        check("development.manifest_split", manifest.get("split") == "development",
              manifest.get("split"), "development"),
        check("development.planned_calls", len(calls) == 22, len(calls), 22),
        check("development.role_graph", role_counts == Counter(expected_counts),
              {"matched_roles": sum((role_counts & Counter(expected_counts)).values())},
              {"planned_roles": 22}),
        check("development.terminal_calls", lineage["terminal_calls"] == 22,
              lineage["terminal_calls"], 22),
        check("development.retry_lineage", lineage["lineage_error_count"] == 0,
              lineage["lineage_error_count"], 0),
        check("development.unknown_events", lineage["unknown_event_count"] == 0,
              lineage["unknown_event_count"], 0),
        check("development.all_stage_case_ids_survive", mapped_stage_calls == 22,
              mapped_stage_calls, 22),
        check("development.no_unknown_case_ids", unknown_ids == 0, unknown_ids, 0),
        check("development.no_duplicate_case_ids", duplicate_ids == 0, duplicate_ids, 0),
        check("development.no_missing_case_ids", missing_ids == 0, missing_ids, 0),
        check("development.independent_schema", independent_valid_calls == 2,
              independent_valid_calls, 2),
        check("development.nonjudge_stages_schema", nonjudge_fully_valid_calls == 21,
              nonjudge_fully_valid_calls, "21 of 21"),
        check("development.judge_call_count", judge_calls == 1, judge_calls, 1),
        check("development.judge_valid_records", judge_valid_records >= 11,
              judge_valid_records, ">=11 of 12"),
    ]
    return {
        "passed": checks_pass(checks),
        "checks": checks,
        "call_integrity": lineage,
        "aggregate_schema": {
            "mapped_stage_calls": mapped_stage_calls,
            "fully_valid_stage_calls": fully_valid_stage_calls,
            "nonjudge_fully_valid_calls": nonjudge_fully_valid_calls,
            "final_judge_valid_records": judge_valid_records,
        },
    }


def canonical_answer(item: Any) -> tuple[str, ...] | None:
    if not isinstance(item, list) or len(item) != 5:
        return None
    answer: list[str] = []
    for term in item:
        if not isinstance(term, str):
            return None
        if term == "0":
            answer.append(term)
            continue
        if term.startswith("-"):
            digits = term[1:]
            if not digits or digits[0] == "0" or not digits.isdigit():
                return None
        elif term[0] == "0" or not term.isdigit():
            return None
        answer.append(term)
    return tuple(answer)


def decimal_confidence(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def vote(rows: list[dict[str, Any]]) -> tuple[str, ...] | None:
    support: dict[tuple[str, ...], list[Decimal]] = defaultdict(list)
    for row in rows:
        answer = row.get("answer")
        confidence = row.get("confidence")
        if isinstance(answer, tuple) and confidence is not None:
            support[answer].append(confidence)
    if not support:
        return None
    def key(item: tuple[tuple[str, ...], list[Decimal]]) -> tuple[Any, ...]:
        answer, confidences = item
        numeric_tuple = tuple(int(value) for value in answer)
        return (-len(confidences), -sum(confidences), -Decimal(str(statistics.median(confidences))), numeric_tuple)
    return min(support.items(), key=key)[0]


def load_calibration_truth(path: Path, expected_ids: set[str]) -> dict[str, dict[str, Any]]:
    assert_not_final_input(path, "calibration truth")
    raw = load_json_or_jsonl(path)
    records = raw if isinstance(raw, list) else raw.get("records", []) if isinstance(raw, dict) else []
    truth: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise GateError("calibration truth contains a non-object record")
        if record.get("split") != "calibration":
            raise GateError("calibration truth contains a non-calibration record")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or case_id not in expected_ids or case_id in truth:
            raise GateError("calibration truth case IDs do not match the frozen calibration manifest")
        answer = canonical_answer(record.get("next"))
        tier = record.get("tier")
        if answer is None or tier not in TIERS:
            raise GateError("calibration truth has an invalid answer or tier")
        truth[case_id] = {"answer": answer, "tier": tier}
    if set(truth) != expected_ids:
        raise GateError("calibration truth does not contain exactly the 12 expected cases")
    counts = Counter(record["tier"] for record in truth.values())
    if counts != Counter({tier: 4 for tier in TIERS}):
        raise GateError("calibration truth must contain four cases from each tier")
    return truth


def verify_calibration_truth_identity(path: Path, benchmark_manifest_path: Path) -> None:
    """Verify the calibration truth hash before opening its contents."""

    assert_not_final_input(path, "calibration truth")
    assert_not_final_input(benchmark_manifest_path, "benchmark manifest")
    benchmark_manifest = load_json(benchmark_manifest_path)
    checksums = benchmark_manifest.get("checksums")
    expected = checksums.get("hidden/calibration_answers.jsonl") if isinstance(checksums, dict) else None
    if not isinstance(expected, str) or len(expected) != 64:
        raise GateError("benchmark manifest has no frozen calibration truth checksum")
    if sha256_file(path) != expected:
        raise GateError("calibration truth does not match the frozen calibration checksum")


def evaluate_calibration(
    manifest: dict[str, Any], events: list[Any], truth_path: Path, validator: Any
) -> dict[str, Any]:
    calls = manifest_call_map(manifest)
    case_ids = set(next(iter(calls.values())).get("case_ids", [])) if calls else set()
    if len(case_ids) != EXPECTED_CASES or any(set(call.get("case_ids", [])) != case_ids for call in calls.values()):
        raise GateError("calibration calls do not share one frozen 12-case block")
    truth = load_calibration_truth(truth_path, case_ids)
    selected, lineage = selected_attempts(manifest, events)

    pools: dict[str, dict[str, list[dict[str, Any]]]] = {
        "Light reasoning": defaultdict(list),
        "Medium reasoning": defaultdict(list),
    }
    schema_counts = {
        "Light reasoning": {"valid": 0, "required": 240, "unmappable_calls": 0,
                            "duplicate_case_ids": 0, "unknown_case_ids": 0},
        "Medium reasoning": {"valid": 0, "required": 240, "unmappable_calls": 0,
                             "duplicate_case_ids": 0, "unknown_case_ids": 0},
    }
    observed_slots: dict[str, list[str]] = defaultdict(list)
    for call_id, call in calls.items():
        label = "Light reasoning" if call.get("condition_label") == "light" else "Medium reasoning"
        slot = call.get("slot_id")
        if isinstance(slot, str):
            observed_slots[label].append(slot)
        attempt = selected.get(call_id)
        if attempt is None:
            continue
        document, mapping = extract_document(validator, attempt, call)
        if not mapping["mapped"]:
            schema_counts[label]["unmappable_calls"] += 1
        schema_counts[label]["duplicate_case_ids"] += mapping["duplicate_ids"]
        schema_counts[label]["unknown_case_ids"] += mapping["unknown_ids"]
        results = document.get("results") if isinstance(document, dict) else None
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("case_id"), str):
                    by_case[item["case_id"]].append(item)
        for case_id in case_ids:
            items = by_case.get(case_id, [])
            valid = False
            answer = None
            confidence = None
            if len(items) == 1 and not validator.validate_solver_item(items[0]):
                answer = canonical_answer(items[0].get("answer"))
                confidence = decimal_confidence(items[0].get("confidence"))
                valid = answer is not None and confidence is not None
            if valid:
                schema_counts[label]["valid"] += 1
            pools[label][case_id].append({
                "slot": slot,
                "answer": answer if valid else None,
                "confidence": confidence if valid else None,
                "exact": bool(valid and answer == truth[case_id]["answer"]),
            })

    checks: list[dict[str, Any]] = [
        check("calibration.manifest_split", manifest.get("split") == "calibration",
              manifest.get("split"), "calibration"),
        check("calibration.planned_calls", len(calls) == 40, len(calls), 40),
        check("calibration.terminal_calls", lineage["terminal_calls"] == 40,
              lineage["terminal_calls"], 40),
        check("calibration.retry_lineage", lineage["lineage_error_count"] == 0,
              lineage["lineage_error_count"], 0),
        check("calibration.unknown_events", lineage["unknown_event_count"] == 0,
              lineage["unknown_event_count"], 0),
    ]
    reasoning_aggregates: dict[str, Any] = {}
    vote20_exact_by_label_case: dict[tuple[str, str], bool] = {}
    for label in ("Light reasoning", "Medium reasoning"):
        slots = observed_slots[label]
        checks.extend([
            check(f"calibration.{label}.slots", sorted(slots) == list(EXPECTED_SLOTS),
                  len(set(slots)), 20),
            check(f"calibration.{label}.schema_valid", schema_counts[label]["valid"] >= 228,
                  schema_counts[label]["valid"], ">=228 of 240"),
            check(f"calibration.{label}.unmappable_calls",
                  schema_counts[label]["unmappable_calls"] == 0,
                  schema_counts[label]["unmappable_calls"], 0),
            check(f"calibration.{label}.duplicate_case_ids",
                  schema_counts[label]["duplicate_case_ids"] == 0,
                  schema_counts[label]["duplicate_case_ids"], 0),
            check(f"calibration.{label}.unknown_case_ids",
                  schema_counts[label]["unknown_case_ids"] == 0,
                  schema_counts[label]["unknown_case_ids"], 0),
        ])
        direct_exact = sum(row["exact"] for rows in pools[label].values() for row in rows)
        direct_total = 240
        direct_accuracy = direct_exact / direct_total
        vote10_exact = 0
        vote20_exact = 0
        for case_id in sorted(case_ids):
            by_slot = {row["slot"]: row for row in pools[label][case_id]}
            ten = [by_slot[slot] for slot in EXPECTED_SLOTS[:10] if slot in by_slot]
            twenty = [by_slot[slot] for slot in EXPECTED_SLOTS if slot in by_slot]
            answer10 = vote(ten)
            answer20 = vote(twenty)
            vote10_exact += answer10 == truth[case_id]["answer"]
            exact20 = answer20 == truth[case_id]["answer"]
            vote20_exact += exact20
            vote20_exact_by_label_case[(label, case_id)] = exact20
        checks.extend([
            check(f"calibration.{label}.direct_range", 0.05 <= direct_accuracy <= 0.70,
                  round(direct_accuracy, 6), "0.05 through 0.70 inclusive"),
            check(f"calibration.{label}.vote10_range", 1 <= vote10_exact <= 10,
                  vote10_exact, "1 through 10 of 12"),
            check(f"calibration.{label}.vote20_range", 2 <= vote20_exact <= 10,
                  vote20_exact, "2 through 10 of 12"),
        ])
        reasoning_aggregates[label] = {
            "schema_valid_records": schema_counts[label]["valid"],
            "schema_required_records": 240,
            "direct_exact": direct_exact,
            "direct_total": direct_total,
            "direct_accuracy": round(direct_accuracy, 6),
            "vote10_exact": vote10_exact,
            "vote10_total": 12,
            "vote20_exact": vote20_exact,
            "vote20_total": 12,
        }

    tier_aggregate: dict[str, dict[str, int | float]] = {}
    for tier in TIERS:
        tier_ids = [case_id for case_id, record in truth.items() if record["tier"] == tier]
        exact = sum(vote20_exact_by_label_case[(label, case_id)]
                    for label in reasoning_aggregates for case_id in tier_ids)
        tier_aggregate[tier] = {"exact": exact, "total": 8, "accuracy": round(exact / 8, 6)}
    easiest_exact = int(tier_aggregate[EASIEST_TIER]["exact"])
    hardest_exact = int(tier_aggregate[HARDEST_TIER]["exact"])
    checks.extend([
        check("calibration.tier_manifest", all(tier_aggregate[tier]["total"] == 8 for tier in TIERS),
              {tier: tier_aggregate[tier]["total"] for tier in TIERS}, {tier: 8 for tier in TIERS}),
        check("calibration.easiest_not_floor", easiest_exact >= 2, easiest_exact, ">=2 of 8 exact"),
        check("calibration.hardest_not_ceiling", 8 - hardest_exact >= 2,
              8 - hardest_exact, ">=2 of 8 incorrect"),
        check("calibration.tier_not_inverted", easiest_exact >= hardest_exact,
              {"easiest_exact": easiest_exact, "hardest_exact": hardest_exact},
              "easiest exact >= hardest exact"),
    ])
    return {
        "passed": checks_pass(checks),
        "checks": checks,
        "call_integrity": lineage,
        "reasoning_aggregates": reasoning_aggregates,
        "tier_aggregates": tier_aggregate,
        "forbidden_selection_metrics_used": [],
    }


def evaluate_load_gate(
    load: dict[str, Any], calibration_manifest: dict[str, Any], calibration_events: list[Any]
) -> dict[str, Any]:
    calls = load.get("calls")
    if not isinstance(calls, list):
        raise GateError("load report calls must be an array")
    call_map = manifest_call_map(calibration_manifest)
    call_ids = [item.get("call_id") for item in calls if isinstance(item, dict)]
    manifest_pool = [call_map.get(call_id) for call_id in call_ids]
    one_pool = (
        len(call_ids) == 20
        and len(set(call_ids)) == 20
        and all(call is not None and call.get("architecture") == "independent" for call in manifest_pool)
        and len({call.get("condition_label") for call in manifest_pool if call}) == 1
    )
    raw_attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_closes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in calibration_events:
        if not isinstance(event, dict) or not isinstance(event.get("call_id"), str):
            continue
        if event.get("event_type") == "attempt":
            raw_attempts[event["call_id"]].append(event)
        elif event.get("event_type") == "call_closed":
            raw_closes[event["call_id"]].append(event)
    raw_summaries: list[dict[str, Any]] = []
    operational_evidence_missing = 0
    for item in calls:
        if not isinstance(item, dict) or not isinstance(item.get("call_id"), str):
            operational_evidence_missing += 1
            continue
        call_id = item["call_id"]
        rows = sorted(raw_attempts.get(call_id, []), key=lambda row: row.get("attempt_number", -1))
        closes = raw_closes.get(call_id, [])
        raw_latencies = [row.get("latency_ms") for row in rows
                         if isinstance(row.get("latency_ms"), int)
                         and not isinstance(row.get("latency_ms"), bool)]
        raw_resolved = (
            len(closes) == 1
            and closes[0].get("outcome") in TERMINAL_STATUSES
            and any(row.get("status") in TERMINAL_STATUSES for row in rows)
        )
        required_raw_fields = (
            "jsonl_integrity", "agent_message_present", "process_started", "start_failure",
            "runner_process_crash", "system_crash", "os_kill_resource_exhaustion",
            "session_resumed",
        )
        evidence_complete = bool(rows) and len(raw_latencies) == len(rows) and all(
            all(field in row for field in required_raw_fields) for row in rows
        )
        if not evidence_complete:
            operational_evidence_missing += 1
        terminal_rows = [row for row in rows if row.get("status") in TERMINAL_STATUSES]
        raw_summaries.append({
            "first_attempt_status": rows[0].get("status") if rows else None,
            "resolved": raw_resolved,
            "latency_ms": max(raw_latencies) if raw_latencies else None,
            "jsonl_integrity": bool(rows) and all(
                row.get("jsonl_integrity") is True
                and row.get("jsonl_parse_failures", 0) == 0 for row in rows
            ),
            "agent_message_present": len(terminal_rows) == 1
            and terminal_rows[0].get("agent_message_present") is True,
            "crash": any(row.get("runner_process_crash") is True
                         or row.get("system_crash") is True for row in rows),
            "os_kill_or_resource_exhaustion": any(
                row.get("os_kill_resource_exhaustion") is True for row in rows
            ),
            "session_resumed": any(row.get("session_resumed") is True for row in rows),
            "unable_to_start": any(row.get("start_failure") is True
                                   or row.get("process_started") is not True for row in rows),
            "critical_resource_warning": any(bool(row.get("resource_warning")) for row in rows),
            "timed_out": any(row.get("timed_out") is True for row in rows),
        })
    initial_failures = sum(item["first_attempt_status"] == INFRASTRUCTURE_STATUS
                           for item in raw_summaries)
    unresolved = sum(item["resolved"] is not True for item in raw_summaries)
    crashes = sum(item["crash"] for item in raw_summaries)
    kills = sum(item["os_kill_or_resource_exhaustion"] for item in raw_summaries)
    corrupted = sum(item["jsonl_integrity"] is not True for item in raw_summaries)
    missing_messages = sum(item["agent_message_present"] is not True for item in raw_summaries)
    resumes = sum(item["session_resumed"] is True for item in raw_summaries)
    unable = sum(item["unable_to_start"] is True for item in raw_summaries)
    critical = sum(item["critical_resource_warning"] is True for item in raw_summaries)
    latencies = [item["latency_ms"] for item in raw_summaries
                 if isinstance(item["latency_ms"], int) and not isinstance(item["latency_ms"], bool)]
    slow = sum(value >= 240_000 for value in latencies)
    timeouts = sum(item["timed_out"] is True for item in raw_summaries)
    deadlock = load.get("deadlock") is True
    max_active = load.get("max_active_processes")
    candidate = load.get("candidate_concurrency")
    timeout = load.get("timeout_seconds")
    checks20 = [
        check("load.zero_unresolved", unresolved == 0, unresolved, 0),
        check("load.zero_crashes", crashes == 0, crashes, 0),
        check("load.zero_os_kills_or_exhaustion", kills == 0, kills, 0),
        check("load.zero_corrupted_jsonl", corrupted == 0, corrupted, 0),
        check("load.all_terminal_agent_messages_present", missing_messages == 0,
              missing_messages, 0),
        check("load.zero_resumes", resumes == 0, resumes, 0),
        check("load.initial_infrastructure_failure_rate", initial_failures <= 1,
              initial_failures, "<=1 of 20"),
        check("load.slow_or_timeout_calls", slow < 2 and timeouts < 2,
              {"crossed_240_seconds": slow, "timed_out": timeouts}, "fewer than 2 each"),
        check("load.zero_deadlock_or_critical_warning_or_start_failure",
              not deadlock and critical == 0 and unable == 0,
              {"deadlock": deadlock, "critical_warnings": critical, "unable_to_start": unable},
              {"deadlock": False, "critical_warnings": 0, "unable_to_start": 0}),
    ]
    stable_at_20 = checks_pass(checks20)
    selected_concurrency = 20 if stable_at_20 else 10
    evidence_checks = [
        check("load.frozen_pool", one_pool, len(set(call_ids)), "one frozen 20-call independent pool"),
        check("load.candidate_concurrency", candidate == 20, candidate, 20),
        check("load.timeout_seconds", timeout == 300, timeout, 300),
        check("load.max_active_processes", max_active == 20, max_active, 20),
        check("load.latency_evidence_complete", len(latencies) == 20, len(latencies), 20),
        check("load.raw_operational_evidence_complete", operational_evidence_missing == 0,
              operational_evidence_missing, 0),
        check("load.all_calls_resolved", unresolved == 0, unresolved, 0),
        check("load.no_session_resume", resumes == 0, resumes, 0),
        check("load.no_lost_evidence", corrupted == 0, corrupted, 0),
    ]
    sorted_latency = sorted(latencies)
    latency_summary = {
        "count": len(latencies),
        "minimum_ms": min(latencies) if latencies else None,
        "median_ms": int(statistics.median(latencies)) if latencies else None,
        "p95_ms": sorted_latency[math.ceil(0.95 * len(sorted_latency)) - 1] if sorted_latency else None,
        "maximum_ms": max(latencies) if latencies else None,
    }
    return {
        "passed": checks_pass(evidence_checks),
        "stable_at_20": stable_at_20,
        "selected_final_concurrency": selected_concurrency,
        "selection_rule": "20 only if every monitored 20-process condition passes; otherwise 10",
        "checks_at_20": checks20,
        "evidence_checks": evidence_checks,
        "operational_aggregates": {
            "initial_infrastructure_failures": initial_failures,
            "unresolved_infrastructure_failures": unresolved,
            "crash_flags": crashes,
            "os_kill_or_resource_exhaustion_flags": kills,
            "corrupted_jsonl_streams": corrupted,
            "missing_terminal_agent_messages": missing_messages,
            "session_resumes": resumes,
            "calls_crossing_240_seconds": slow,
            "hard_timeouts": timeouts,
            "critical_resource_warnings": critical,
            "unable_to_start": unable,
            "calls_missing_raw_operational_evidence": operational_evidence_missing,
            "latency": latency_summary,
        },
    }


def evaluate(
    development_manifest_path: Path,
    development_attempts_path: Path,
    calibration_manifest_path: Path,
    calibration_attempts_path: Path,
    calibration_truth_path: Path,
    benchmark_manifest_path: Path,
    preflight_path: Path,
    pipeline_path: Path,
    load_path: Path,
    candidate_number: int = 1,
) -> dict[str, Any]:
    if candidate_number != 1:
        raise GateError("this protocol defines exactly one calibration candidate")
    for path, label in (
        (development_manifest_path, "development manifest"),
        (development_attempts_path, "development attempts"),
        (calibration_manifest_path, "calibration manifest"),
        (calibration_attempts_path, "calibration attempts"),
        (calibration_truth_path, "calibration truth"),
        (benchmark_manifest_path, "benchmark manifest"),
    ):
        assert_not_final_input(path, label)
    validator, run_manifest = support_modules()
    development_manifest = load_json(development_manifest_path)
    calibration_manifest = load_json(calibration_manifest_path)
    if development_manifest.get("split") != "development" or calibration_manifest.get("split") != "calibration":
        raise GateError("manifest split labels must be development and calibration")
    try:
        run_manifest.validate_manifest(development_manifest)
        run_manifest.validate_manifest(calibration_manifest)
    except Exception as exc:
        raise GateError(f"run manifest validation failed: {exc}") from exc
    development_events = load_jsonl(development_attempts_path)
    calibration_events = load_jsonl(calibration_attempts_path)
    verify_calibration_truth_identity(calibration_truth_path, benchmark_manifest_path)
    preflight = load_json(preflight_path)
    pipeline = load_json(pipeline_path)
    load = load_json(load_path)
    if not all(isinstance(item, dict) for item in (preflight, pipeline, load)):
        raise GateError("preflight, pipeline, and load reports must be JSON objects")

    preflight_result, pipeline_result = validate_auxiliary_reports(preflight, pipeline)
    development_result = evaluate_development(development_manifest, development_events, validator)
    calibration_result = evaluate_calibration(
        calibration_manifest, calibration_events, calibration_truth_path, validator
    )
    load_result = evaluate_load_gate(load, calibration_manifest, calibration_events)
    sections = {
        "cli_preflight": preflight_result,
        "development_pipeline": development_result,
        "pipeline_audit": pipeline_result,
        "calibration": calibration_result,
        "load_gate": load_result,
    }
    failed_checks = sorted(
        item["check_id"]
        for section in sections.values()
        for group in (section.get("checks", []), section.get("checks_at_20", []),
                      section.get("evidence_checks", []))
        for item in group
        if item.get("passed") is not True
        and not (group is section.get("checks_at_20", []) and load_result["passed"])
    )
    required_pass = all(section.get("passed") is True for section in sections.values())
    failure_classifications: list[str] = []
    pipeline_failed = not all(
        sections[name]["passed"] for name in ("cli_preflight", "development_pipeline", "pipeline_audit")
    )
    load_failed = not load_result["passed"]
    calibration_failed_ids = [
        item["check_id"] for item in calibration_result["checks"] if item.get("passed") is not True
    ]
    difficulty_markers = (
        ".direct_range", ".vote10_range", ".vote20_range", ".easiest_not_floor",
        ".hardest_not_ceiling", ".tier_not_inverted",
    )
    difficulty_failed = any(any(marker in check_id for marker in difficulty_markers)
                            for check_id in calibration_failed_ids)
    reliability_failed = any(not any(marker in check_id for marker in difficulty_markers)
                             for check_id in calibration_failed_ids)
    if pipeline_failed:
        failure_classifications.append("pipeline_or_schema_failure")
    if reliability_failed or load_failed:
        failure_classifications.append("reliability_failure")
    if difficulty_failed:
        failure_classifications.append("difficulty_failure")
    if required_pass:
        next_action = "proceed_to_final_freeze"
    elif pipeline_failed:
        next_action = "return_to_development_and_rerun_the_affected_smoke_path"
    elif calibration_failed_ids:
        next_action = "stop_experiment_02_and_redesign_under_a_new_protocol_version"
    else:
        next_action = "repair_operational_evidence_before_final_collection"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "experiment_id": "swarm-seeds-02",
        "passed": required_pass,
        "decision": "proceed_to_final_freeze" if required_pass else "stop_before_final_collection",
        "candidate_number": candidate_number,
        "failure_classifications": failure_classifications,
        "next_action": next_action,
        "selected_final_concurrency": load_result["selected_final_concurrency"],
        "failed_required_checks": failed_checks,
        "correctness_firewall": {
            "final_inputs_accessed": False,
            "final_correctness_inspected": False,
            "case_level_calibration_values_emitted": False,
            "selection_metrics_used": [
                "schema reliability",
                "Direct expected exact accuracy range",
                "Vote10 exact range",
                "Vote20 exact range",
                "pooled Vote20 tier coverage",
            ],
        },
        "inputs": {
            "development_manifest_sha256": sha256_file(development_manifest_path),
            "development_attempts_sha256": sha256_file(development_attempts_path),
            "calibration_manifest_sha256": sha256_file(calibration_manifest_path),
            "calibration_attempts_sha256": sha256_file(calibration_attempts_path),
            "calibration_truth_sha256": sha256_file(calibration_truth_path),
            "benchmark_manifest_sha256": sha256_file(benchmark_manifest_path),
            "preflight_report_sha256": sha256_file(preflight_path),
            "pipeline_report_sha256": sha256_file(pipeline_path),
            "load_report_sha256": sha256_file(load_path),
        },
        **sections,
    }
    report["report_sha256"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    return report


def synthetic_item(role: str, case_id: str, answer: list[str], confidence: float = 0.7) -> dict[str, Any]:
    if role in {"solver", "explorer", "proposer"}:
        return {"case_id": case_id, "answer": answer, "confidence": confidence,
                "rule_summary": "Synthetic exact rule.", "check_summary": "Checked."}
    if role in {"critic", "breaker"}:
        return {"case_id": case_id, "supported_candidates": ["C1"], "rejections": [],
                "alternative_answer": None, "confidence": confidence, "summary": "Supported."}
    if role == "verifier":
        return {"case_id": case_id, "ranked_candidates": [], "recommended_answer": answer,
                "confidence": confidence, "check_summary": "Verified."}
    if role == "synthesizer":
        choice = {"candidate_id": "C1", "answer": answer}
        return {"case_id": case_id, "champion": choice,
                "runner_up": {"candidate_id": "C2", "answer": answer},
                "confidence": confidence, "decision_basis": "Synthetic fusion."}
    if role == "red_team":
        return {"case_id": case_id, "attacks": [
            {"synthesizer_id": "SY1", "verdict": "survives", "issue": "No issue."},
            {"synthesizer_id": "SY2", "verdict": "uncertain", "issue": "Minor issue."},
        ], "alternative_answer": None, "confidence": confidence, "summary": "Checked."}
    if role == "judge":
        return {"case_id": case_id, "answer": answer, "confidence": confidence,
                "selected_candidate_id": "C1", "decision_basis": "Synthetic decision."}
    raise AssertionError(role)


def synthetic_manifest(split: str, prompts: Path, run_manifest: Any) -> dict[str, Any]:
    prefix = [str(index) for index in range(12)]
    letter = "D" if split == "development" else "C"
    cases = [{"case_id": f"{letter}{index:02d}", "prefix": prefix} for index in range(1, 13)]
    return run_manifest.build_manifest(cases, prompts, split=split, seed=f"self-test-{split}")


def synthetic_events(manifest: dict[str, Any], truth: dict[str, list[str]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in manifest["calls"]:
        slot = call["slot_id"]
        role = call["role"]
        results = []
        for index, case_id in enumerate(call["case_ids"], 1):
            correct = index <= 5
            answer = truth[case_id] if correct else [str(-1000 - index)] * 5
            results.append(synthetic_item(role, case_id, answer))
        response = json.dumps({"schema_version": "2.0", "block_id": call["block_id"], "results": results})
        attempt = {
            "schema_version": "2.0", "event_type": "attempt", "call_id": call["call_id"],
            "attempt_number": 1, "request_sha256": "a" * 64,
            "prompt_identity_sha256": call["prompt_identity_sha256"],
            "status": "semantic_response", "timed_out": False,
            "latency_ms": 1000 + call["schedule_index"], "response_text": response,
            "jsonl_integrity": True, "jsonl_parse_failures": 0,
            "agent_message_present": True, "process_started": True,
            "start_failure": False, "runner_process_crash": False,
            "system_crash": False, "os_kill_resource_exhaustion": False,
            "session_resumed": False,
        }
        close = {"schema_version": "2.0", "event_type": "call_closed", "call_id": call["call_id"],
                 "outcome": "semantic_response", "selected_attempt": 1}
        events.extend([attempt, close])
    return events


def _self_test() -> None:
    validator, run_manifest = support_modules()
    del validator
    lower = ("1", "2", "3", "4", "5")
    higher = ("2", "3", "4", "5", "6")
    assert vote([
        {"answer": lower, "confidence": Decimal("0.9")},
        {"answer": lower, "confidence": Decimal("0.1")},
        {"answer": higher, "confidence": Decimal("0.6")},
        {"answer": higher, "confidence": Decimal("0.4")},
    ]) == lower
    assert vote([
        {"answer": lower, "confidence": Decimal("0.2")},
        {"answer": higher, "confidence": Decimal("0.8")},
    ]) == higher
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prompts = root / "prompts"
        prompts.mkdir()
        names = {"COMMON_PREFIX.txt", "ROLE_CATALOG.json", "SCHEMAS.json"}
        for roles in run_manifest.ROLE_PLAN.values():
            names.update(role[2] for role in roles)
        for name in names:
            (prompts / name).write_text(f"self-test {name}\n", encoding="utf-8")
        development = synthetic_manifest("development", prompts, run_manifest)
        calibration = synthetic_manifest("calibration", prompts, run_manifest)
        truth = {f"C{index:02d}": [str(index * 10 + offset) for offset in range(5)]
                 for index in range(1, 13)}
        truth_rows = [
            {"case_id": case_id, "split": "calibration", "tier": TIERS[(index - 1) // 4],
             "next": answer}
            for index, (case_id, answer) in enumerate(truth.items(), 1)
        ]
        paths = {
            "development_manifest": root / "development_manifest.json",
            "development_attempts": root / "development_attempts.jsonl",
            "calibration_manifest": root / "calibration_manifest.json",
            "calibration_attempts": root / "calibration_attempts.jsonl",
            "calibration_truth": root / "calibration_truth.jsonl",
            "benchmark_manifest": root / "benchmark_manifest.json",
            "preflight": root / "preflight.json",
            "pipeline": root / "pipeline.json",
            "load": root / "load.json",
        }
        paths["development_manifest"].write_text(json.dumps(development), encoding="utf-8")
        paths["calibration_manifest"].write_text(json.dumps(calibration), encoding="utf-8")
        development_events = synthetic_events(development, {f"D{i:02d}": [str(i)] * 5 for i in range(1, 13)})
        calibration_events = synthetic_events(calibration, truth)
        paths["development_attempts"].write_text(
            "".join(json.dumps(row) + "\n" for row in development_events), encoding="utf-8"
        )
        paths["calibration_attempts"].write_text(
            "".join(json.dumps(row) + "\n" for row in calibration_events), encoding="utf-8"
        )
        paths["calibration_truth"].write_text(
            "".join(json.dumps(row) + "\n" for row in truth_rows), encoding="utf-8"
        )
        paths["benchmark_manifest"].write_text(json.dumps({
            "checksums": {
                "hidden/calibration_answers.jsonl": sha256_file(paths["calibration_truth"]),
            }
        }), encoding="utf-8")
        preflight = {field: True for field in PREFLIGHT_TRUE_FIELDS}
        preflight.update({
            "requested_model": MODEL, "timeout_seconds": 300, "candidate_concurrency": 20,
            "disabled_features": sorted(REQUIRED_DISABLED_FEATURES),
            "codex_cli_version": "codex-cli 0.144.3", "usage_telemetry_status": "available",
        })
        pipeline = {field: True for field in PIPELINE_TRUE_FIELDS}
        pool = [call for call in calibration["calls"] if call["condition_label"] == "light"]
        load = {
            "candidate_concurrency": 20, "timeout_seconds": 300, "max_active_processes": 20,
            "deadlock": False,
            "calls": [
                {"call_id": call["call_id"], "first_attempt_status": "semantic_response",
                 "resolved": True, "latency_ms": 1000 + call["schedule_index"],
                 "jsonl_integrity": True, "process_crash": False, "runner_crash": False,
                 "system_crash": False, "os_kill": False, "resource_exhaustion": False,
                 "session_resumed": False, "unable_to_start": False,
                 "critical_resource_warning": False, "timed_out": False}
                for index, call in enumerate(pool)
            ],
        }
        paths["preflight"].write_text(json.dumps(preflight), encoding="utf-8")
        paths["pipeline"].write_text(json.dumps(pipeline), encoding="utf-8")
        paths["load"].write_text(json.dumps(load), encoding="utf-8")
        report = evaluate(*paths.values())
        assert report["passed"], report["failed_required_checks"]
        assert report["selected_final_concurrency"] == 20
        assert report["calibration"]["reasoning_aggregates"]["Light reasoning"]["vote20_exact"] == 5
        serialized_report = json.dumps(report)
        assert all(f'"C{index:02d}"' not in serialized_report for index in range(1, 13))

        degraded_events = load_jsonl(paths["calibration_attempts"])
        for event in degraded_events:
            if event.get("event_type") == "attempt" and event.get("call_id") == pool[0]["call_id"]:
                event["resource_warning"] = "critical resource warning"
        paths["calibration_attempts"].write_text(
            "".join(json.dumps(row) + "\n" for row in degraded_events), encoding="utf-8"
        )
        fallback = evaluate(*paths.values())
        assert fallback["passed"] and fallback["selected_final_concurrency"] == 10

        forbidden = root / "final_answers.jsonl"
        forbidden.write_text("{}\n", encoding="utf-8")
        try:
            evaluate(paths["development_manifest"], paths["development_attempts"],
                     paths["calibration_manifest"], paths["calibration_attempts"], forbidden,
                     paths["benchmark_manifest"], paths["preflight"], paths["pipeline"],
                     paths["load"])
        except GateError:
            pass
        else:
            raise AssertionError("final truth path was not rejected")
    print("evaluate_calibration.py self-test: PASS")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--self-test", action="store_true", help="run deterministic fixture tests and exit")
    result.add_argument("--development-manifest", type=Path)
    result.add_argument("--development-attempts", type=Path)
    result.add_argument("--calibration-manifest", type=Path)
    result.add_argument("--calibration-attempts", type=Path)
    result.add_argument("--calibration-truth", type=Path)
    result.add_argument("--benchmark-manifest", type=Path)
    result.add_argument("--preflight-report", type=Path)
    result.add_argument("--pipeline-report", type=Path)
    result.add_argument("--load-report", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--candidate-number", type=int, choices=(1,), default=1)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    required = (
        args.development_manifest, args.development_attempts, args.calibration_manifest,
        args.calibration_attempts, args.calibration_truth, args.benchmark_manifest,
        args.preflight_report,
        args.pipeline_report, args.load_report, args.output,
    )
    if any(path is None for path in required):
        raise GateError("all evaluation inputs and --output are required")
    report = evaluate(
        args.development_manifest,
        args.development_attempts,
        args.calibration_manifest,
        args.calibration_attempts,
        args.calibration_truth,
        args.benchmark_manifest,
        args.preflight_report,
        args.pipeline_report,
        args.load_report,
        args.candidate_number,
    )
    atomic_write_json(args.output, report)
    print(json.dumps({
        "passed": report["passed"],
        "decision": report["decision"],
        "selected_final_concurrency": report["selected_final_concurrency"],
        "output": str(args.output),
        "report_sha256": report["report_sha256"],
    }, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)
