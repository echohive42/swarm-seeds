#!/usr/bin/env python3
"""Deterministically score Experiment 02 raw responses.

The answer manifest is not opened until collection closure has been established.
Only the Python standard library is used so this file is independently auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "experiment-02-scored-v1"
SLOTS = tuple(f"S{i:02d}" for i in range(1, 21))
VOTE_SLOTS = {"Vote10": SLOTS[:10], "Vote20": SLOTS}
INTEGER_RE = re.compile(r"^[+-]?\d+$")
REASONING_LABELS = {
    "low": "Light reasoning",
    "light": "Light reasoning",
    "light reasoning": "Light reasoning",
    "medium": "Medium reasoning",
    "medium reasoning": "Medium reasoning",
}


class ScoreError(ValueError):
    """Raised when inputs cannot be scored without violating the protocol."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ScoreError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _reject_nonfinite(token: str) -> None:
    raise ScoreError(f"non-finite JSON number: {token}")


def parse_json_strict(text: str) -> Any:
    return json.loads(text.strip().lstrip("\ufeff"), object_pairs_hook=_reject_duplicate_pairs,
                      parse_constant=_reject_nonfinite)


def load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_error:
        rows = []
        try:
            for line in text.splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except json.JSONDecodeError:
            raise ScoreError(f"{path} is neither JSON nor JSONL") from json_error
        return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reasoning_label(value: Any) -> str:
    text = str(value if value is not None else "Light reasoning").strip()
    return REASONING_LABELS.get(text.lower(), text)


def canonical_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ScoreError("booleans are not sequence integers")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and INTEGER_RE.fullmatch(value.strip()):
        return int(value)
    raise ScoreError(f"not an integer: {value!r}")


def _unwrap_prediction(value: Any) -> Any:
    if isinstance(value, dict):
        for key in (
            "next_five", "next_terms", "prediction", "predicted_terms",
            "answer", "final_answer", "values", "terms",
        ):
            if key in value:
                return _unwrap_prediction(value[key])
    return value


def parse_prediction(value: Any) -> tuple[tuple[int, ...] | None, bool]:
    """Return canonical five-integer tuple and format compliance.

    A compliant value is a JSON array (possibly inside the documented answer
    object) of exactly five canonical decimal strings. JSON numbers, leading
    zeroes, plus signs, free-form text, and wrong-length arrays are failures.
    """
    value = _unwrap_prediction(value)
    if not isinstance(value, list) or len(value) != 5:
        return None, False
    canonical: list[int] = []
    for item in value:
        if not isinstance(item, str) or not INTEGER_RE.fullmatch(item):
            return None, False
        integer = int(item)
        if item != str(integer):
            return None, False
        canonical.append(integer)
    return tuple(canonical), True


def scored_item_valid(item: Any, schema_name: str) -> bool:
    """Validate the two item schemas that can contribute final scores."""
    if not isinstance(item, dict):
        return False
    common = item.get("case_id")
    answer, answer_valid = parse_prediction(item.get("answer"))
    confidence = item.get("confidence")
    confidence_valid = (
        not isinstance(confidence, bool) and isinstance(confidence, (int, float))
        and 0.0 <= float(confidence) <= 1.0
    )
    if not isinstance(common, str) or not common or answer is None or not answer_valid or not confidence_valid:
        return False
    if schema_name == "solver":
        return set(item) == {"case_id", "answer", "confidence", "rule_summary", "check_summary"} \
            and isinstance(item.get("rule_summary"), str) and len(item["rule_summary"]) <= 180 \
            and isinstance(item.get("check_summary"), str) and len(item["check_summary"]) <= 120
    if schema_name == "judge":
        selected = item.get("selected_candidate_id")
        return set(item) == {"case_id", "answer", "confidence", "selected_candidate_id", "decision_basis"} \
            and (selected is None or isinstance(selected, str)) \
            and isinstance(item.get("decision_basis"), str) and len(item["decision_basis"]) <= 180
    return False


def _first(record: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return default


def execution_metadata_value(data: Any, keys: Iterable[str], default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    for container in (
        data, data.get("execution_metadata"), data.get("schedule_metadata"),
        data.get("collection_metadata"), data.get("execution_schedule"),
    ):
        if isinstance(container, dict):
            value = _first(container, keys)
            if value is not None:
                return value
    return default


def _records_container(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ScoreError("top-level results must be an object or array")
    for key in ("records", "results", "calls", "attempts", "items", "responses"):
        if isinstance(data.get(key), list):
            return data[key]
    return [data]


def flatten_results(data: Any) -> list[dict[str, Any]]:
    """Normalize documented row-, call-, and case-oriented JSON/JSONL forms."""
    output: list[dict[str, Any]] = []

    def visit(record: Any, inherited: dict[str, Any] | None = None) -> None:
        if not isinstance(record, dict):
            return
        base = dict(inherited or {})
        for key in (
            "reasoning", "reasoning_level", "condition", "method", "arm",
            "architecture", "role", "architecture_role", "role_index", "index", "call_id",
            "execution_wave", "block", "block_id",
            "batch", "batch_id", "batch_index", "execution_batch", "schedule_batch",
            "selected_concurrency", "prompt_characters", "prompt_character_count", "prompt_chars",
            "slot", "slot_id", "solver_id", "attempt_id", "confidence",
            "cost_usd", "input_tokens", "output_tokens", "total_tokens",
            "visible_input_token_proxy", "visible_output_token_proxy", "telemetry_source",
            "latency_ms", "status",
        ):
            if key in record:
                base[key] = record[key]

        # One case containing nested solver/method attempts.
        case_id = _first(record, ("case_id", "item_id", "problem_id"))
        nested = _first(record, ("attempts", "responses", "outputs"))
        if case_id is not None and isinstance(nested, list):
            for child in nested:
                visit(child, {**base, "case_id": case_id})
            return

        # One model call containing a mapping/list of answers for a block.
        answers = _first(record, ("answers", "predictions", "case_answers"))
        if isinstance(answers, dict):
            for answer_case_id, answer in answers.items():
                row = {**base, "case_id": str(answer_case_id), "prediction": answer}
                if isinstance(answer, dict):
                    row.update(answer)
                    row["case_id"] = str(answer_case_id)
                output.append(row)
            return
        if isinstance(answers, list) and case_id is None and answers and all(
            isinstance(item, dict) for item in answers
        ):
            for child in answers:
                visit(child, base)
            return

        row = {**base, **record}
        if "case_id" not in row and case_id is not None:
            row["case_id"] = case_id
        output.append(row)

    for top_record in _records_container(data):
        visit(top_record)
    return output


def join_execution_events(manifest_data: Any, attempts_data: Any) -> list[dict[str, Any]]:
    """Join the frozen run manifest to append-only attempt/call_closed events."""
    calls = _records_container(manifest_data)
    call_by_id = {
        str(call["call_id"]): dict(call) for call in calls
        if isinstance(call, dict) and "call_id" in call
    }
    selected_concurrency = execution_metadata_value(manifest_data, (
        "selected_concurrency", "concurrency", "concurrency_cap", "max_concurrency",
    ))
    if isinstance(manifest_data, dict):
        schedules = execution_metadata_value(manifest_data, ("execution_batches", "batch_schedule", "batches"), [])
        if isinstance(schedules, list):
            for batch_index, batch in enumerate(schedules):
                if not isinstance(batch, dict):
                    continue
                batch_id = _first(batch, ("batch_id", "id", "batch_index"), batch_index)
                for call_id in batch.get("call_ids", []):
                    if str(call_id) in call_by_id:
                        call_by_id[str(call_id)]["batch_id"] = batch_id
    for call in call_by_id.values():
        if selected_concurrency is not None:
            call.setdefault("selected_concurrency", selected_concurrency)
    events = _records_container(attempts_data)
    attempt_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    close_events: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict) or "call_id" not in event:
            continue
        call_id = str(event["call_id"])
        event_type = str(event.get("event_type", "attempt"))
        if event_type == "call_closed":
            close_events[call_id] = event
        elif event_type == "attempt":
            attempt_events[call_id].append(event)

    rows: list[dict[str, Any]] = []
    for call_id, call in sorted(call_by_id.items()):
        attempts = sorted(attempt_events.get(call_id, []), key=lambda row: int(row.get("attempt_number", 0)))
        close = close_events.get(call_id)
        selected: dict[str, Any] | None = None
        if close is not None and close.get("selected_attempt") is not None:
            number = int(close["selected_attempt"])
            selected = next((row for row in attempts if int(row.get("attempt_number", 0)) == number), None)
        if selected is None:
            completed = [row for row in attempts if row.get("status") in {"semantic_response", "malformed_output"}]
            selected = completed[0] if completed else None
        if selected is None and len(attempts) >= 3 and all(
            row.get("status") == "infrastructure_failure" for row in attempts
        ):
            raise ScoreError(f"protocol incomplete: {call_id} exhausted infrastructure retries")

        base = dict(call)
        base["reasoning"] = _first(call, ("condition_label", "reasoning", "reasoning_level"))
        base["slot"] = _first(call, ("slot", "slot_id", "solver_id", "role_index", "index"))
        if isinstance(base.get("provider_usage"), dict):
            base.update(base["provider_usage"])
        if selected is not None:
            usage = selected.get("provider_usage")
            if isinstance(usage, dict):
                for target, candidates in {
                    "input_tokens": ("input_tokens", "prompt_tokens"),
                    "output_tokens": ("output_tokens", "completion_tokens"),
                    "total_tokens": ("total_tokens",),
                }.items():
                    value = _first(usage, candidates)
                    if value is not None:
                        base[target] = value
            if selected.get("provider_cost_usd") is not None:
                base["cost_usd"] = selected["provider_cost_usd"]
            if selected.get("latency_ms") is not None:
                base["latency_ms"] = selected["latency_ms"]
            if selected.get("execution_batch") is not None:
                base["execution_batch"] = selected["execution_batch"]
            base["response_characters"] = len(selected.get("response_text", ""))
            base["telemetry_source"] = "provider" if isinstance(usage, dict) else "visible-token proxy"
            if not isinstance(usage, dict):
                prompt_chars = _first(selected, ("prompt_characters", "prompt_character_count", "prompt_chars"))
                if prompt_chars is None:
                    prompt_chars = _first(call, ("prompt_characters", "prompt_character_count", "prompt_chars"))
                if prompt_chars is None:
                    prompt_text = _first(selected, ("prompt_text", "request_text"))
                    prompt_chars = len(prompt_text) if isinstance(prompt_text, str) else None
                if isinstance(prompt_chars, int) and not isinstance(prompt_chars, bool) and prompt_chars >= 0:
                    base["visible_input_token_proxy"] = math.ceil(prompt_chars / 4)
                base["visible_output_token_proxy"] = math.ceil(base["response_characters"] / 4)

        response_text = selected.get("response_text") if selected is not None else None
        parsed_response: Any = None
        if selected is not None and selected.get("status") in {"semantic_response", "malformed_output"} and isinstance(response_text, str):
            try:
                parsed_response = parse_json_strict(response_text)
            except (json.JSONDecodeError, ScoreError):
                parsed_response = None
        if parsed_response is not None:
            if isinstance(parsed_response, dict):
                payload = parsed_response.get("results", parsed_response.get("answers", parsed_response))
            else:
                payload = parsed_response
            expanded = flatten_results([{**base, "answers": payload}])
            if expanded and any(row.get("case_id") is not None for row in expanded):
                schema_name = str(call.get("output_schema", call.get("role", "")))
                item_validity: dict[str, list[bool]] = defaultdict(list)
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict) and item.get("case_id") is not None:
                            item_validity[str(item["case_id"])].append(scored_item_valid(item, schema_name))
                for row in expanded:
                    case_key = str(row.get("case_id"))
                    validations = item_validity.get(case_key, [])
                    row["_schema_compliant"] = len(validations) == 1 and validations[0]
                rows.extend(expanded)
                present = {str(row.get("case_id")) for row in expanded if row.get("case_id") is not None}
                for case_id in call.get("case_ids", []):
                    if str(case_id) not in present:
                        rows.append({**base, "case_id": str(case_id), "prediction": None,
                                     "_schema_compliant": False, "_missing_case_record": True})
                continue

        # Malformed and infrastructure-exhausted calls are failures for every
        # case in the call; represent them explicitly instead of dropping them.
        for case_id in call.get("case_ids", []):
            rows.append({**base, "case_id": str(case_id), "prediction": response_text,
                         "_schema_compliant": False, "_missing_case_record": True})
    return rows


def _closure_value(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    candidates = [data]
    for key in ("metadata", "collection", "status"):
        if isinstance(data.get(key), dict):
            candidates.append(data[key])
    for obj in candidates:
        if obj.get("collection_closed") is True or obj.get("closed") is True:
            return True
        status = str(obj.get("collection_status", obj.get("status", ""))).lower()
        if status in {"closed", "complete", "completed"}:
            return True
    return False


def collection_states(manifest_data: Any, results_data: Any) -> dict[str, Any]:
    calls = _records_container(manifest_data)
    call_ids = {str(call["call_id"]) for call in calls if isinstance(call, dict) and "call_id" in call}
    events = _records_container(results_data)
    by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if isinstance(event, dict) and event.get("call_id") is not None:
            by_call[str(event["call_id"])].append(event)
    call_by_id = {
        str(call["call_id"]): call for call in calls
        if isinstance(call, dict) and "call_id" in call
    }
    terminal = 0
    exhausted = 0
    open_calls: list[str] = []
    for call_id in sorted(call_ids):
        lineage = by_call.get(call_id, [])
        attempts = [event for event in lineage if event.get("event_type") == "attempt"]
        closes = [event for event in lineage if event.get("event_type") == "call_closed"]
        if len(closes) > 1 or any(event.get("event_type") not in {"attempt", "call_closed"} for event in lineage):
            raise ScoreError(f"invalid attempt lineage events for {call_id}")
        request_hash: str | None = None
        terminal_seen = False
        for index, event in enumerate(attempts, 1):
            if event.get("schema_version") != "2.0" or event.get("attempt_number") != index or index > 3:
                raise ScoreError(f"invalid attempt numbering or schema for {call_id}")
            status = event.get("status")
            if status not in {"semantic_response", "malformed_output", "infrastructure_failure"} or terminal_seen:
                raise ScoreError(f"invalid attempt status/order for {call_id}")
            current_request = event.get("request_sha256")
            if not isinstance(current_request, str) or re.fullmatch(r"[0-9a-f]{64}", current_request) is None:
                raise ScoreError(f"missing or invalid request hash for {call_id}")
            if request_hash is not None and request_hash != current_request:
                raise ScoreError(f"request drift across retries for {call_id}")
            request_hash = current_request
            if event.get("prompt_identity_sha256") != call_by_id[call_id].get("prompt_identity_sha256"):
                raise ScoreError(f"prompt identity drift for {call_id}")
            response = event.get("response_text")
            if status == "infrastructure_failure":
                if response is not None or not event.get("error"):
                    raise ScoreError(f"invalid infrastructure failure record for {call_id}")
            else:
                if not isinstance(response, str) or event.get("response_sha256") != hashlib.sha256(response.encode()).hexdigest():
                    raise ScoreError(f"missing response or response hash mismatch for {call_id}")
                if event.get("agent_message_present") is not True:
                    raise ScoreError(f"substantive attempt lacks a final agent_message for {call_id}")
                if event.get("jsonl_integrity") is not True or not isinstance(event.get("stdout_event_count"), int) \
                        or event["stdout_event_count"] <= 0 or int(event.get("jsonl_parse_failures", 0)) != 0:
                    raise ScoreError(f"raw Codex JSONL integrity is not established for {call_id}")
                terminal_seen = True
        if attempts and any(event.get("status") != "infrastructure_failure" for event in attempts[:-1]):
            raise ScoreError(f"retry occurred after a substantive response for {call_id}")
        substantive = [event for event in attempts if event.get("status") in {"semantic_response", "malformed_output"}]
        is_exhausted = len(attempts) >= 3 and all(event.get("status") == "infrastructure_failure" for event in attempts)
        if closes:
            expected_outcome = substantive[0]["status"] if len(substantive) == 1 else \
                "infrastructure_exhausted" if is_exhausted else None
            expected_selected = substantive[0].get("attempt_number") if len(substantive) == 1 else None
            if closes[0].get("outcome") != expected_outcome or closes[0].get("selected_attempt") != expected_selected:
                raise ScoreError(f"invalid close marker for {call_id}")
        if len(substantive) == 1:
            terminal += 1
        elif is_exhausted:
            exhausted += 1
        else:
            open_calls.append(call_id)
    return {"planned": len(call_ids), "terminal": terminal, "infrastructure_exhausted": exhausted,
            "open": open_calls, "unknown_event_calls": sorted(set(by_call) - call_ids)}


def operational_reliability(manifest_data: Any, results_data: Any, *, attempt_log_jsonl: bool) -> dict[str, Any]:
    calls = _records_container(manifest_data)
    call_by_id = {
        str(call["call_id"]): call for call in calls
        if isinstance(call, dict) and call.get("call_id") is not None
    }
    attempts = [
        event for event in _records_container(results_data)
        if isinstance(event, dict) and event.get("event_type") == "attempt"
    ]
    initial = [event for event in attempts if event.get("attempt_number") == 1]
    retries = [event for event in attempts if isinstance(event.get("attempt_number"), int) and event["attempt_number"] > 1]
    by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_condition: dict[str, Counter[str]] = defaultdict(Counter)
    by_block: dict[str, Counter[str]] = defaultdict(Counter)
    exit_codes: Counter[str] = Counter()
    cli_drift = 0
    model_drift = 0
    prompt_identity_drift = 0
    reasoning_drift = 0
    session_resume = 0
    for event in attempts:
        call_id = str(event.get("call_id"))
        by_call[call_id].append(event)
        call = call_by_id.get(call_id, {})
        condition = reasoning_label(call.get("condition_label", call.get("reasoning")))
        block = str(call.get("block_id", "UNSPECIFIED"))
        by_condition[condition]["attempts"] += 1
        by_condition[condition]["initial_attempts"] += event.get("attempt_number") == 1
        by_condition[condition]["retry_attempts"] += isinstance(event.get("attempt_number"), int) and event["attempt_number"] > 1
        by_condition[condition]["infrastructure_failures"] += event.get("status") == "infrastructure_failure"
        by_condition[condition]["malformed_outputs"] += event.get("status") == "malformed_output"
        by_condition[condition]["agent_messages"] += event.get("status") in {"semantic_response", "malformed_output"} \
            and event.get("agent_message_present") is True
        by_condition[condition]["usage_missing"] += not isinstance(event.get("provider_usage"), dict)
        by_condition[condition]["timeouts"] += bool(event.get("timed_out"))
        if event.get("exit_code") is not None:
            exit_codes[str(event["exit_code"])] += 1
        expected_model = call.get("model", manifest_data.get("model") if isinstance(manifest_data, dict) else None)
        observed_model = event.get("provider_model", event.get("requested_model"))
        if observed_model is not None and expected_model is not None and observed_model != expected_model:
            model_drift += 1
            by_block[block]["model_metadata_drift"] += 1
        expected_prompt = call.get("prompt_identity_sha256")
        if event.get("prompt_identity_sha256") != expected_prompt:
            prompt_identity_drift += 1
            by_block[block]["prompt_identity_drift"] += 1
        expected_effort = call.get("reasoning_effort")
        if event.get("reasoning_effort") is not None and event.get("reasoning_effort") != expected_effort:
            reasoning_drift += 1
            by_block[block]["reasoning_metadata_drift"] += 1
        expected_cli = execution_metadata_value(manifest_data, ("codex_cli_version", "cli_version"))
        if event.get("cli_version") is not None and expected_cli is not None and event.get("cli_version") != expected_cli:
            cli_drift += 1
            by_block[block]["cli_metadata_drift"] += 1
        session_resume += bool(event.get("session_resumed") or event.get("resume_session") or event.get("resumed"))
        by_block[block]["attempts"] += 1
        by_block[block]["infrastructure_failures"] += event.get("status") == "infrastructure_failure"
        by_block[block]["timeouts"] += bool(event.get("timed_out"))
        by_block[block]["resource_warnings"] += bool(event.get("resource_warning"))
    exhausted = sum(
        len(rows) >= 3 and all(row.get("status") == "infrastructure_failure" for row in rows)
        for rows in by_call.values()
    )
    selected_concurrency = execution_metadata_value(manifest_data, (
        "selected_concurrency", "concurrency", "concurrency_cap", "max_concurrency",
    ))
    schedules = execution_metadata_value(manifest_data, ("execution_batches", "batch_schedule", "batches"), [])
    substantive = [event for event in attempts if event.get("status") in {"semantic_response", "malformed_output"}]
    raw_captured = sum(
        event.get("jsonl_integrity") is True
        and isinstance(event.get("stdout_event_count"), int)
        and event["stdout_event_count"] > 0
        for event in substantive
    )
    latencies = [float(event["latency_ms"]) for event in attempts if isinstance(event.get("latency_ms"), (int, float))]
    load_gate = execution_metadata_value(manifest_data, (
        "load_gate_evidence", "concurrency_load_gate", "calibration_load_gate", "load_gate",
    ))
    return {
        "requested_model": manifest_data.get("model") if isinstance(manifest_data, dict) else None,
        "codex_cli_version": execution_metadata_value(manifest_data, ("codex_cli_version", "cli_version")),
        "model_catalog_verified": execution_metadata_value(manifest_data, ("model_catalog_verified", "catalog_verified")),
        "reasoning_configuration": manifest_data.get("condition_mapping") if isinstance(manifest_data, dict) else None,
        "planned_calls": len(call_by_id),
        "initial_attempts": len(initial),
        "retry_attempts": len(retries),
        "infrastructure_failures": sum(event.get("status") == "infrastructure_failure" for event in attempts),
        "infrastructure_exhausted": exhausted,
        "substantive_malformed_outputs": sum(event.get("status") == "malformed_output" for event in attempts),
        "final_agent_message_present": sum(
            event.get("status") in {"semantic_response", "malformed_output"}
            and event.get("agent_message_present") is True for event in attempts
        ),
        "exit_code_counts": dict(sorted(exit_codes.items())),
        "timeouts": sum(bool(event.get("timed_out")) for event in attempts),
        "attempt_log_jsonl_present": bool(attempt_log_jsonl),
        "raw_jsonl_present": bool(substantive) and raw_captured == len(substantive),
        "raw_jsonl_captured": raw_captured,
        "raw_jsonl_missing": len(substantive) - raw_captured,
        "jsonl_parse_failures": sum(int(event.get("jsonl_parse_failures", 0)) for event in attempts),
        "usage_telemetry_present": sum(isinstance(event.get("provider_usage"), dict) for event in attempts),
        "usage_telemetry_missing": sum(not isinstance(event.get("provider_usage"), dict) for event in attempts),
        "cli_metadata_drift": cli_drift,
        "model_metadata_drift": model_drift,
        "reasoning_metadata_drift": reasoning_drift,
        "prompt_identity_drift": prompt_identity_drift,
        "session_resume_count": session_resume,
        "selected_concurrency": selected_concurrency,
        "frozen_batch_count": len(schedules) if isinstance(schedules, list) else 0,
        "latency_ms": {
            "observations": len(latencies),
            "mean": statistics.fmean(latencies) if latencies else None,
            "maximum": max(latencies) if latencies else None,
            "over_240_seconds": sum(value >= 240_000 for value in latencies),
        },
        "resource_warnings": sum(bool(event.get("resource_warning")) for event in attempts),
        "load_gate_evidence": load_gate,
        "load_gate_evidence_available": isinstance(load_gate, dict),
        "by_condition": {key: dict(value) for key, value in sorted(by_condition.items())},
        "by_block": {key: dict(value) for key, value in sorted(by_block.items())},
    }


def ensure_collection_closed(
    results_path: Path, results_data: Any, manifest_path: Path | None,
    manifest_data: Any, marker: Path | None,
) -> Path:
    """Verify terminal collection and raw hash before answer truth is accessed."""
    if manifest_path is None or not isinstance(manifest_data, dict):
        raise ScoreError("final scoring requires --manifest to validate all planned call lineages")
    if marker is None or not marker.is_file() or marker.suffix.lower() != ".json":
        raise ScoreError("final scoring requires --collection-closed with a JSON closure receipt")
    marker_data = load_json_or_jsonl(marker)
    if not isinstance(marker_data, dict) or marker_data.get("collection_closed") is not True:
        raise ScoreError("collection closure receipt does not declare collection_closed=true")
    state = collection_states(manifest_data, results_data)
    planned = int(manifest_data.get("planned_call_count", len(manifest_data.get("calls", []))))
    if planned != 400 or state["planned"] != 400:
        raise ScoreError(f"final collection must contain 400 planned calls, found {state['planned']}")
    if state["unknown_event_calls"] or state["open"]:
        raise ScoreError("collection is not terminal for every frozen call")
    if state["infrastructure_exhausted"]:
        raise ScoreError(
            f"protocol incomplete: {state['infrastructure_exhausted']} call(s) exhausted infrastructure retries"
        )
    if state["terminal"] != 400:
        raise ScoreError(f"expected 400 substantive terminal calls, found {state['terminal']}")
    recorded_hash = _first(marker_data, (
        "attempt_log_sha256", "raw_output_sha256", "raw_outputs_sha256",
        "raw_output_manifest_sha256", "results_sha256", "attempts_sha256",
    ))
    actual_hash = file_sha256(results_path)
    if recorded_hash != actual_hash:
        raise ScoreError("closure receipt raw-output SHA-256 does not match the attempt log")
    recorded_manifest = _first(marker_data, ("run_manifest_sha256", "manifest_sha256"))
    if recorded_manifest not in {
        file_sha256(manifest_path), manifest_data.get("manifest_sha256")
    }:
        raise ScoreError("closure receipt run-manifest hash does not match")
    recorded_terminal = _first(marker_data, ("terminal_call_count", "closed_call_count", "completed_calls"))
    if recorded_terminal is not None and int(recorded_terminal) != 400:
        raise ScoreError("closure receipt does not record 400 terminal calls")
    return marker


def block_map_from_data(data: Any) -> dict[str, str]:
    """Extract case-to-block assignments from run manifests or public block tasks.

    Accepted public task records are exactly the frozen ``{case_id, prefix}``
    shape; no target or answer field is needed or inferred.
    """
    mapping: dict[str, str] = {}

    def assign(block: Any, case_ids: Any) -> None:
        if block is None or not isinstance(case_ids, list):
            return
        for item in case_ids:
            case_id = item.get("case_id", item.get("id")) if isinstance(item, dict) else item
            if case_id is None:
                continue
            key, value = str(case_id), str(block)
            if key in mapping and mapping[key] != value:
                raise ScoreError(f"case {key} assigned to conflicting blocks {mapping[key]} and {value}")
            mapping[key] = value

    if isinstance(data, dict):
        # One canonical public block task: {block_id, cases:[{case_id,prefix}]}.
        assign(data.get("block_id"), data.get("cases", data.get("case_ids")))
        blocks = data.get("blocks", data.get("final_blocks"))
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict):
                    assign(block.get("block_id", block.get("id")), block.get("cases", block.get("case_ids")))
        elif isinstance(blocks, dict):
            for block_id, value in blocks.items():
                assign(block_id, value.get("cases", value.get("case_ids")) if isinstance(value, dict) else value)
        for call in data.get("calls", []):
            if isinstance(call, dict):
                assign(call.get("block_id"), call.get("case_ids", call.get("cases")))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                assign(item.get("block_id", item.get("block")), item.get("cases", item.get("case_ids")))
                case_id = item.get("case_id")
                if case_id is not None and item.get("block_id", item.get("block")) is not None:
                    assign(item.get("block_id", item.get("block")), [case_id])
    return mapping


def load_truth(path: Path, block_by_case: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    data = load_json_or_jsonl(path)
    records = _records_container(data)
    truth: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        case_id = _first(record, ("case_id", "id", "item_id", "problem_id"))
        answer = _first(record, (
            "expected_next_five", "next_five", "target", "answer",
            "continuation", "final_terms", "expected", "next",
        ))
        if case_id is None or answer is None:
            continue
        parsed, compliant = parse_prediction(answer)
        if not compliant or parsed is None:
            raise ScoreError(f"answer manifest has invalid five-term truth for {case_id}")
        block = _first(record, ("block", "block_id", "final_block"))
        if block is None and block_by_case is not None:
            block = block_by_case.get(str(case_id))
        if block is None:
            block = "UNSPECIFIED"
        truth[str(case_id)] = {"answer": parsed, "block": str(block)}
    if not truth:
        raise ScoreError("no case truths found in answer manifest")
    return truth


def normalize_slot(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    match = re.fullmatch(r"S(?:LOT)?0*(\d{1,2})", text)
    if match:
        number = int(match.group(1))
        return f"S{number:02d}" if 1 <= number <= 20 else text
    if text.isdigit():
        number = int(text)
        return f"S{number:02d}" if 1 <= number <= 20 else text
    return text


def normalize_method(record: dict[str, Any], slot: str | None) -> str:
    raw = _first(record, ("method", "arm", "architecture", "condition"), "")
    text = str(raw).strip()
    lowered = text.lower().replace("_", " ").replace("-", " ")
    names = {
        "vote10": "Vote10", "vote 10": "Vote10", "vote20": "Vote20", "vote 20": "Vote20",
        "swarm10": "Swarm10", "swarm 10": "Swarm10",
        "tournament20": "Tournament20", "tournament 20": "Tournament20",
        "independent": "Independent", "independent pool": "Independent",
    }
    if lowered in names:
        return names[lowered]
    if slot in SLOTS or lowered in {"independent", "solver", "direct", "direct expected", "pool"}:
        return "Independent"
    return text or "Unknown"


def extract_prediction(record: dict[str, Any]) -> Any:
    return _first(record, (
        "prediction", "predicted_terms", "next_five", "next_terms",
        "final_answer", "answer", "response", "output", "content",
    ))


def numeric_field(record: dict[str, Any], key: str) -> float | int | None:
    value = record.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if key == "cost_usd" and isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) and parsed >= 0 else None
        except ValueError:
            return None
    return None


def score_attempt(record: dict[str, Any], truth: tuple[int, ...]) -> dict[str, Any]:
    prediction, compliant = parse_prediction(extract_prediction(record))
    compliant = compliant and record.get("_schema_compliant", True) is not False
    if not compliant:
        prediction = None
    term_correct = [False] * 5 if prediction is None else [a == b for a, b in zip(prediction, truth)]
    confidence = numeric_field(record, "confidence")
    scored = {
        "slot": normalize_slot(_first(record, ("slot", "slot_id", "solver_id", "attempt_id"))),
        "method": normalize_method(record, normalize_slot(_first(record, ("slot", "slot_id", "solver_id", "attempt_id")))),
        "prediction": list(prediction) if prediction is not None else None,
        "format_compliant": compliant,
        "exact": bool(prediction == truth),
        "term_correct": term_correct,
        "confidence": float(confidence) if confidence is not None else 0.0,
    }
    for key in (
        "cost_usd", "input_tokens", "output_tokens", "total_tokens", "latency_ms",
        "visible_input_token_proxy", "visible_output_token_proxy",
    ):
        value = numeric_field(record, key)
        if value is not None:
            scored[key] = value
    return scored


def vote(attempts_by_slot: dict[str, dict[str, Any]], slots: tuple[str, ...]) -> dict[str, Any]:
    supporters: dict[tuple[int, ...], list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        attempt = attempts_by_slot.get(slot)
        if attempt is not None and attempt["format_compliant"] and attempt["prediction"] is not None:
            supporters[tuple(attempt["prediction"])].append(attempt)
    if not supporters:
        return {"prediction": None, "format_compliant": False, "vote_count": 0, "votes_cast": 0}

    def ranking(item: tuple[tuple[int, ...], list[dict[str, Any]]]) -> tuple[Any, ...]:
        answer, rows = item
        confidences = [float(row.get("confidence", 0.0)) for row in rows]
        # min() chooses the best: negate descending criteria; answer remains ascending.
        return (-len(rows), -sum(confidences), -statistics.median(confidences), answer)

    winner, rows = min(supporters.items(), key=ranking)
    return {
        "prediction": list(winner),
        "format_compliant": True,
        "vote_count": len(rows),
        "votes_cast": sum(len(value) for value in supporters.values()),
        "confidence_sum": sum(float(row.get("confidence", 0.0)) for row in rows),
        "confidence_median": statistics.median(float(row.get("confidence", 0.0)) for row in rows),
    }


def add_correctness(row: dict[str, Any], truth: tuple[int, ...]) -> dict[str, Any]:
    prediction = tuple(row["prediction"]) if row.get("prediction") is not None else None
    row["exact"] = bool(prediction == truth)
    row["term_correct"] = [False] * 5 if prediction is None else [a == b for a, b in zip(prediction, truth)]
    return row


def sum_costs(attempts: Iterable[dict[str, Any]]) -> dict[str, float | int]:
    rows = list(attempts)
    output: dict[str, float | int] = {}
    for key in (
        "cost_usd", "input_tokens", "output_tokens", "total_tokens",
        "visible_input_token_proxy", "visible_output_token_proxy",
    ):
        values = [row[key] for row in rows if key in row]
        if values:
            output[key] = sum(values)
    latencies = [float(row["latency_ms"]) for row in rows if "latency_ms" in row]
    if latencies:
        output["model_seconds"] = sum(latencies) / 1000.0
        batches = [
            _first(row, ("batch_id", "execution_batch", "schedule_batch", "batch", "batch_index"))
            for row in rows if "latency_ms" in row
        ]
        if batches and all(batch is not None for batch in batches):
            grouped: dict[str, list[float]] = defaultdict(list)
            latency_rows = [row for row in rows if "latency_ms" in row]
            for row, batch in zip(latency_rows, batches):
                grouped[str(batch)].append(float(row["latency_ms"]))
            output["critical_path_latency_ms"] = sum(max(values) for values in grouped.values())
    return output


def score_data(results_data: Any, truth: dict[str, dict[str, Any]], *, strict_slots: bool = True) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unknown_cases: set[str] = set()
    for record in flatten_results(results_data):
        case_id = _first(record, ("case_id", "item_id", "problem_id", "id"))
        if case_id is None:
            continue
        case_id = str(case_id)
        if case_id not in truth:
            unknown_cases.add(case_id)
            continue
        reasoning = reasoning_label(_first(record, ("reasoning", "reasoning_level", "model_reasoning")))
        grouped[(reasoning, case_id)].append(score_attempt(record, truth[case_id]["answer"]))
    if unknown_cases:
        raise ScoreError(f"results contain unknown case IDs: {sorted(unknown_cases)[:5]}")
    if not grouped:
        raise ScoreError("no scoreable result rows found")

    cases: list[dict[str, Any]] = []
    warnings: list[str] = []
    for (reasoning, case_id), attempts in sorted(grouped.items()):
        independent: dict[str, dict[str, Any]] = {}
        precomputed: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for attempt in attempts:
            slot = attempt.get("slot")
            if attempt["method"] == "Independent" and slot in SLOTS:
                if slot in independent:
                    raise ScoreError(f"duplicate {reasoning}/{case_id}/{slot}")
                independent[slot] = attempt
            else:
                precomputed[attempt["method"]].append(attempt)
        missing = [slot for slot in SLOTS if slot not in independent]
        if missing and strict_slots:
            raise ScoreError(f"{reasoning}/{case_id} missing independent slots: {', '.join(missing)}")
        if missing:
            warnings.append(f"{reasoning}/{case_id} missing independent slots: {', '.join(missing)}")

        truth_tuple = truth[case_id]["answer"]
        independent_rows = [independent[slot] for slot in SLOTS if slot in independent]
        n = len(independent_rows)
        direct = {
            "prediction": None,
            "format_compliant": sum(row["format_compliant"] for row in independent_rows) / n if n else 0.0,
            "exact": sum(row["exact"] for row in independent_rows) / n if n else 0.0,
            "term_accuracy": sum(sum(row["term_correct"]) for row in independent_rows) / (5 * n) if n else 0.0,
            "per_term": [sum(row["term_correct"][i] for row in independent_rows) / n if n else 0.0 for i in range(5)],
            "attempts": n,
            "deployment_calls": 1,
        }
        direct_cost = sum_costs(independent_rows)
        if direct_cost:
            direct["cost"] = {key: value / n for key, value in direct_cost.items()} if n else {}
            latencies = [float(row["latency_ms"]) for row in independent_rows if "latency_ms" in row]
            if latencies:
                direct["cost"]["critical_path_latency_ms"] = statistics.fmean(latencies)
        methods: dict[str, Any] = {"Direct expected": direct}
        for method, slots in VOTE_SLOTS.items():
            voted = add_correctness(vote(independent, slots), truth_tuple)
            voted["term_accuracy"] = sum(voted["term_correct"]) / 5
            voted["per_term"] = [float(value) for value in voted["term_correct"]]
            voted["deployment_calls"] = len(slots)
            voted_cost = sum_costs(independent[slot] for slot in slots if slot in independent)
            if voted_cost:
                voted["cost"] = voted_cost
            methods[method] = voted
        for method, rows in sorted(precomputed.items()):
            if method in {"Unknown", ""}:
                continue
            # A structured arm normally has one final case answer. Preserve every
            # raw row, but use the last documented final/judge row deterministically.
            judges = [
                row for row in rows
                if str(row.get("role", row.get("architecture_role", ""))).lower()
                in {"judge", "final_judge", "final judge"}
            ]
            if method in {"Swarm10", "Tournament20"} and len(judges) != 1:
                raise ScoreError(
                    f"{reasoning}/{case_id}/{method} requires exactly one final judge, found {len(judges)}"
                )
            chosen = judges[0] if judges else rows[-1]
            chosen["term_accuracy"] = sum(chosen["term_correct"]) / 5
            chosen["per_term"] = [float(value) for value in chosen["term_correct"]]
            chosen["deployment_calls"] = 10 if method == "Swarm10" else 20 if method == "Tournament20" else 1
            structured_cost = sum_costs(rows)
            if structured_cost:
                chosen["cost"] = structured_cost
            methods[method] = chosen
        cases.append({
            "case_id": case_id,
            "block": truth[case_id]["block"],
            "reasoning": reasoning,
            "independent_attempts": independent_rows,
            "methods": methods,
        })
    return {"schema_version": SCHEMA_VERSION, "cases": cases, "warnings": warnings}


def run_score(args: argparse.Namespace) -> dict[str, Any]:
    results_path = Path(args.results)
    answer_path = Path(args.answers)
    results_data = load_json_or_jsonl(results_path)
    manifest_path = Path(args.manifest) if args.manifest else None
    manifest_data: Any = load_json_or_jsonl(manifest_path) if manifest_path is not None else None
    execution_metadata_path = Path(args.execution_metadata) if args.execution_metadata else None
    if execution_metadata_path is not None:
        if not isinstance(manifest_data, dict):
            raise ScoreError("--execution-metadata requires --manifest")
        metadata = load_json_or_jsonl(execution_metadata_path)
        if not isinstance(metadata, dict):
            raise ScoreError("execution metadata must be a JSON object")
        manifest_data = {**manifest_data, "execution_metadata": metadata}
    marker = ensure_collection_closed(
        results_path, results_data, manifest_path, manifest_data,
        Path(args.collection_closed) if args.collection_closed else None,
    )
    reliability = operational_reliability(
        manifest_data, results_data, attempt_log_jsonl=results_path.suffix.lower() == ".jsonl"
    )
    block_by_case: dict[str, str] = {}

    def merge_blocks(new_mapping: dict[str, str]) -> None:
        for case_id, block in new_mapping.items():
            if case_id in block_by_case and block_by_case[case_id] != block:
                raise ScoreError(f"case {case_id} has conflicting block assignments")
            block_by_case[case_id] = block

    if manifest_path is not None:
        merge_blocks(block_map_from_data(manifest_data))
        results_data = join_execution_events(manifest_data, results_data)
        reliability["missing_case_records"] = sum(
            bool(row.get("_missing_case_record")) for row in results_data if isinstance(row, dict)
        )
        missing_by_condition: Counter[str] = Counter()
        missing_by_block: Counter[str] = Counter()
        for row in results_data:
            if isinstance(row, dict) and row.get("_missing_case_record"):
                missing_by_condition[reasoning_label(row.get("reasoning"))] += 1
                missing_by_block[str(row.get("block_id", row.get("block", "UNSPECIFIED")))] += 1
        for condition, count in missing_by_condition.items():
            reliability.setdefault("by_condition", {}).setdefault(condition, {})["missing_case_records"] = count
        for block, count in missing_by_block.items():
            reliability.setdefault("by_block", {}).setdefault(block, {})["missing_case_records"] = count
        for condition in reliability.get("by_condition", {}).values():
            condition.setdefault("missing_case_records", 0)
        for block in reliability.get("by_block", {}).values():
            block.setdefault("missing_case_records", 0)
    case_manifest_path = Path(args.case_manifest) if args.case_manifest else None
    if case_manifest_path is not None:
        merge_blocks(block_map_from_data(load_json_or_jsonl(case_manifest_path)))
    # Flexible row-oriented inputs may carry block_id alongside each case.
    for row in flatten_results(results_data):
        case_id = _first(row, ("case_id", "item_id", "problem_id", "id"))
        block = _first(row, ("block", "block_id", "final_block"))
        if case_id is not None and block is not None:
            existing = block_by_case.get(str(case_id))
            if existing is not None and existing != str(block):
                raise ScoreError(f"case {case_id} has conflicting block assignments")
            block_by_case[str(case_id)] = str(block)
    # Security boundary: this is intentionally the first access to answer_path.
    truth = load_truth(answer_path, block_by_case)
    scored = score_data(results_data, truth, strict_slots=not args.allow_incomplete)
    scored["provenance"] = {
        "results_sha256": file_sha256(results_path),
        "answers_sha256": file_sha256(answer_path),
        "closure_marker": marker.name if marker else "embedded in results metadata",
    }
    if manifest_path is not None:
        scored["provenance"]["run_manifest_sha256"] = file_sha256(manifest_path)
    if case_manifest_path is not None:
        scored["provenance"]["case_manifest_sha256"] = file_sha256(case_manifest_path)
    if execution_metadata_path is not None:
        scored["provenance"]["execution_metadata_sha256"] = file_sha256(execution_metadata_path)
    scored["metadata"] = {
        "collection_closed": True,
        "vote_tie_break": [
            "largest exact-answer count", "largest supporting-confidence sum",
            "largest supporting-confidence median", "numerically smallest integer tuple",
        ],
        "vote10_slots": list(SLOTS[:10]),
        "vote20_slots": list(SLOTS),
        "selected_concurrency": reliability.get("selected_concurrency"),
    }
    scored["operational_reliability"] = reliability
    return scored


def self_test() -> None:
    assert parse_prediction(["1", "-2", "3", "4", "5"]) == ((1, -2, 3, 4, 5), True)
    assert parse_prediction([1, "2", "3", "4", "5"]) == (None, False)
    assert parse_prediction(["01", "2", "3", "4", "5"]) == (None, False)
    assert parse_prediction("the answer is 1,2,3,4,5") == (None, False)
    attempts: dict[str, dict[str, Any]] = {}
    for index, slot in enumerate(SLOTS):
        prediction = [1, 2, 3, 4, 5] if index % 2 == 0 else [1, 2, 3, 4, 6]
        attempts[slot] = {"prediction": prediction, "format_compliant": True, "confidence": 0.5}
    # Equal count/sum/median resolves to numerically smaller full tuple.
    assert vote(attempts, SLOTS)["prediction"] == [1, 2, 3, 4, 5]
    attempts["S02"]["confidence"] = 0.9
    assert vote(attempts, SLOTS)["prediction"] == [1, 2, 3, 4, 6]

    manifest = {"selected_concurrency": 10, "load_gate_evidence": {
        "candidate_concurrency": 20, "initial_infrastructure_failure_rate": 0.01,
        "retries_resolved": True, "latency_stable": True, "resource_warnings": 0,
        "selected_concurrency": 10,
    }, "execution_batches": [{
        "batch_id": "batch-01", "call_ids": ["final-b01-light-independent-s01"],
    }], "calls": [{
        "call_id": "final-b01-light-independent-s01", "block_id": "B01",
        "case_ids": ["C01"], "condition_label": "light", "architecture": "independent",
        "role": "solver", "slot_id": "S01", "prompt_identity_sha256": "a" * 64,
    }]}
    response = json.dumps({
        "schema_version": "2.0", "block_id": "B01",
        "results": [{"case_id": "C01", "answer": ["1", "2", "3", "4", "5"],
                     "confidence": 0.7, "rule_summary": "r", "check_summary": "c"}],
    })
    events = [
        {"event_type": "attempt", "call_id": "final-b01-light-independent-s01",
         "attempt_number": 1, "status": "semantic_response", "response_text": response,
         "prompt_identity_sha256": "a" * 64, "jsonl_integrity": True,
         "stdout_event_count": 2, "agent_message_present": True},
        {"event_type": "call_closed", "call_id": "final-b01-light-independent-s01",
         "selected_attempt": 1, "outcome": "semantic_response"},
    ]
    joined = join_execution_events(manifest, events)
    assert joined[0]["case_id"] == "C01" and joined[0]["architecture"] == "independent"
    assert joined[0]["batch_id"] == "batch-01" and joined[0]["selected_concurrency"] == 10
    assert joined[0]["visible_output_token_proxy"] > 0
    assert parse_prediction(extract_prediction(joined[0])) == ((1, 2, 3, 4, 5), True)
    assert numeric_field({"confidence": "0.9"}, "confidence") is None
    reliability = operational_reliability(manifest, events, attempt_log_jsonl=True)
    assert reliability["selected_concurrency"] == 10 and reliability["raw_jsonl_present"] is True
    assert reliability["load_gate_evidence_available"] is True
    public_task = {"block_id": "B01", "cases": [{"case_id": "C01", "prefix": ["1", "2"]}]}
    assert block_map_from_data(public_task) == {"C01": "B01"}
    assert block_map_from_data({"blocks": [{"block_id": "B01", "case_ids": ["C01"]}]}) == {"C01": "B01"}

    # Integration smoke for the frozen run-manifest, attempt-log, and closure-receipt shapes.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        calls = []
        closure_events = []
        for index in range(400):
            call_id = f"call-{index:03d}"
            prompt_hash = hashlib.sha256(f"prompt-{index}".encode()).hexdigest()
            request_hash = hashlib.sha256(f"request-{index}".encode()).hexdigest()
            response_text = "{}"
            calls.append({"call_id": call_id, "prompt_identity_sha256": prompt_hash})
            closure_events.append({
                "schema_version": "2.0", "event_type": "attempt", "call_id": call_id,
                "attempt_number": 1, "request_sha256": request_hash,
                "prompt_identity_sha256": prompt_hash, "status": "malformed_output",
                "response_text": response_text,
                "response_sha256": hashlib.sha256(response_text.encode()).hexdigest(),
                "agent_message_present": True, "jsonl_integrity": True,
                "stdout_event_count": 1, "jsonl_parse_failures": 0,
            })
        final_manifest = {"planned_call_count": 400, "calls": calls}
        manifest_file = root / "run_manifest.json"
        manifest_file.write_text(json.dumps(final_manifest), encoding="utf-8")
        attempts_file = root / "attempts.jsonl"
        attempts_file.write_text("".join(json.dumps(event) + "\n" for event in closure_events), encoding="utf-8")
        receipt = {
            "collection_closed": True, "terminal_call_count": 400,
            "attempt_log_sha256": file_sha256(attempts_file),
            "run_manifest_sha256": file_sha256(manifest_file),
        }
        receipt_file = root / "collection_closed.json"
        receipt_file.write_text(json.dumps(receipt), encoding="utf-8")
        assert ensure_collection_closed(
            attempts_file, closure_events, manifest_file, final_manifest, receipt_file
        ) == receipt_file
        invalid_events = [dict(event) for event in closure_events]
        invalid_events[0].pop("response_text")
        try:
            collection_states(final_manifest, invalid_events)
        except ScoreError:
            pass
        else:
            raise AssertionError("empty semantic/malformed response passed the closure firewall")

    truth = {"C01": {"answer": (1, 2, 3, 4, 5), "block": "B01"}}
    rows = []
    for slot in SLOTS:
        rows.append({
            "case_id": "C01", "slot": slot, "reasoning": "low",
            "prediction": ["1", "2", "3", "4", "5"], "confidence": 0.5,
        })
    scored = score_data(rows, truth)
    assert scored["cases"][0]["reasoning"] == "Light reasoning"
    assert scored["cases"][0]["methods"]["Direct expected"]["exact"] == 1.0
    assert scored["cases"][0]["methods"]["Vote10"]["exact"] is True
    print("score_results.py self-test: ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", help="raw JSON or JSONL results")
    parser.add_argument("--answers", help="hidden answer-manifest JSON or JSONL")
    parser.add_argument("--manifest", help="run_manifest.json when --results is append-only attempt events")
    parser.add_argument("--case-manifest", help="optional public block/task manifest used only for case-to-block mapping")
    parser.add_argument("--execution-metadata", help="frozen selected-concurrency and actual batch schedule JSON")
    parser.add_argument("--collection-closed", help="JSON collection-close marker")
    parser.add_argument("--output", help="output scored JSON; stdout if omitted")
    parser.add_argument("--allow-incomplete", action="store_true", help="development only: allow missing S01-S20")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.results or not args.answers:
        parser.error("--results and --answers are required unless --self-test is used")
    try:
        scored = run_score(args)
    except (OSError, ScoreError) as error:
        print(f"score error: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(scored, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
