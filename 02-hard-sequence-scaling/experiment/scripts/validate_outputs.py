#!/usr/bin/env python3
"""Strict validators and failure classification for Swarm Seeds experiment 02.

Only the Python standard library is used. The public schemas are frozen in
../prompts/SCHEMAS.json; this module implements the same constraints without a
third-party JSON Schema dependency.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "2.0"
EXPECTED_CASE_COUNT = 12
DECIMAL_RE = re.compile(r"^(0|-?[1-9][0-9]*)$")
SCHEMA_NAMES = ("task", "solver", "critic", "breaker", "verifier", "synthesizer", "red_team", "judge")


class StrictJSONError(ValueError):
    """Raised when a response is not one strict JSON value."""


class DuplicateKeyError(StrictJSONError):
    """Raised when a JSON object repeats a key."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> None:
    raise StrictJSONError(f"non-finite JSON number is forbidden: {token}")


def parse_json_strict(text: str) -> tuple[Any, list[str]]:
    """Parse one JSON value, rejecting duplicate keys and non-finite numbers.

    A leading UTF-8 BOM and surrounding whitespace are the only deterministic
    transport normalizations. They are reported so the raw response can remain
    preserved in the audit log.
    """

    if not isinstance(text, str):
        raise StrictJSONError("raw output must be text")
    repairs: list[str] = []
    normalized = text
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]
        repairs.append("removed_utf8_bom")
    stripped = normalized.strip()
    if stripped != normalized:
        repairs.append("trimmed_outer_whitespace")
    if not stripped:
        raise StrictJSONError("empty response")
    try:
        value = json.loads(
            stripped,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, DuplicateKeyError, StrictJSONError) as exc:
        raise StrictJSONError(str(exc)) from exc
    return value, repairs


def _path(parent: str, child: str | int) -> str:
    return f"{parent}[{child}]" if isinstance(child, int) else f"{parent}.{child}"


def _exact_keys(value: Any, required: Iterable[str], path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return False
    expected = set(required)
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        errors.append(f"{path}: missing properties {missing}")
    if extra:
        errors.append(f"{path}: extra properties {extra}")
    return not missing and not extra


def _string(value: Any, path: str, errors: list[str], *, minimum: int = 0, maximum: int | None = None) -> bool:
    if not isinstance(value, str):
        errors.append(f"{path}: expected string")
        return False
    if len(value) < minimum:
        errors.append(f"{path}: string shorter than {minimum}")
        return False
    if maximum is not None and len(value) > maximum:
        errors.append(f"{path}: string longer than {maximum}")
        return False
    return True


def _decimal_string(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or DECIMAL_RE.fullmatch(value) is None:
        errors.append(f"{path}: expected canonical decimal string")
        return False
    return True


def _answer(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path}: expected array of five decimal strings")
        return False
    if len(value) != 5:
        errors.append(f"{path}: expected exactly five terms, got {len(value)}")
    valid = len(value) == 5
    for index, term in enumerate(value):
        valid = _decimal_string(term, _path(path, index), errors) and valid
    return valid


def _confidence(value: Any, path: str, errors: list[str]) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path}: expected finite number from 0 through 1")
        return False
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        errors.append(f"{path}: expected finite number from 0 through 1")
        return False
    return True


def _integer_range(value: Any, path: str, errors: list[str], minimum: int, maximum: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        errors.append(f"{path}: expected integer from {minimum} through {maximum}")
        return False
    return True


def _candidate_id(value: Any, path: str, errors: list[str]) -> bool:
    return _string(value, path, errors, minimum=1, maximum=40)


def _base_document(document: Any, errors: list[str]) -> tuple[str | None, list[Any] | None]:
    if not _exact_keys(document, ("schema_version", "block_id", "results"), "$", errors):
        if not isinstance(document, dict):
            return None, None
    if not isinstance(document, dict):
        return None, None
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version: expected {SCHEMA_VERSION!r}")
    block_id = document.get("block_id")
    _string(block_id, "$.block_id", errors, minimum=1, maximum=80)
    results = document.get("results")
    if not isinstance(results, list):
        errors.append("$.results: expected array")
        return block_id if isinstance(block_id, str) else None, None
    if len(results) != EXPECTED_CASE_COUNT:
        errors.append(f"$.results: expected exactly {EXPECTED_CASE_COUNT} results, got {len(results)}")
    return block_id if isinstance(block_id, str) else None, results


def validate_solver_item(item: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "answer", "confidence", "rule_summary", "check_summary")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    _answer(item.get("answer"), _path(path, "answer"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    _string(item.get("rule_summary"), _path(path, "rule_summary"), errors, maximum=180)
    _string(item.get("check_summary"), _path(path, "check_summary"), errors, maximum=120)
    return errors


def _validate_critic_item(item: Any, path: str) -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "supported_candidates", "rejections", "alternative_answer", "confidence", "summary")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    supported = item.get("supported_candidates")
    if not isinstance(supported, list):
        errors.append(f"{_path(path, 'supported_candidates')}: expected array")
    else:
        if len(supported) > 2:
            errors.append(f"{_path(path, 'supported_candidates')}: at most two entries")
        if len(set(map(str, supported))) != len(supported):
            errors.append(f"{_path(path, 'supported_candidates')}: duplicate candidate ID")
        for index, candidate in enumerate(supported):
            _candidate_id(candidate, _path(_path(path, "supported_candidates"), index), errors)
    rejections = item.get("rejections")
    allowed_codes = {"prefix_mismatch", "arithmetic_error", "overfit", "weaker_rule", "unsupported_jump", "other"}
    if not isinstance(rejections, list):
        errors.append(f"{_path(path, 'rejections')}: expected array")
    else:
        if len(rejections) > 3:
            errors.append(f"{_path(path, 'rejections')}: at most three entries")
        seen: set[str] = set()
        for index, rejection in enumerate(rejections):
            rejection_path = _path(_path(path, "rejections"), index)
            _exact_keys(rejection, ("candidate_id", "issue_code", "issue"), rejection_path, errors)
            if not isinstance(rejection, dict):
                continue
            candidate = rejection.get("candidate_id")
            _candidate_id(candidate, _path(rejection_path, "candidate_id"), errors)
            if isinstance(candidate, str) and candidate in seen:
                errors.append(f"{rejection_path}.candidate_id: duplicate rejection")
            if isinstance(candidate, str):
                seen.add(candidate)
            if rejection.get("issue_code") not in allowed_codes:
                errors.append(f"{rejection_path}.issue_code: invalid code")
            _string(rejection.get("issue"), _path(rejection_path, "issue"), errors, maximum=140)
    alternative = item.get("alternative_answer")
    if alternative is not None:
        _answer(alternative, _path(path, "alternative_answer"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    _string(item.get("summary"), _path(path, "summary"), errors, maximum=180)
    return errors


def _validate_verifier_item(item: Any, path: str) -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "ranked_candidates", "recommended_answer", "confidence", "check_summary")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    ranked = item.get("ranked_candidates")
    if not isinstance(ranked, list):
        errors.append(f"{_path(path, 'ranked_candidates')}: expected array")
    else:
        if len(ranked) > 3:
            errors.append(f"{_path(path, 'ranked_candidates')}: at most three entries")
        seen: set[str] = set()
        for index, candidate in enumerate(ranked):
            candidate_path = _path(_path(path, "ranked_candidates"), index)
            keys2 = ("candidate_id", "answer", "prefix_fit", "score", "reason")
            _exact_keys(candidate, keys2, candidate_path, errors)
            if not isinstance(candidate, dict):
                continue
            candidate_id = candidate.get("candidate_id")
            _candidate_id(candidate_id, _path(candidate_path, "candidate_id"), errors)
            if isinstance(candidate_id, str) and candidate_id in seen:
                errors.append(f"{candidate_path}.candidate_id: duplicate ranked candidate")
            if isinstance(candidate_id, str):
                seen.add(candidate_id)
            _answer(candidate.get("answer"), _path(candidate_path, "answer"), errors)
            if candidate.get("prefix_fit") not in {"exact", "partial", "failed"}:
                errors.append(f"{candidate_path}.prefix_fit: invalid value")
            _integer_range(candidate.get("score"), _path(candidate_path, "score"), errors, 0, 100)
            _string(candidate.get("reason"), _path(candidate_path, "reason"), errors, maximum=140)
    _answer(item.get("recommended_answer"), _path(path, "recommended_answer"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    _string(item.get("check_summary"), _path(path, "check_summary"), errors, maximum=180)
    return errors


def _candidate_choice(value: Any, path: str, errors: list[str]) -> None:
    _exact_keys(value, ("candidate_id", "answer"), path, errors)
    if not isinstance(value, dict):
        return
    _candidate_id(value.get("candidate_id"), _path(path, "candidate_id"), errors)
    _answer(value.get("answer"), _path(path, "answer"), errors)


def _validate_synthesizer_item(item: Any, path: str) -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "champion", "runner_up", "confidence", "decision_basis")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    _candidate_choice(item.get("champion"), _path(path, "champion"), errors)
    _candidate_choice(item.get("runner_up"), _path(path, "runner_up"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    _string(item.get("decision_basis"), _path(path, "decision_basis"), errors, maximum=180)
    return errors


def _validate_red_team_item(item: Any, path: str) -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "attacks", "alternative_answer", "confidence", "summary")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    attacks = item.get("attacks")
    if not isinstance(attacks, list):
        errors.append(f"{_path(path, 'attacks')}: expected array")
    else:
        if len(attacks) != 2:
            errors.append(f"{_path(path, 'attacks')}: expected exactly two entries")
        seen: set[str] = set()
        for index, attack in enumerate(attacks):
            attack_path = _path(_path(path, "attacks"), index)
            _exact_keys(attack, ("synthesizer_id", "verdict", "issue"), attack_path, errors)
            if not isinstance(attack, dict):
                continue
            synthesizer_id = attack.get("synthesizer_id")
            if synthesizer_id not in {"SY1", "SY2"}:
                errors.append(f"{attack_path}.synthesizer_id: expected SY1 or SY2")
            if isinstance(synthesizer_id, str) and synthesizer_id in seen:
                errors.append(f"{attack_path}.synthesizer_id: duplicate synthesizer")
            if isinstance(synthesizer_id, str):
                seen.add(synthesizer_id)
            if attack.get("verdict") not in {"survives", "uncertain", "fails"}:
                errors.append(f"{attack_path}.verdict: invalid value")
            _string(attack.get("issue"), _path(attack_path, "issue"), errors, maximum=140)
    alternative = item.get("alternative_answer")
    if alternative is not None:
        _answer(alternative, _path(path, "alternative_answer"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    _string(item.get("summary"), _path(path, "summary"), errors, maximum=180)
    return errors


def _validate_judge_item(item: Any, path: str) -> list[str]:
    errors: list[str] = []
    keys = ("case_id", "answer", "confidence", "selected_candidate_id", "decision_basis")
    _exact_keys(item, keys, path, errors)
    if not isinstance(item, dict):
        return errors
    _string(item.get("case_id"), _path(path, "case_id"), errors, minimum=1, maximum=80)
    _answer(item.get("answer"), _path(path, "answer"), errors)
    _confidence(item.get("confidence"), _path(path, "confidence"), errors)
    selected = item.get("selected_candidate_id")
    if selected is not None:
        _candidate_id(selected, _path(path, "selected_candidate_id"), errors)
    _string(item.get("decision_basis"), _path(path, "decision_basis"), errors, maximum=180)
    return errors


ITEM_VALIDATORS: dict[str, Callable[[Any, str], list[str]]] = {
    "solver": validate_solver_item,
    "critic": _validate_critic_item,
    "breaker": _validate_critic_item,
    "verifier": _validate_verifier_item,
    "synthesizer": _validate_synthesizer_item,
    "red_team": _validate_red_team_item,
    "judge": _validate_judge_item,
}


def validate_result_item(item: Any, schema_name: str, path: str = "$") -> list[str]:
    """Validate one case-keyed result without requiring the other 11 cases."""

    if schema_name == "task" or schema_name not in ITEM_VALIDATORS:
        return [f"unknown result-item schema: {schema_name}"]
    return ITEM_VALIDATORS[schema_name](item, path)


def validate_task(document: Any) -> list[str]:
    errors: list[str] = []
    keys = ("schema_version", "experiment_id", "block_id", "cases")
    _exact_keys(document, keys, "$", errors)
    if not isinstance(document, dict):
        return errors
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version: expected {SCHEMA_VERSION!r}")
    if document.get("experiment_id") != "swarm-seeds-02":
        errors.append("$.experiment_id: expected 'swarm-seeds-02'")
    _string(document.get("block_id"), "$.block_id", errors, minimum=1, maximum=80)
    cases = document.get("cases")
    if not isinstance(cases, list):
        errors.append("$.cases: expected array")
        return errors
    if len(cases) != EXPECTED_CASE_COUNT:
        errors.append(f"$.cases: expected exactly {EXPECTED_CASE_COUNT} cases, got {len(cases)}")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        case_path = _path("$.cases", index)
        _exact_keys(case, ("case_id", "prefix"), case_path, errors)
        if not isinstance(case, dict):
            continue
        case_id = case.get("case_id")
        _string(case_id, _path(case_path, "case_id"), errors, minimum=1, maximum=80)
        if isinstance(case_id, str) and case_id in seen:
            errors.append(f"{case_path}.case_id: duplicate case ID")
        if isinstance(case_id, str):
            seen.add(case_id)
        prefix = case.get("prefix")
        if not isinstance(prefix, list) or not 12 <= len(prefix) <= 14:
            errors.append(f"{case_path}.prefix: expected 12 through 14 decimal strings")
        else:
            for term_index, term in enumerate(prefix):
                _decimal_string(term, _path(_path(case_path, "prefix"), term_index), errors)
    return errors


def validate_document(
    document: Any,
    schema_name: str,
    *,
    expected_case_ids: list[str] | None = None,
    expected_block_id: str | None = None,
) -> list[str]:
    if schema_name not in SCHEMA_NAMES:
        return [f"unknown schema: {schema_name}"]
    if schema_name == "task":
        return validate_task(document)
    errors: list[str] = []
    block_id, results = _base_document(document, errors)
    if expected_block_id is not None and block_id != expected_block_id:
        errors.append(f"$.block_id: expected {expected_block_id!r}")
    if results is None:
        return errors
    validator = ITEM_VALIDATORS[schema_name]
    observed_ids: list[str] = []
    for index, item in enumerate(results):
        path = _path("$.results", index)
        errors.extend(validator(item, path))
        if isinstance(item, dict) and isinstance(item.get("case_id"), str):
            observed_ids.append(item["case_id"])
    seen: set[str] = set()
    for case_id in observed_ids:
        if case_id in seen:
            errors.append(f"$.results: duplicate case_id {case_id!r}")
        seen.add(case_id)
    if expected_case_ids is not None:
        if len(expected_case_ids) != EXPECTED_CASE_COUNT or len(set(expected_case_ids)) != len(expected_case_ids):
            errors.append("expected case ID list must contain 12 unique IDs")
        missing = sorted(set(expected_case_ids) - set(observed_ids))
        extra = sorted(set(observed_ids) - set(expected_case_ids))
        if missing:
            errors.append(f"$.results: missing expected case IDs {missing}")
        if extra:
            errors.append(f"$.results: unexpected case IDs {extra}")
    return errors


def validate_raw_output(
    text: str,
    schema_name: str,
    *,
    expected_case_ids: list[str] | None = None,
    expected_block_id: str | None = None,
) -> dict[str, Any]:
    try:
        document, repairs = parse_json_strict(text)
    except StrictJSONError as exc:
        return {"valid": False, "repairs": [], "errors": [f"$: {exc}"], "document": None}
    errors = validate_document(
        document,
        schema_name,
        expected_case_ids=expected_case_ids,
        expected_block_id=expected_block_id,
    )
    return {"valid": not errors, "repairs": repairs, "errors": errors, "document": document}


INFRASTRUCTURE_STATUSES = {
    "infrastructure_failure",
    "timeout",
    "connection_error",
    "service_error",
    "provider_5xx",
    "worker_crash",
    "cancelled",
    "interrupted",
    "no_response",
}
SUCCESS_STATUSES = {"ok", "success", "completed", "semantic_response", "malformed_output"}


def classify_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    """Classify retryable infrastructure failure versus model failure."""

    transport_status = attempt.get("transport_status", attempt.get("status", "ok"))
    response = attempt.get("raw_text", attempt.get("response_text"))
    substantive_after_transport_error = False
    if transport_status not in SUCCESS_STATUSES:
        if isinstance(response, str) and response.strip():
            substantive_after_transport_error = True
        elif transport_status not in INFRASTRUCTURE_STATUSES:
            return {
                "classification": "record_error",
                "retry_allowed": False,
                "reason": f"unknown transport_status={transport_status}",
                "validation": None,
            }
        else:
            attempt_number = attempt.get("attempt_number", 1)
            retry_allowed = isinstance(attempt_number, int) and not isinstance(attempt_number, bool) and attempt_number < 3
            reason = f"transport_status={transport_status}"
            if not retry_allowed:
                reason += "; retry limit reached"
            return {"classification": "infrastructure_failure", "retry_allowed": retry_allowed, "reason": reason, "validation": None}
    raw_text = response
    if not isinstance(raw_text, str) or not raw_text.strip():
        attempt_number = attempt.get("attempt_number", 1)
        retry_allowed = isinstance(attempt_number, int) and not isinstance(attempt_number, bool) and attempt_number < 3
        reason = "successful transport returned no semantic output"
        if not retry_allowed:
            reason += "; retry limit reached"
        return {
            "classification": "infrastructure_failure",
            "retry_allowed": retry_allowed,
            "reason": reason,
            "validation": None,
        }
    schema_name = attempt.get("schema")
    if schema_name not in SCHEMA_NAMES:
        return {
            "classification": "record_error",
            "retry_allowed": False,
            "reason": "attempt record has unknown schema",
            "validation": None,
        }
    validation = validate_raw_output(
        raw_text,
        schema_name,
        expected_case_ids=attempt.get("expected_case_ids"),
        expected_block_id=attempt.get("expected_block_id"),
    )
    if validation["valid"]:
        reason = "schema valid"
        if substantive_after_transport_error:
            reason += f"; substantive response preserved despite transport_status={transport_status}"
        return {"classification": "valid", "retry_allowed": False, "reason": reason, "validation": validation}
    reason = "response arrived but violated JSON or output schema"
    if substantive_after_transport_error:
        reason += f" after transport_status={transport_status}"
    return {
        "classification": "model_failure",
        "retry_allowed": False,
        "reason": reason,
        "validation": validation,
    }


def _load_task_expectations(path: Path | None) -> tuple[list[str] | None, str | None]:
    if path is None:
        return None, None
    document, _ = parse_json_strict(path.read_text(encoding="utf-8"))
    errors = validate_task(document)
    if errors:
        raise StrictJSONError("invalid task block: " + "; ".join(errors))
    return [case["case_id"] for case in document["cases"]], document["block_id"]


def _self_test() -> dict[str, Any]:
    case_ids = [f"F{i:03d}" for i in range(1, 13)]
    task = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": "swarm-seeds-02",
        "block_id": "final-b01",
        "cases": [
            {"case_id": case_id, "prefix": [str(value) for value in range(12)]}
            for case_id in case_ids
        ],
    }
    assert not validate_task(task)
    result = {
        "schema_version": SCHEMA_VERSION,
        "block_id": "final-b01",
        "results": [
            {
                "case_id": case_id,
                "answer": ["0", "-1", "2", "999999999999999999999999999999", "4"],
                "confidence": 0.5,
                "rule_summary": "Compact exact rule.",
                "check_summary": "Full prefix checked.",
            }
            for case_id in case_ids
        ],
    }
    valid_text = json.dumps(result, separators=(",", ":"))
    valid = validate_raw_output(valid_text, "solver", expected_case_ids=case_ids, expected_block_id="final-b01")
    assert valid["valid"], valid

    wrong_count = json.loads(valid_text)
    wrong_count["results"][0]["answer"] = ["1", "2", "3"]
    assert not validate_raw_output(json.dumps(wrong_count), "solver", expected_case_ids=case_ids)["valid"]

    wrong_type = json.loads(valid_text)
    wrong_type["results"][0]["answer"][0] = 1
    assert not validate_raw_output(json.dumps(wrong_type), "solver", expected_case_ids=case_ids)["valid"]

    leading_zero = json.loads(valid_text)
    leading_zero["results"][0]["answer"][0] = "01"
    assert not validate_raw_output(json.dumps(leading_zero), "solver", expected_case_ids=case_ids)["valid"]

    negative_zero = json.loads(valid_text)
    negative_zero["results"][0]["answer"][0] = "-0"
    assert not validate_raw_output(json.dumps(negative_zero), "solver", expected_case_ids=case_ids)["valid"]

    duplicate = '{"schema_version":"2.0","schema_version":"2.0","block_id":"x","results":[]}'
    assert not validate_raw_output(duplicate, "solver")["valid"]
    assert not validate_raw_output('{"x":NaN}', "solver")["valid"]

    infra = classify_attempt({"transport_status": "timeout", "schema": "solver", "raw_text": "", "attempt_number": 1})
    assert infra["classification"] == "infrastructure_failure" and infra["retry_allowed"]
    exhausted = classify_attempt({"transport_status": "timeout", "schema": "solver", "raw_text": "", "attempt_number": 3})
    assert exhausted["classification"] == "infrastructure_failure" and not exhausted["retry_allowed"]
    empty_success = classify_attempt({"transport_status": "ok", "schema": "solver", "raw_text": "", "attempt_number": 1})
    assert empty_success["classification"] == "infrastructure_failure" and empty_success["retry_allowed"]
    empty_success_exhausted = classify_attempt(
        {"transport_status": "ok", "schema": "solver", "raw_text": "", "attempt_number": 3}
    )
    assert empty_success_exhausted["classification"] == "infrastructure_failure"
    assert not empty_success_exhausted["retry_allowed"]
    model = classify_attempt({"transport_status": "ok", "schema": "solver", "raw_text": "not json"})
    assert model["classification"] == "model_failure" and not model["retry_allowed"]
    accepted = classify_attempt(
        {
            "transport_status": "ok",
            "schema": "solver",
            "raw_text": valid_text,
            "expected_case_ids": case_ids,
            "expected_block_id": "final-b01",
        }
    )
    assert accepted["classification"] == "valid"

    red_team = {
        "schema_version": SCHEMA_VERSION,
        "block_id": "final-b01",
        "results": [
            {
                "case_id": case_id,
                "attacks": [
                    {"synthesizer_id": "SY1", "verdict": "survives", "issue": "No contradiction found."},
                    {"synthesizer_id": "SY2", "verdict": "uncertain", "issue": "One rule choice remains weak."},
                ],
                "alternative_answer": None,
                "confidence": 0.5,
                "summary": "SY1 survives the stronger check.",
            }
            for case_id in case_ids
        ],
    }
    assert not validate_document(red_team, "red_team", expected_case_ids=case_ids, expected_block_id="final-b01")
    wrong_synthesizer = json.loads(json.dumps(red_team))
    wrong_synthesizer["results"][0]["attacks"][0]["synthesizer_id"] = "SY01"
    assert validate_document(wrong_synthesizer, "red_team", expected_case_ids=case_ids)
    return {"ok": True, "tests": 16, "answer_terms": 5, "answer_encoding": "canonical_decimal_strings"}


def _write_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--self-test"]:
        _write_report(_self_test())
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate one raw model response")
    validate_parser.add_argument("schema", choices=SCHEMA_NAMES)
    validate_parser.add_argument("input", type=Path)
    validate_parser.add_argument("--task-block", type=Path)

    classify_parser = subparsers.add_parser("classify", help="classify one attempt record")
    classify_parser.add_argument("input", type=Path)

    subparsers.add_parser("self-test", help="run deterministic built-in tests")
    args = parser.parse_args(argv)

    if args.command == "self-test":
        _write_report(_self_test())
        return 0
    if args.command == "classify":
        attempt, _ = parse_json_strict(args.input.read_text(encoding="utf-8"))
        if not isinstance(attempt, dict):
            raise StrictJSONError("attempt record must be an object")
        _write_report(classify_attempt(attempt))
        return 0

    expected_case_ids, expected_block_id = _load_task_expectations(args.task_block)
    report = validate_raw_output(
        args.input.read_text(encoding="utf-8"),
        args.schema,
        expected_case_ids=expected_case_ids,
        expected_block_id=expected_block_id,
    )
    printable = {key: value for key, value in report.items() if key != "document"}
    printable["schema"] = args.schema
    _write_report(printable)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, StrictJSONError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2)
