#!/usr/bin/env python3
"""Append-only attempt lineages for Experiment 02.

Only an infrastructure failure with no substantive model response is retryable.
A semantic response (valid or malformed) closes the planned call immediately.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "2.0"
ATTEMPT_STATUSES = {"semantic_response", "malformed_output", "infrastructure_failure"}
TERMINAL_STATUSES = {"semantic_response", "malformed_output"}
MAX_ATTEMPTS = 3
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AttemptLogError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_line(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AttemptLogError(f"invalid JSON on {path}:{line_number}: {exc}") from exc
            if not isinstance(event, dict):
                raise AttemptLogError(f"event on {path}:{line_number} is not an object")
            event["_line_number"] = line_number
            events.append(event)
    return events


def _lineages(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        call_id = event.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise AttemptLogError(f"event at line {event.get('_line_number', '?')} has no call_id")
        result.setdefault(call_id, []).append(event)
    return result


def lineage_state(events: list[dict[str, Any]], call_id: str) -> dict[str, Any]:
    lineage = _lineages(events).get(call_id, [])
    attempts = [event for event in lineage if event.get("event_type") == "attempt"]
    closes = [event for event in lineage if event.get("event_type") == "call_closed"]
    terminal = next((event for event in attempts if event.get("status") in TERMINAL_STATUSES), None)
    if terminal:
        return {"state": "closed", "outcome": terminal["status"], "attempt_count": len(attempts),
                "selected_attempt": terminal.get("attempt_number"), "terminal_event": terminal}
    if len(attempts) >= MAX_ATTEMPTS:
        return {"state": "closed", "outcome": "infrastructure_exhausted", "attempt_count": len(attempts),
                "selected_attempt": None, "terminal_event": attempts[-1]}
    if closes:
        return {"state": "closed", "outcome": closes[0].get("outcome"), "attempt_count": len(attempts),
                "selected_attempt": closes[0].get("selected_attempt"), "terminal_event": closes[0]}
    return {"state": "open", "outcome": None, "attempt_count": len(attempts),
            "next_attempt": len(attempts) + 1}


def validate_events(events: list[dict[str, Any]], allowed_call_ids: set[str] | None = None) -> None:
    for call_id, lineage in _lineages(events).items():
        if allowed_call_ids is not None and call_id not in allowed_call_ids:
            raise AttemptLogError(f"attempt log contains unknown call_id {call_id}")
        attempts: list[dict[str, Any]] = []
        closes: list[dict[str, Any]] = []
        terminal_seen = False
        request_hash: str | None = None
        for event in lineage:
            event_type = event.get("event_type")
            if event.get("schema_version") != SCHEMA_VERSION:
                raise AttemptLogError(f"unsupported event schema for {call_id}")
            if event_type == "attempt":
                if closes or terminal_seen:
                    raise AttemptLogError(f"attempt appended after {call_id} was terminal")
                attempts.append(event)
                if event.get("attempt_number") != len(attempts) or len(attempts) > MAX_ATTEMPTS:
                    raise AttemptLogError(f"non-contiguous or excessive attempt number for {call_id}")
                status = event.get("status")
                if status not in ATTEMPT_STATUSES:
                    raise AttemptLogError(f"invalid attempt status for {call_id}: {status!r}")
                current_hash = event.get("request_sha256")
                if not isinstance(current_hash, str) or not _SHA256.fullmatch(current_hash):
                    raise AttemptLogError(f"invalid request_sha256 for {call_id}")
                if request_hash is None:
                    request_hash = current_hash
                elif current_hash != request_hash:
                    raise AttemptLogError(f"retry changed the frozen request for {call_id}")
                if status == "infrastructure_failure":
                    if event.get("response_text") is not None or event.get("response_sha256") is not None:
                        raise AttemptLogError(f"infrastructure failure for {call_id} contains a model response")
                    if not event.get("error"):
                        raise AttemptLogError(f"infrastructure failure for {call_id} must record an error")
                else:
                    response = event.get("response_text")
                    if not isinstance(response, str):
                        raise AttemptLogError(f"terminal model attempt for {call_id} must preserve response_text")
                    if event.get("response_sha256") != sha256_bytes(response.encode("utf-8")):
                        raise AttemptLogError(f"response hash mismatch for {call_id}")
                    terminal_seen = True
                for hash_field in (
                    "raw_events_sha256", "stderr_sha256", "last_message_sha256",
                ):
                    value = event.get(hash_field)
                    if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
                        raise AttemptLogError(f"invalid {hash_field} for {call_id}")
                for size_field in ("raw_events_bytes", "stderr_bytes", "last_message_bytes"):
                    value = event.get(size_field)
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                    ):
                        raise AttemptLogError(f"invalid {size_field} for {call_id}")
                artifact = event.get("artifact_relpath")
                if artifact is not None and (
                    not isinstance(artifact, str)
                    or not artifact
                    or artifact.startswith("/")
                    or ".." in Path(artifact).parts
                ):
                    raise AttemptLogError(f"unsafe artifact_relpath for {call_id}")
            elif event_type == "call_closed":
                closes.append(event)
                if len(closes) > 1:
                    raise AttemptLogError(f"multiple close markers for {call_id}")
                expected = (attempts[-1].get("status") if attempts and attempts[-1].get("status") in TERMINAL_STATUSES
                            else "infrastructure_exhausted" if len(attempts) == MAX_ATTEMPTS else None)
                if event.get("outcome") != expected:
                    raise AttemptLogError(f"premature or mismatched close marker for {call_id}")
                selected = attempts[-1]["attempt_number"] if expected in TERMINAL_STATUSES else None
                if event.get("selected_attempt") != selected:
                    raise AttemptLogError(f"invalid selected_attempt for {call_id}")
            else:
                raise AttemptLogError(f"unknown event_type for {call_id}: {event_type!r}")


def _usage(value: dict[str, Any] | None) -> dict[str, int] | None:
    if value is None:
        return None
    allowed = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"}
    result: dict[str, int] = {}
    for key, number in value.items():
        if key not in allowed or isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise AttemptLogError(f"invalid provider usage field {key}={number!r}")
        result[key] = number
    return result


def _cost(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = decimal.Decimal(value)
    except decimal.InvalidOperation as exc:
        raise AttemptLogError("provider_cost_usd must be a non-negative decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise AttemptLogError("provider_cost_usd must be a non-negative decimal string")
    return value


def record_attempt(path: Path, *, call_id: str, status: str, request_sha256: str,
                   prompt_identity_sha256: str, response_text: str | None = None,
                   error: str | None = None, recorded_at: str | None = None,
                   latency_ms: int | None = None, provider_request_id: str | None = None,
                   provider_model: str | None = None, provider_usage: dict[str, Any] | None = None,
                   provider_cost_usd: str | None = None, exit_code: int | None = None,
                   timed_out: bool = False, reasoning_effort: str | None = None,
                   requested_model: str | None = None, cli_version: str | None = None,
                   session_resumed: bool = False, execution_batch: int | None = None,
                   jsonl_integrity: bool | None = None,
                   agent_message_present: bool | None = None,
                   process_started: bool | None = None, start_failure: bool = False,
                   runner_process_crash: bool = False, system_crash: bool = False,
                   os_kill_resource_exhaustion: bool = False,
                   resource_warning: str | None = None,
                   prompt_characters: int | None = None,
                   stdout_event_count: int | None = None,
                   jsonl_parse_failures: int | None = None,
                   raw_events_sha256: str | None = None,
                   raw_events_bytes: int | None = None,
                   stderr_sha256: str | None = None,
                   stderr_bytes: int | None = None,
                   last_message_sha256: str | None = None,
                   last_message_bytes: int | None = None,
                   artifact_relpath: str | None = None,
                   protocol_violation: bool = False) -> list[dict[str, Any]]:
    """Atomically append one attempt and, when terminal, its close marker."""
    if status not in ATTEMPT_STATUSES:
        raise AttemptLogError(f"invalid status {status!r}")
    if not _SHA256.fullmatch(request_sha256) or not _SHA256.fullmatch(prompt_identity_sha256):
        raise AttemptLogError("request and prompt identity hashes must be lowercase SHA-256 values")
    if latency_ms is not None and (isinstance(latency_ms, bool) or latency_ms < 0):
        raise AttemptLogError("latency_ms must be a non-negative integer")
    for field, value in (
        ("raw_events_sha256", raw_events_sha256),
        ("stderr_sha256", stderr_sha256),
        ("last_message_sha256", last_message_sha256),
    ):
        if value is not None and not _SHA256.fullmatch(value):
            raise AttemptLogError(f"{field} must be a lowercase SHA-256 value")
    for field, value in (
        ("raw_events_bytes", raw_events_bytes),
        ("stderr_bytes", stderr_bytes),
        ("last_message_bytes", last_message_bytes),
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise AttemptLogError(f"{field} must be a non-negative integer")
    if artifact_relpath is not None and (
        not artifact_relpath or artifact_relpath.startswith("/") or ".." in Path(artifact_relpath).parts
    ):
        raise AttemptLogError("artifact_relpath must be a safe relative path")
    usage = _usage(provider_usage)
    cost = _cost(provider_cost_usd)
    if status == "infrastructure_failure":
        if response_text is not None:
            raise AttemptLogError("never classify a substantive response as infrastructure failure")
        if not error:
            raise AttemptLogError("infrastructure failure must preserve an error")
    elif response_text is None:
        raise AttemptLogError("completed model output must preserve response_text, even when malformed")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        events = []
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                event = json.loads(line)
                event["_line_number"] = line_number
                events.append(event)
        validate_events(events)
        state = lineage_state(events, call_id)
        if state["state"] == "closed":
            raise AttemptLogError(f"call {call_id} is already closed ({state['outcome']})")
        prior = [event for event in events if event.get("call_id") == call_id and event.get("event_type") == "attempt"]
        if prior and prior[-1].get("status") != "infrastructure_failure":
            raise AttemptLogError(f"call {call_id} is not retryable")
        if prior and prior[0].get("request_sha256") != request_sha256:
            raise AttemptLogError(f"retry request hash changed for {call_id}")

        number = len(prior) + 1
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION, "event_type": "attempt", "call_id": call_id,
            "attempt_number": number, "recorded_at": recorded_at or utc_now(),
            "request_sha256": request_sha256, "prompt_identity_sha256": prompt_identity_sha256,
            "status": status, "timed_out": bool(timed_out),
        }
        optional = {"error": error, "latency_ms": latency_ms, "provider_request_id": provider_request_id,
                    "provider_model": provider_model, "provider_usage": usage,
                    "provider_cost_usd": cost, "exit_code": exit_code,
                    "reasoning_effort": reasoning_effort, "requested_model": requested_model,
                    "cli_version": cli_version, "session_resumed": bool(session_resumed),
                    "execution_batch": execution_batch, "jsonl_integrity": jsonl_integrity,
                    "agent_message_present": agent_message_present,
                    "process_started": process_started, "start_failure": bool(start_failure),
                    "runner_process_crash": bool(runner_process_crash),
                    "system_crash": bool(system_crash),
                    "os_kill_resource_exhaustion": bool(os_kill_resource_exhaustion),
                    "resource_warning": resource_warning,
                    "prompt_characters": prompt_characters,
                    "stdout_event_count": stdout_event_count,
                    "jsonl_parse_failures": jsonl_parse_failures,
                    "raw_events_sha256": raw_events_sha256,
                    "raw_events_bytes": raw_events_bytes,
                    "stderr_sha256": stderr_sha256,
                    "stderr_bytes": stderr_bytes,
                    "last_message_sha256": last_message_sha256,
                    "last_message_bytes": last_message_bytes,
                    "artifact_relpath": artifact_relpath,
                    "protocol_violation": bool(protocol_violation)}
        event.update({key: value for key, value in optional.items() if value is not None})
        if response_text is not None:
            event["response_text"] = response_text
            event["response_sha256"] = sha256_bytes(response_text.encode("utf-8"))
        additions = [event]
        outcome = status if status in TERMINAL_STATUSES else ("infrastructure_exhausted" if number == MAX_ATTEMPTS else None)
        if outcome:
            close: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION, "event_type": "call_closed", "call_id": call_id,
                "closed_at": event["recorded_at"], "outcome": outcome,
                "selected_attempt": number if status in TERMINAL_STATUSES else None,
            }
            if response_text is not None:
                close["selected_response_sha256"] = event["response_sha256"]
            additions.append(close)
        handle.seek(0, os.SEEK_END)
        handle.write("".join(canonical_line(item) + "\n" for item in additions))
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return additions


def manifest_call_map(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    calls = data.get("calls", [])
    return {call["call_id"]: call for call in calls}


def _read_payload(path: str | None) -> bytes | None:
    if path is None:
        return None
    if path == "-":
        return sys.stdin.buffer.read()
    return Path(path).read_bytes()


def _self_test() -> None:
    frozen = "a" * 64
    request = sha256_bytes(b"identical request")
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "attempts.jsonl"
        record_attempt(log, call_id="c1", status="infrastructure_failure", request_sha256=request,
                       prompt_identity_sha256=frozen, error="timeout", recorded_at="2026-01-01T00:00:00Z")
        record_attempt(log, call_id="c1", status="semantic_response", request_sha256=request,
                       prompt_identity_sha256=frozen, response_text='{"ok":true}',
                       recorded_at="2026-01-01T00:00:01Z")
        events = load_events(log)
        validate_events(events)
        assert lineage_state(events, "c1")["selected_attempt"] == 2
        try:
            record_attempt(log, call_id="c1", status="infrastructure_failure", request_sha256=request,
                           prompt_identity_sha256=frozen, error="late")
        except AttemptLogError:
            pass
        else:
            raise AssertionError("retry after first semantic response was accepted")
        for number in range(3):
            record_attempt(log, call_id="c2", status="infrastructure_failure", request_sha256=request,
                           prompt_identity_sha256=frozen, error=f"failure {number}")
        assert lineage_state(load_events(log), "c2")["outcome"] == "infrastructure_exhausted"
        record_attempt(log, call_id="c3", status="malformed_output", request_sha256=request,
                       prompt_identity_sha256=frozen, response_text="not json")
        assert lineage_state(load_events(log), "c3")["outcome"] == "malformed_output"
    print("attempt_log.py self-test: PASS")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and audit append-only Experiment 02 attempt lineages.")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    record = sub.add_parser("record", help="append an attempt; attempt number is assigned under a file lock")
    record.add_argument("--log", type=Path, required=True)
    record.add_argument("--manifest", type=Path, required=True)
    record.add_argument("--call-id", required=True)
    record.add_argument("--status", choices=sorted(ATTEMPT_STATUSES), required=True)
    request_group = record.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request-file", help="hash this exact request; '-' reads stdin")
    request_group.add_argument("--request-sha256")
    record.add_argument("--response-file", help="preserve completed output; '-' reads stdin")
    record.add_argument("--error")
    record.add_argument("--latency-ms", type=int)
    record.add_argument("--provider-request-id")
    record.add_argument("--provider-model")
    record.add_argument("--provider-cost-usd")
    record.add_argument("--exit-code", type=int)
    record.add_argument("--timed-out", action="store_true")
    check = sub.add_parser("verify", help="validate all lineages and optionally require all 400 closed")
    check.add_argument("--log", type=Path, required=True)
    check.add_argument("--manifest", type=Path)
    check.add_argument("--require-complete", action="store_true")
    status = sub.add_parser("status", help="print operational counts only (never correctness)")
    status.add_argument("--log", type=Path, required=True)
    status.add_argument("--manifest", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.command == "record":
            calls = manifest_call_map(args.manifest)
            if args.call_id not in calls:
                raise AttemptLogError(f"unknown call_id {args.call_id}")
            request_data = _read_payload(args.request_file)
            request_hash = sha256_bytes(request_data) if request_data is not None else args.request_sha256
            response_data = _read_payload(args.response_file)
            response = response_data.decode("utf-8", errors="replace") if response_data is not None else None
            additions = record_attempt(args.log, call_id=args.call_id, status=args.status,
                                       request_sha256=request_hash,
                                       prompt_identity_sha256=calls[args.call_id]["prompt_identity_sha256"],
                                       response_text=response, error=args.error, latency_ms=args.latency_ms,
                                       provider_request_id=args.provider_request_id,
                                       provider_model=args.provider_model,
                                       provider_cost_usd=args.provider_cost_usd, exit_code=args.exit_code,
                                       timed_out=args.timed_out)
            print(canonical_line(additions[-1]))
            return 0
        if args.command in {"verify", "status"}:
            events = load_events(args.log)
            calls = manifest_call_map(args.manifest) if args.manifest else None
            validate_events(events, set(calls) if calls else None)
            ids = set(calls) if calls else set(_lineages(events))
            states = [lineage_state(events, call_id) for call_id in ids]
            summary = {"planned": len(ids), "closed": sum(s["state"] == "closed" for s in states),
                       "open": sum(s["state"] == "open" and s["attempt_count"] > 0 for s in states),
                       "not_started": sum(s["attempt_count"] == 0 for s in states),
                       "infrastructure_exhausted": sum(s.get("outcome") == "infrastructure_exhausted" for s in states)}
            if args.command == "verify" and args.require_complete and summary["closed"] != summary["planned"]:
                raise AttemptLogError(f"collection incomplete: {summary}")
            print(json.dumps(summary, sort_keys=True))
            return 0
        parser.print_help()
        return 2
    except (AttemptLogError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
