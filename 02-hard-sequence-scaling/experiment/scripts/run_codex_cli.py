#!/usr/bin/env python3
"""Execute frozen Experiment 02 calls through isolated Codex CLI processes.

The runner uses only the Python standard library. It renders frozen prompts,
builds anonymous packets, enforces the dependency graph, limits active
processes, records append-only retry lineages, and closes final collection only
after every planned call has one substantive terminal response.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from attempt_log import (
    MAX_ATTEMPTS,
    AttemptLogError,
    lineage_state,
    load_events,
    record_attempt,
    validate_events,
)
from build_packets import (
    anonymize_bundle,
    anonymize_report_bundle,
    cluster_anonymous_packet,
    extract_stage_schema,
    preflight_and_compact,
)
from run_manifest import validate_manifest
from validate_outputs import validate_raw_output, validate_task


SCHEMA_VERSION = "runner-v1"
MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT_SECONDS = 300
MAX_CONCURRENCY = 20
PACKET_LIMIT = 60_000
DISABLED_FEATURES = (
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
)
ROLE_KEYS = {
    ("swarm10", "proposer"): "proposers",
    ("swarm10", "critic"): "critics",
    ("swarm10", "verifier"): "verifiers",
    ("swarm10", "judge"): "judge",
    ("tournament20", "explorer"): "explorers",
    ("tournament20", "breaker"): "breakers",
    ("tournament20", "verifier"): "verifiers",
    ("tournament20", "synthesizer"): "synthesizers",
    ("tournament20", "red_team"): "red_team",
    ("tournament20", "judge"): "final_judge",
}
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
HOME_RE = re.compile(r"/(?:Users|home)/[^/\s]+")
TOOL_EVENT_MARKERS = (
    "tool_call",
    "function_call",
    "mcp_tool_call",
    "command_execution",
    "computer_action",
    "browser_action",
)


class RunnerError(RuntimeError):
    """Raised when collection cannot safely continue."""


class ActiveCounter:
    def __init__(self, prior_maximum: int = 0) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum = max(0, int(prior_maximum))

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self) -> None:
        with self._lock:
            self.active -= 1


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sanitize_string(value: str) -> str:
    value = HOME_RE.sub("<HOME>", value)
    return UUID_RE.sub("<ID>", value)


def sanitize_event(value: Any, key: str | None = None) -> Any:
    """Remove internal session identifiers while preserving model text exactly."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child in value.items():
            normalized = str(child_key).lower()
            if normalized in {"thread_id", "session_id", "task_id", "conversation_id"}:
                continue
            if normalized == "id" and isinstance(child, str) and UUID_RE.fullmatch(child):
                result[child_key] = "<ID>"
            else:
                result[child_key] = sanitize_event(child, normalized)
        return result
    if isinstance(value, list):
        return [sanitize_event(child, key) for child in value]
    if isinstance(value, str) and key not in {"text", "message", "content"}:
        return _sanitize_string(value)
    return value


def parse_codex_jsonl(stdout: str) -> tuple[list[dict[str, Any]], int, bool]:
    events: list[dict[str, Any]] = []
    failures = 0
    tool_event = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            failures += 1
            continue
        if not isinstance(event, dict):
            failures += 1
            continue
        event_type = str(event.get("type", event.get("event_type", ""))).lower()
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = str(item.get("type", "")).lower()
        if any(marker in event_type or marker in item_type for marker in TOOL_EVENT_MARKERS):
            tool_event = True
        events.append(event)
    return events, failures, tool_event


def final_agent_message(events: list[dict[str, Any]], last_message_path: Path) -> str | None:
    if last_message_path.is_file():
        text = last_message_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text.strip()
    messages: list[str] = []
    for event in events:
        event_type = str(event.get("type", event.get("event_type", ""))).lower()
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = str(item.get("type", "")).lower()
        if event_type in {"item.completed", "item_completed"} and item_type == "agent_message":
            text = item.get("text", item.get("content"))
            if isinstance(text, str) and text.strip():
                messages.append(text.strip())
    return messages[-1] if messages else None


def provider_usage(events: list[dict[str, Any]]) -> dict[str, int] | None:
    observed: dict[str, int] | None = None
    for event in events:
        usage = event.get("usage")
        if not isinstance(usage, dict) and isinstance(event.get("turn"), dict):
            usage = event["turn"].get("usage")
        if not isinstance(usage, dict):
            continue
        normalized: dict[str, int] = {}
        aliases = {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "cached_input_tokens": ("cached_input_tokens",),
            "output_tokens": ("output_tokens", "completion_tokens"),
            "reasoning_tokens": ("reasoning_tokens", "reasoning_output_tokens"),
            "total_tokens": ("total_tokens",),
        }
        for target, candidates in aliases.items():
            for candidate in candidates:
                value = usage.get(candidate)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    normalized[target] = value
                    break
        if "total_tokens" not in normalized and normalized:
            normalized["total_tokens"] = normalized.get("input_tokens", 0) + normalized.get("output_tokens", 0)
        if normalized:
            observed = normalized
    return observed


def provider_model(events: list[dict[str, Any]]) -> str | None:
    """Return explicit provider telemetry when the JSONL stream exposes it."""
    observed: str | None = None
    for event in events:
        candidates: list[Any] = [
            event.get("model"), event.get("model_id"), event.get("model_name"),
        ]
        turn = event.get("turn")
        if isinstance(turn, dict):
            candidates.extend((turn.get("model"), turn.get("model_id"), turn.get("model_name")))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                observed = candidate.strip()
    return observed


class RunDirectoryLock:
    """Prevent two runner processes from launching the same call lineage."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / ".runner.lock"
        self.handle: Any = None

    def __enter__(self) -> "RunDirectoryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            self.handle = None
            raise RunnerError(f"another runner already owns {self.path.parent}") from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(json.dumps({"pid": os.getpid(), "acquired_at": utc_now()}) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def load_tasks(path: Path) -> dict[str, dict[str, Any]]:
    value = load_json(path)
    if isinstance(value, dict) and "final_blocks" in value:
        blocks = value["final_blocks"]
    elif isinstance(value, dict) and "block_id" in value:
        blocks = [value]
    elif isinstance(value, list):
        blocks = value
    else:
        raise RunnerError("unsupported public task-block file")
    result: dict[str, dict[str, Any]] = {}
    for block in blocks:
        errors = validate_task(block)
        if errors:
            raise RunnerError("invalid public task block: " + "; ".join(errors))
        block_id = block["block_id"]
        if block_id in result:
            raise RunnerError(f"duplicate task block {block_id}")
        result[block_id] = block
    return result


def read_cli_version(binary: Path) -> str:
    completed = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=False, timeout=30
    )
    if completed.returncode != 0:
        raise RunnerError(f"unable to read Codex CLI version: {_sanitize_string(completed.stderr.strip())}")
    return completed.stdout.strip()


def build_command(
    binary: Path,
    effort: str,
    schema_path: Path,
    empty_workspace: Path,
    last_message_path: Path,
) -> list[str]:
    command = [
        str(binary),
        "exec",
        "--model",
        MODEL,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
    ]
    for feature in DISABLED_FEATURES:
        command.extend(("--disable", feature))
    command.extend(
        (
            "--json",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message_path),
            "-C",
            str(empty_workspace),
            "-",
        )
    )
    return command


def public_command(command: list[str]) -> list[str]:
    output = []
    replace_next: str | None = None
    for token in command:
        if replace_next is not None:
            output.append(replace_next)
            replace_next = None
        elif token == "--output-schema":
            output.append(token)
            replace_next = "<OUTPUT_SCHEMA>"
        elif token == "--output-last-message":
            output.append(token)
            replace_next = "<LAST_MESSAGE>"
        elif token == "-C":
            output.append(token)
            replace_next = "<FRESH_EMPTY_WORKSPACE>"
        elif token == command[0]:
            output.append("<FROZEN_CODEX_BINARY>")
        else:
            output.append(token)
    return output


def group_calls(manifest: dict[str, Any], call: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in manifest["calls"]
        if candidate["block_id"] == call["block_id"]
        and candidate["condition_label"] == call["condition_label"]
        and candidate["architecture"] == call["architecture"]
    ]


def terminal_worker(call: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [
        event
        for event in events
        if event.get("event_type") == "attempt" and event.get("call_id") == call["call_id"]
    ]
    attempts.sort(key=lambda event: int(event.get("attempt_number", 0)))
    substantive = [event for event in attempts if event.get("status") in {"semantic_response", "malformed_output"}]
    if substantive:
        return {
            "slot_id": call["slot_id"],
            "transport_status": "ok",
            "raw_text": substantive[0]["response_text"],
        }
    return {"slot_id": call["slot_id"], "transport_status": "infrastructure_failure", "raw_text": None}


def bundle_for_role(
    manifest: dict[str, Any],
    call: dict[str, Any],
    role: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    calls = sorted(
        (candidate for candidate in group_calls(manifest, call) if candidate["role"] == role),
        key=lambda candidate: candidate["role_index"],
    )
    return {
        "packet_version": "2.0",
        "block_id": call["block_id"],
        "case_ids": list(call["case_ids"]),
        "workers": [terminal_worker(candidate, events) for candidate in calls],
    }


def packet_seed(manifest: dict[str, Any], call: dict[str, Any], label: str) -> str:
    return "|".join(
        (
            str(manifest["schedule_seed"]),
            call["block_id"],
            call["condition_label"],
            call["architecture"],
            label,
        )
    )


def build_context(
    manifest: dict[str, Any],
    call: dict[str, Any],
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    architecture = call["architecture"]
    role = call["role"]
    context: dict[str, Any] = {}
    if architecture == "independent" or role in {"proposer", "explorer"}:
        return context, {"before_characters": 0, "after_characters": 0, "compacted": False}

    source_role = "proposer" if architecture == "swarm10" else "explorer"
    expected_source = 5 if architecture == "swarm10" else 8
    anonymous = anonymize_bundle(
        bundle_for_role(manifest, call, source_role, events),
        packet_seed(manifest, call, "candidates"),
        expected_workers=expected_source,
    )
    clusters = cluster_anonymous_packet(anonymous, packet_seed(manifest, call, "clusters"))

    if role in {"critic", "breaker"}:
        context["ANONYMOUS_CANDIDATE_PACKET_JSON"] = anonymous
    else:
        report_role = "critic" if architecture == "swarm10" else "breaker"
        report_schema = report_role
        expected_reports = 2 if architecture == "swarm10" else 4
        reports = anonymize_report_bundle(
            bundle_for_role(manifest, call, report_role, events),
            packet_seed(manifest, call, f"{report_role}-reports"),
            report_schema,
            expected_workers=expected_reports,
        )
        if role == "verifier":
            context["CLUSTER_PACKET_JSON"] = clusters
            key = "CRITIC_PACKET_JSON" if architecture == "swarm10" else "BREAKER_PACKET_JSON"
            context[key] = reports
        else:
            verifier_reports = anonymize_report_bundle(
                bundle_for_role(manifest, call, "verifier", events),
                packet_seed(manifest, call, "verifier-reports"),
                "verifier",
                expected_workers=2 if architecture == "swarm10" else 4,
            )
            if architecture == "swarm10":
                context["CLUSTER_PACKET_JSON"] = clusters
                context["CRITIC_PACKET_JSON"] = reports
                context["VERIFIER_PACKET_JSON"] = verifier_reports
            else:
                ledger = {
                    "packet_version": "2.0",
                    "block_id": call["block_id"],
                    "candidate_clusters": clusters["cases"],
                    "breaker_reports": reports["cases"],
                    "verifier_reports": verifier_reports["cases"],
                }
                if role == "synthesizer":
                    context["EVIDENCE_LEDGER_JSON"] = ledger
                else:
                    synthesizer_reports = anonymize_report_bundle(
                        bundle_for_role(manifest, call, "synthesizer", events),
                        packet_seed(manifest, call, "synthesizer-reports"),
                        "synthesizer",
                        expected_workers=2,
                    )
                    if role == "red_team":
                        context["SYNTHESIZER_PACKET_JSON"] = {
                            "packet_version": "2.0",
                            "block_id": call["block_id"],
                            "synthesizer_reports": synthesizer_reports["cases"],
                            "evidence_ledger": ledger,
                        }
                    else:
                        red_team_reports = anonymize_report_bundle(
                            bundle_for_role(manifest, call, "red_team", events),
                            packet_seed(manifest, call, "red-team-reports"),
                            "red_team",
                            expected_workers=1,
                        )
                        context["SYNTHESIZER_PACKET_JSON"] = synthesizer_reports
                        context["RED_TEAM_PACKET_JSON"] = red_team_reports
                        context["EVIDENCE_LEDGER_JSON"] = ledger

    compacted, report = preflight_and_compact(context, PACKET_LIMIT)
    return compacted, report


def role_specialty(catalog: dict[str, Any], call: dict[str, Any]) -> str:
    if call["architecture"] == "independent":
        return ""
    key = ROLE_KEYS[(call["architecture"], call["role"])]
    records = catalog[call["architecture"]][key]
    index = int(call["role_index"]) - 1
    if index < 0 or index >= len(records):
        raise RunnerError(f"role catalog index is invalid for {call['call_id']}")
    return str(records[index].get("specialty_prompt", ""))


def render_prompt(
    experiment_root: Path,
    manifest: dict[str, Any],
    call: dict[str, Any],
    task: dict[str, Any],
    events: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    prompts = experiment_root / "prompts"
    common = (prompts / "COMMON_PREFIX.txt").read_text(encoding="utf-8").strip()
    identity = manifest["prompt_identities"][call["prompt_identity_id"]]
    template = (experiment_root / identity["template"]).read_text(encoding="utf-8")
    catalog = load_json(prompts / "ROLE_CATALOG.json")
    context, compact_report = build_context(manifest, call, events)
    replacements: dict[str, str] = {
        "COMMON_PREFIX": common,
        "TASK_BLOCK_JSON": json.dumps(task, separators=(",", ":"), ensure_ascii=False),
        "SPECIALTY_PROMPT": role_specialty(catalog, call),
    }
    replacements.update(
        {
            key: json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            for key, value in context.items()
        }
    )
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)))
    if leftovers:
        raise RunnerError(f"unresolved prompt placeholders for {call['call_id']}: {leftovers}")
    return rendered.strip() + "\n", compact_report


def write_schema_files(experiment_root: Path, run_dir: Path) -> dict[str, Path]:
    catalog = load_json(experiment_root / "prompts" / "SCHEMAS.json")
    paths: dict[str, Path] = {}
    for stage in ("solver", "critic", "breaker", "verifier", "synthesizer", "red_team", "judge"):
        path = run_dir / "schemas" / f"{stage}.json"
        atomic_write_json(path, extract_stage_schema(catalog, stage))
        paths[stage] = path
    return paths


def request_identity(
    prompt: str,
    call: dict[str, Any],
    schema_path: Path,
    binary: Path,
    timeout_seconds: int,
) -> str:
    identity = {
        "model": MODEL,
        "reasoning_effort": call["reasoning_effort"],
        "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        "schema_sha256": sha256_file(schema_path),
        "codex_binary_sha256": sha256_file(binary),
        "timeout_seconds": timeout_seconds,
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
        "disabled_features": list(DISABLED_FEATURES),
    }
    return sha256_bytes(canonical_bytes(identity))


def _resource_warning() -> str | None:
    try:
        load_one = os.getloadavg()[0]
        cpu = os.cpu_count() or 1
    except (AttributeError, OSError):
        return None
    if load_one > cpu * 4:
        return f"one-minute load average {load_one:.2f} exceeds four times logical CPU count {cpu}"
    return None


def invoke_codex(
    *,
    binary: Path,
    call: dict[str, Any],
    prompt: str,
    schema_path: Path,
    attempt_dir: Path,
    timeout_seconds: int,
    active_counter: ActiveCounter,
) -> dict[str, Any]:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    workspace_parent = attempt_dir / "empty"
    workspace_parent.mkdir(exist_ok=True)
    empty_workspace = Path(tempfile.mkdtemp(prefix="workspace-", dir=workspace_parent))
    last_message_path = attempt_dir / "last_message.txt"
    command = build_command(binary, call["reasoning_effort"], schema_path, empty_workspace, last_message_path)
    atomic_write_json(attempt_dir / "command.json", {"argv": public_command(command), "stdin": "prompt.txt"})
    atomic_write_text(attempt_dir / "prompt.txt", prompt)
    atomic_write_json(
        attempt_dir / "claim.json",
        {
            "call_id": call["call_id"],
            "claimed_at": utc_now(),
            "request_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        },
    )
    started = time.monotonic()
    process_started = False
    timed_out = False
    start_failure = False
    stdout_bytes = b""
    stderr_bytes = b""
    exit_code: int | None = None
    active_counter.enter()
    try:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            process_started = True
            atomic_write_json(
                attempt_dir / "process.json",
                {"pid": process.pid, "started_at": utc_now(), "process_started": True},
            )
        except OSError as exc:
            start_failure = True
            stderr_bytes = str(exc).encode("utf-8", errors="replace")
            process = None
        if process is not None:
            try:
                stdout_bytes, stderr_bytes = process.communicate(
                    input=prompt.encode("utf-8"), timeout=timeout_seconds
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    stdout_bytes, stderr_bytes = process.communicate(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout_bytes, stderr_bytes = process.communicate()
            exit_code = process.returncode
    finally:
        active_counter.leave()
    latency_ms = int(round((time.monotonic() - started) * 1000))
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    events, parse_failures, tool_event = parse_codex_jsonl(stdout)
    raw_events_path = attempt_dir / "events.jsonl"
    stderr_path = attempt_dir / "stderr.txt"
    atomic_write_bytes(raw_events_path, stdout_bytes)
    atomic_write_bytes(stderr_path, stderr_bytes)
    message = final_agent_message(events, last_message_path)
    if tool_event:
        stderr = (stderr + "\nforbidden tool-call event observed").strip()
    last_message_bytes = last_message_path.read_bytes() if last_message_path.is_file() else b""
    result = {
        "response_text": message,
        "latency_ms": latency_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "process_started": process_started,
        "start_failure": start_failure,
        "events": events,
        "event_count": len(events),
        "jsonl_parse_failures": parse_failures,
        "jsonl_integrity": parse_failures == 0,
        "tool_event": tool_event,
        "usage": provider_usage(events),
        "provider_model": provider_model(events),
        "stderr": _sanitize_string(stderr.strip()),
        "raw_events_sha256": sha256_file(raw_events_path),
        "raw_events_bytes": raw_events_path.stat().st_size,
        "stderr_sha256": sha256_file(stderr_path),
        "stderr_bytes": stderr_path.stat().st_size,
        "last_message_sha256": sha256_bytes(last_message_bytes) if last_message_bytes else None,
        "last_message_bytes": len(last_message_bytes),
        "resource_warning": _resource_warning(),
        "os_kill_resource_exhaustion": exit_code in {-9, 9, 137},
    }
    atomic_write_json(attempt_dir / "transport_result.json", result)
    return result


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_orphan_result(attempt_dir: Path) -> dict[str, Any]:
    """Recover a claimed attempt after a runner crash without duplicating it."""
    transport_path = attempt_dir / "transport_result.json"
    if transport_path.is_file():
        result = load_json(transport_path)
        result["runner_process_crash"] = True
        return result
    process_path = attempt_dir / "process.json"
    if process_path.is_file():
        process_record = load_json(process_path)
        pid = process_record.get("pid")
        if isinstance(pid, int) and _pid_is_alive(pid):
            raise RunnerError(
                f"orphan Codex process {pid} is still active for {attempt_dir}; collection paused"
            )
    raw_events_path = attempt_dir / "events.jsonl"
    stderr_path = attempt_dir / "stderr.txt"
    if not raw_events_path.exists():
        atomic_write_bytes(raw_events_path, b"")
    if not stderr_path.exists():
        atomic_write_bytes(stderr_path, b"")
    stdout = raw_events_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    events, parse_failures, tool_event = parse_codex_jsonl(stdout)
    last_message_path = attempt_dir / "last_message.txt"
    response = final_agent_message(events, last_message_path)
    last_bytes = last_message_path.read_bytes() if last_message_path.is_file() else b""
    result = {
        "response_text": response,
        "latency_ms": 0,
        "exit_code": None,
        "timed_out": False,
        "process_started": process_path.is_file(),
        "start_failure": not process_path.is_file(),
        "event_count": len(events),
        "jsonl_parse_failures": parse_failures,
        "jsonl_integrity": parse_failures == 0,
        "tool_event": tool_event,
        "usage": provider_usage(events),
        "provider_model": provider_model(events),
        "stderr": _sanitize_string(stderr.strip()),
        "raw_events_sha256": sha256_file(raw_events_path),
        "raw_events_bytes": raw_events_path.stat().st_size,
        "stderr_sha256": sha256_file(stderr_path),
        "stderr_bytes": stderr_path.stat().st_size,
        "last_message_sha256": sha256_bytes(last_bytes) if last_bytes else None,
        "last_message_bytes": len(last_bytes),
        "resource_warning": "runner crashed before durable attempt-log append",
        "os_kill_resource_exhaustion": False,
        "runner_process_crash": True,
    }
    atomic_write_json(transport_path, result)
    return result


def classify_result(
    result: dict[str, Any], call: dict[str, Any], attempt_dir: Path
) -> tuple[str, str | None, str | None]:
    response = result.get("response_text")
    if result.get("tool_event") is True:
        if not isinstance(response, str) or not response.strip():
            response = (attempt_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace")
        error = "forbidden tool-call event observed; recorded as terminal malformed model output"
        atomic_write_json(
            attempt_dir / "validation.json",
            {"valid": False, "errors": [error], "protocol_violation": True},
        )
        return "malformed_output", error, response
    if isinstance(response, str) and response.strip():
        validation = validate_raw_output(
            response,
            call["output_schema"],
            expected_case_ids=list(call["case_ids"]),
            expected_block_id=call["block_id"],
        )
        status = "semantic_response" if validation["valid"] else "malformed_output"
        error = None if validation["valid"] else "; ".join(validation["errors"][:8])
        atomic_write_json(
            attempt_dir / "validation.json",
            {key: value for key, value in validation.items() if key != "document"},
        )
        return status, error, response
    details = []
    if result.get("runner_process_crash"):
        details.append("runner process crashed before durable attempt-log append")
    if result.get("start_failure"):
        details.append("process start failure")
    if result.get("timed_out"):
        details.append("hard timeout")
    if result.get("jsonl_parse_failures"):
        details.append(f"{result['jsonl_parse_failures']} JSONL parse failure(s)")
    if result.get("exit_code") not in {0, None}:
        details.append(f"exit code {result['exit_code']}")
    if result.get("stderr"):
        details.append(str(result["stderr"])[:800])
    return "infrastructure_failure", "; ".join(details) or "no substantive final agent_message", None


def execute_call(
    *,
    experiment_root: Path,
    manifest: dict[str, Any],
    call: dict[str, Any],
    task: dict[str, Any],
    run_dir: Path,
    attempts_path: Path,
    schema_path: Path,
    binary: Path,
    cli_version: str,
    timeout_seconds: int,
    execution_batch: int,
    active_counter: ActiveCounter,
) -> dict[str, Any]:
    events_before = load_events(attempts_path)
    state = lineage_state(events_before, call["call_id"])
    if state["state"] == "closed":
        if state.get("outcome") == "infrastructure_exhausted":
            raise RunnerError(f"infrastructure retries are exhausted for {call['call_id']}")
        return {"call_id": call["call_id"], "outcome": state["outcome"], "skipped": True}
    prompt, compact_report = render_prompt(experiment_root, manifest, call, task, events_before)
    call_dir = run_dir / "calls" / call["call_id"]
    atomic_write_text(call_dir / "prompt.txt", prompt)
    atomic_write_json(call_dir / "packet_preflight.json", compact_report)
    request_sha = request_identity(prompt, call, schema_path, binary, timeout_seconds)
    atomic_write_json(
        call_dir / "request_identity.json",
        {
            "request_sha256": request_sha,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
            "prompt_identity_sha256": call["prompt_identity_sha256"],
            "schema_sha256": sha256_file(schema_path),
        },
    )
    attempt_number = int(state.get("next_attempt", 1))
    outcome = "open"
    while attempt_number <= MAX_ATTEMPTS:
        attempt_dir = call_dir / f"attempt-{attempt_number:02d}"
        if attempt_dir.exists():
            result = recover_orphan_result(attempt_dir)
        else:
            result = invoke_codex(
                binary=binary,
                call=call,
                prompt=prompt,
                schema_path=schema_path,
                attempt_dir=attempt_dir,
                timeout_seconds=timeout_seconds,
                active_counter=active_counter,
            )
        status, error, response = classify_result(result, call, attempt_dir)
        artifact_relpath = attempt_dir.relative_to(run_dir).as_posix()
        record_attempt(
            attempts_path,
            call_id=call["call_id"],
            status=status,
            request_sha256=request_sha,
            prompt_identity_sha256=call["prompt_identity_sha256"],
            response_text=response if status != "infrastructure_failure" else None,
            error=error,
            latency_ms=result["latency_ms"],
            provider_model=result.get("provider_model"),
            provider_usage=result["usage"],
            exit_code=result["exit_code"],
            timed_out=result["timed_out"],
            reasoning_effort=call["reasoning_effort"],
            requested_model=MODEL,
            cli_version=cli_version,
            session_resumed=False,
            execution_batch=execution_batch,
            jsonl_integrity=result.get("jsonl_integrity") is True,
            agent_message_present=isinstance(response, str) and bool(response.strip()),
            process_started=result["process_started"],
            start_failure=result["start_failure"],
            runner_process_crash=result.get("runner_process_crash") is True,
            system_crash=False,
            os_kill_resource_exhaustion=result["os_kill_resource_exhaustion"],
            resource_warning=result["resource_warning"],
            prompt_characters=len(prompt),
            stdout_event_count=result["event_count"],
            jsonl_parse_failures=result["jsonl_parse_failures"],
            raw_events_sha256=result.get("raw_events_sha256"),
            raw_events_bytes=result.get("raw_events_bytes"),
            stderr_sha256=result.get("stderr_sha256"),
            stderr_bytes=result.get("stderr_bytes"),
            last_message_sha256=result.get("last_message_sha256"),
            last_message_bytes=result.get("last_message_bytes"),
            artifact_relpath=artifact_relpath,
            protocol_violation=result.get("tool_event") is True,
        )
        outcome = status
        if result.get("tool_event") is True:
            atomic_write_json(
                run_dir / "protocol_violation.json",
                {
                    "call_id": call["call_id"],
                    "attempt_number": attempt_number,
                    "recorded_at": utc_now(),
                    "reason": "forbidden tool-call event",
                },
            )
            raise RunnerError(
                f"forbidden tool-call event recorded for {call['call_id']}; collection paused"
            )
        if status != "infrastructure_failure":
            break
        attempt_number += 1
    return {"call_id": call["call_id"], "outcome": outcome, "skipped": False}


def _call_states(manifest: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {call["call_id"]: lineage_state(events, call["call_id"]) for call in manifest["calls"]}


def operational_report(
    manifest: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    candidate_concurrency: int,
    timeout_seconds: int,
    active_counter: ActiveCounter,
    deadlock: bool,
    call_filter: set[str] | None = None,
) -> dict[str, Any]:
    calls = [call for call in manifest["calls"] if call_filter is None or call["call_id"] in call_filter]
    rows: list[dict[str, Any]] = []
    for call in calls:
        attempts = sorted(
            (
                event
                for event in events
                if event.get("event_type") == "attempt" and event.get("call_id") == call["call_id"]
            ),
            key=lambda event: int(event.get("attempt_number", 0)),
        )
        state = lineage_state(events, call["call_id"])
        rows.append(
            {
                "call_id": call["call_id"],
                "condition_label": call["condition_label"],
                "architecture": call["architecture"],
                "role": call["role"],
                "first_attempt_status": attempts[0].get("status") if attempts else None,
                "resolved_status": state.get("outcome"),
                "attempt_count": len(attempts),
                "latency_ms": sum(int(event.get("latency_ms", 0)) for event in attempts),
                "max_attempt_latency_ms": max((int(event.get("latency_ms", 0)) for event in attempts), default=0),
                "jsonl_integrity": all(event.get("jsonl_integrity") is True for event in attempts) if attempts else False,
                "agent_message_present": any(event.get("agent_message_present") is True for event in attempts),
                "runner_process_crash": any(event.get("runner_process_crash") is True for event in attempts),
                "system_crash": any(event.get("system_crash") is True for event in attempts),
                "os_kill_resource_exhaustion": any(
                    event.get("os_kill_resource_exhaustion") is True for event in attempts
                ),
                "session_resumed": any(event.get("session_resumed") is True for event in attempts),
                "start_failure": any(event.get("start_failure") is True for event in attempts),
                "process_started": all(event.get("process_started") is True for event in attempts) if attempts else False,
                "resource_warning": any(bool(event.get("resource_warning")) for event in attempts),
                "timed_out": any(event.get("timed_out") is True for event in attempts),
                "jsonl_parse_failures": sum(int(event.get("jsonl_parse_failures", 0)) for event in attempts),
            }
        )
    initial_failures = sum(row["first_attempt_status"] == "infrastructure_failure" for row in rows)
    unresolved = sum(row["resolved_status"] == "infrastructure_exhausted" for row in rows)
    latencies = sorted(row["max_attempt_latency_ms"] for row in rows if row["attempt_count"])

    def percentile(p: float) -> int | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, max(0, math.ceil(p * len(latencies)) - 1))
        return latencies[index]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "candidate_concurrency": candidate_concurrency,
        "timeout_seconds": timeout_seconds,
        "max_active_processes": active_counter.maximum,
        "observed_max_active_processes": active_counter.maximum,
        "deadlock": bool(deadlock),
        "planned_calls": len(calls),
        "calls_with_attempts": sum(row["attempt_count"] > 0 for row in rows),
        "closed_calls": sum(row["resolved_status"] != "open" for row in rows),
        "initial_infrastructure_failures": initial_failures,
        "initial_infrastructure_failure_rate": initial_failures / len(rows) if rows else 0.0,
        "unresolved_infrastructure_failures": unresolved,
        "latency_ms": {"p50": percentile(0.50), "p90": percentile(0.90), "p95": percentile(0.95), "max": max(latencies) if latencies else None},
        "calls": rows,
    }


def write_progress_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "call_id",
        "condition_label",
        "architecture",
        "role",
        "first_attempt_status",
        "resolved_status",
        "attempt_count",
        "latency_ms",
        "jsonl_integrity",
        "agent_message_present",
    )
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in report["calls"]:
                writer.writerow({field: row.get(field) for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def select_calls(manifest: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    calls = list(manifest["calls"])
    if args.condition:
        calls = [call for call in calls if call["condition_label"] == args.condition]
    if args.architecture:
        calls = [call for call in calls if call["architecture"] == args.architecture]
    if args.block:
        calls = [call for call in calls if call["block_id"] == args.block]
    if args.call_id:
        requested = set(args.call_id)
        calls = [call for call in calls if call["call_id"] in requested]
        missing = requested - {call["call_id"] for call in calls}
        if missing:
            raise RunnerError(f"unknown requested call IDs: {sorted(missing)}")
    return calls


def verify_prompt_components(experiment_root: Path, manifest: dict[str, Any]) -> None:
    identities = manifest.get("prompt_identities")
    if not isinstance(identities, dict) or not identities:
        raise RunnerError("manifest has no prompt identities")
    for identity_id, identity in identities.items():
        components = identity.get("components")
        if not isinstance(components, list) or not components:
            raise RunnerError(f"prompt identity {identity_id} has no components")
        for component in components:
            path = (experiment_root / str(component.get("path", ""))).resolve()
            try:
                path.relative_to(experiment_root)
            except ValueError as exc:
                raise RunnerError(f"unsafe prompt component path for {identity_id}") from exc
            if not path.is_file() or sha256_file(path) != component.get("sha256"):
                raise RunnerError(f"prompt component changed or is missing: {path}")
        if sha256_bytes(canonical_bytes(components)) != identity.get("identity_sha256"):
            raise RunnerError(f"prompt identity hash mismatch: {identity_id}")


def verify_task_binding(tasks_path: Path, manifest: dict[str, Any]) -> None:
    if sha256_file(tasks_path) != manifest.get("case_source_sha256"):
        raise RunnerError("public task file hash does not match manifest.case_source_sha256")


def verify_final_binding(
    args: argparse.Namespace,
    experiment_root: Path,
    manifest: dict[str, Any],
    binary: Path,
    run_dir: Path,
) -> dict[str, Any]:
    if args.freeze_manifest is None:
        raise RunnerError("final collection requires --freeze-manifest")
    expected_run_dir = (experiment_root / "raw" / "final").resolve()
    if run_dir != expected_run_dir:
        raise RunnerError(f"final run directory must be {expected_run_dir}")
    try:
        from freeze_experiment import verify_freeze

        freeze = verify_freeze(args.freeze_manifest.resolve(), experiment_root, binary)
    except Exception as exc:
        raise RunnerError(f"final freeze verification failed: {exc}") from exc
    frozen_manifest = (experiment_root / freeze["run_manifest_path"]).resolve()
    if frozen_manifest != args.manifest.resolve():
        raise RunnerError("--manifest is not the run manifest bound by the freeze")
    if freeze.get("run_manifest_sha256") != sha256_file(args.manifest):
        raise RunnerError("run manifest file hash does not match the freeze")
    if manifest.get("manifest_sha256") != freeze.get("run_manifest_identity_sha256"):
        raise RunnerError("run manifest identity does not match the freeze")
    if list(manifest.get("disabled_features", [])) != list(DISABLED_FEATURES):
        raise RunnerError("final manifest feature-disable list does not match the runner")
    return freeze


def write_attempt_artifact_manifest(run_dir: Path, events: list[dict[str, Any]]) -> Path:
    records: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "attempt":
            continue
        relative = event.get("artifact_relpath")
        if not isinstance(relative, str):
            raise RunnerError(f"attempt {event.get('call_id')} has no artifact_relpath")
        attempt_dir = (run_dir / relative).resolve()
        try:
            attempt_dir.relative_to(run_dir)
        except ValueError as exc:
            raise RunnerError(f"unsafe artifact path for {event.get('call_id')}") from exc
        expected = {
            "events.jsonl": (event.get("raw_events_sha256"), event.get("raw_events_bytes")),
            "stderr.txt": (event.get("stderr_sha256"), event.get("stderr_bytes")),
        }
        if event.get("last_message_bytes", 0):
            expected["last_message.txt"] = (
                event.get("last_message_sha256"), event.get("last_message_bytes")
            )
        for name, (expected_hash, expected_bytes) in expected.items():
            path = attempt_dir / name
            if (
                not path.is_file()
                or sha256_file(path) != expected_hash
                or path.stat().st_size != expected_bytes
            ):
                raise RunnerError(f"raw artifact changed or is missing: {relative}/{name}")
        for path in sorted(candidate for candidate in attempt_dir.rglob("*") if candidate.is_file()):
            artifact_relative = path.relative_to(run_dir).as_posix()
            records[artifact_relative] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": "attempt-artifacts-v1",
        "generated_at": utc_now(),
        "artifact_count": len(records),
        "artifacts": records,
        "artifact_set_sha256": sha256_bytes(canonical_bytes(records)),
    }
    path = run_dir / "attempt_artifacts.json"
    atomic_write_json(path, manifest)
    return path


def _run_collection_locked(args: argparse.Namespace) -> int:
    experiment_root = args.experiment_root.resolve()
    manifest_path = args.manifest.resolve()
    tasks_path = args.tasks.resolve()
    manifest = load_json(manifest_path)
    validate_manifest(manifest)
    verify_prompt_components(experiment_root, manifest)
    verify_task_binding(tasks_path, manifest)
    tasks = load_tasks(tasks_path)
    binary = args.codex_binary.resolve()
    if not binary.is_file():
        raise RunnerError(f"Codex binary does not exist: {binary}")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        raise RunnerError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    if args.timeout != DEFAULT_TIMEOUT_SECONDS:
        raise RunnerError(f"timeout must remain frozen at {DEFAULT_TIMEOUT_SECONDS} seconds")
    selected = select_calls(manifest, args)
    if not selected:
        raise RunnerError("call selection is empty")
    selected_ids = {call["call_id"] for call in selected}
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    violation_path = run_dir / "protocol_violation.json"
    if violation_path.exists():
        raise RunnerError(f"unresolved protocol violation marker exists: {violation_path}")
    attempts_path = run_dir / "attempts.jsonl"
    schemas = write_schema_files(experiment_root, run_dir)
    cli_version = read_cli_version(binary)
    freeze: dict[str, Any] | None = None
    if manifest.get("split") == "final":
        if args.max_calls is not None:
            raise RunnerError("--max-calls is forbidden for final collection")
        freeze = verify_final_binding(args, experiment_root, manifest, binary, run_dir)
        if args.condition or args.architecture or args.block or args.call_id:
            raise RunnerError("final collection must execute the complete frozen manifest without arm filters")
        if manifest.get("selected_concurrency") != args.concurrency:
            raise RunnerError("requested concurrency does not match the frozen final manifest")
        if manifest.get("timeout_seconds") != args.timeout:
            raise RunnerError("requested timeout does not match the frozen final manifest")
        if manifest.get("codex_cli_version") != cli_version:
            raise RunnerError("Codex CLI version drifted from the frozen final manifest")
        if manifest.get("codex_binary_sha256") != sha256_file(binary):
            raise RunnerError("Codex CLI binary hash drifted from the frozen final manifest")
        if manifest.get("runner_sha256") != sha256_file(Path(__file__).resolve()):
            raise RunnerError("runner source hash drifted from the frozen final manifest")
        if not isinstance(manifest.get("execution_batches"), list):
            raise RunnerError("final manifest has no frozen execution-batch plan")
    prior_maximum = 0
    prior_report_path = run_dir / "operational_report.json"
    if prior_report_path.is_file():
        prior_report = load_json(prior_report_path)
        prior_maximum = int(
            prior_report.get("max_active_processes", prior_report.get("observed_max_active_processes", 0))
        )
    active_counter = ActiveCounter(prior_maximum)
    deadlock = False
    batch_index = 0
    completed_this_invocation = 0
    while True:
        events = load_events(attempts_path)
        validate_events(events, {call["call_id"] for call in manifest["calls"]})
        states = _call_states(manifest, events)
        exhausted = [
            call_id for call_id, state in states.items()
            if state.get("outcome") == "infrastructure_exhausted"
        ]
        if exhausted:
            raise RunnerError(
                f"infrastructure retries exhausted for {len(exhausted)} call(s); collection paused"
            )
        remaining = [call for call in selected if states[call["call_id"]]["state"] == "open"]
        if not remaining:
            break
        frozen_batches = manifest.get("execution_batches")
        if isinstance(frozen_batches, list):
            next_batch = next(
                (
                    batch for batch in frozen_batches
                    if any(states[call_id]["state"] == "open" for call_id in batch["call_ids"])
                ),
                None,
            )
            if next_batch is None:
                break
            call_map = {call["call_id"]: call for call in selected}
            ready = [
                call_map[call_id]
                for call_id in next_batch["call_ids"]
                if states[call_id]["state"] == "open"
                and all(
                    states[dependency].get("outcome") in {"semantic_response", "malformed_output"}
                    for dependency in call_map[call_id]["dependency_call_ids"]
                )
            ]
            batch_index = int(next_batch["batch_id"])
        else:
            ready = [
                call
                for call in remaining
                if all(
                    states[dependency].get("outcome") in {"semantic_response", "malformed_output"}
                    for dependency in call["dependency_call_ids"]
                )
            ]
            ready.sort(key=lambda call: call["schedule_index"])
            batch_index += 1
        if not ready:
            deadlock = True
            break
        if args.max_calls is not None:
            available = args.max_calls - completed_this_invocation
            if available <= 0:
                break
            ready = ready[:available]
        batch = ready[: args.concurrency]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(
                    execute_call,
                    experiment_root=experiment_root,
                    manifest=manifest,
                    call=call,
                    task=tasks[call["block_id"]],
                    run_dir=run_dir,
                    attempts_path=attempts_path,
                    schema_path=schemas[call["output_schema"]],
                    binary=binary,
                    cli_version=cli_version,
                    timeout_seconds=args.timeout,
                    execution_batch=batch_index,
                    active_counter=active_counter,
                )
                for call in batch
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()
        completed_this_invocation += len(batch)
        events = load_events(attempts_path)
        report = operational_report(
            manifest,
            events,
            candidate_concurrency=args.concurrency,
            timeout_seconds=args.timeout,
            active_counter=active_counter,
            deadlock=False,
            call_filter=selected_ids,
        )
        atomic_write_json(run_dir / "operational_report.json", report)
        write_progress_csv(run_dir / "run_progress.csv", report)
        states = _call_states(manifest, events)
        exhausted = [call_id for call_id, state in states.items() if state.get("outcome") == "infrastructure_exhausted"]
        if exhausted:
            raise RunnerError(f"infrastructure retries exhausted for {len(exhausted)} call(s); collection paused")
        if args.max_calls is not None and completed_this_invocation >= args.max_calls:
            break

    events = load_events(attempts_path)
    report = operational_report(
        manifest,
        events,
        candidate_concurrency=args.concurrency,
        timeout_seconds=args.timeout,
        active_counter=active_counter,
        deadlock=deadlock,
        call_filter=selected_ids,
    )
    atomic_write_json(run_dir / "operational_report.json", report)
    write_progress_csv(run_dir / "run_progress.csv", report)
    if deadlock:
        raise RunnerError("dependency deadlock or an unselected prerequisite prevented progress")

    all_states = _call_states(manifest, events)
    if all(state["state"] == "closed" and state.get("outcome") in {"semantic_response", "malformed_output"} for state in all_states.values()):
        artifact_manifest = write_attempt_artifact_manifest(run_dir, events)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "collection_closed": True,
            "closed_at": utc_now(),
            "terminal_call_count": len(manifest["calls"]),
            "attempt_log_sha256": sha256_file(attempts_path),
            "run_manifest_sha256": sha256_file(manifest_path),
            "run_manifest_identity_sha256": manifest["manifest_sha256"],
            "selected_concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
            "codex_cli_version": cli_version,
            "codex_binary_sha256": sha256_file(binary),
            "task_file_sha256": sha256_file(tasks_path),
            "attempt_artifact_manifest_sha256": sha256_file(artifact_manifest),
        }
        if freeze is not None:
            receipt.update(
                {
                    "freeze_manifest_sha256": sha256_file(args.freeze_manifest.resolve()),
                    "freeze_manifest_identity_sha256": freeze["freeze_manifest_sha256"],
                    "freeze_immutable_set_sha256": freeze["immutable_set_sha256"],
                }
            )
        atomic_write_json(run_dir / "collection_closed.json", receipt)
    print(json.dumps({
        "status": "complete" if report["closed_calls"] == report["planned_calls"] else "partial",
        "selected_calls": report["planned_calls"],
        "closed_calls": report["closed_calls"],
        "initial_infrastructure_failures": report["initial_infrastructure_failures"],
        "observed_max_active_processes": report["observed_max_active_processes"],
        "run_dir": str(run_dir),
    }, indent=2, sort_keys=True))
    return 0


def run_collection(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with RunDirectoryLock(run_dir):
        return _run_collection_locked(args)


def derive_load_report(args: argparse.Namespace) -> int:
    manifest = load_json(args.manifest)
    validate_manifest(manifest)
    events = load_events(args.attempts)
    selected = [
        call for call in manifest["calls"]
        if call["condition_label"] == args.condition and call["architecture"] == "independent"
    ]
    if len(selected) != 20:
        raise RunnerError(f"load-gate pool must contain exactly 20 calls, found {len(selected)}")
    source_report = load_json(args.operational_report)
    source_call_ids = {
        row.get("call_id") for row in source_report.get("calls", []) if isinstance(row, dict)
    }
    selected_ids = {call["call_id"] for call in selected}
    if source_call_ids != selected_ids:
        raise RunnerError("operational report does not describe exactly the frozen 20-call load pool")
    if source_report.get("candidate_concurrency") != 20:
        raise RunnerError("load-pool operational report was not run at candidate concurrency 20")
    if source_report.get("timeout_seconds") != DEFAULT_TIMEOUT_SECONDS:
        raise RunnerError("load-pool operational report used the wrong timeout")
    observed = source_report.get(
        "max_active_processes", source_report.get("observed_max_active_processes")
    )
    if not isinstance(observed, int) or isinstance(observed, bool):
        raise RunnerError("operational report has no measured max_active_processes")
    counter = ActiveCounter(observed)
    report = operational_report(
        manifest,
        events,
        candidate_concurrency=20,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        active_counter=counter,
        deadlock=False,
        call_filter={call["call_id"] for call in selected},
    )
    report["source_operational_report_sha256"] = sha256_file(args.operational_report)
    atomic_write_json(args.output, report)
    print(json.dumps({key: report[key] for key in (
        "planned_calls", "initial_infrastructure_failures", "unresolved_infrastructure_failures",
        "max_active_processes", "observed_max_active_processes", "deadlock",
    )}, indent=2, sort_keys=True))
    return 0


def _fake_solver_response(prompt: str) -> dict[str, Any]:
    match = re.search(r'"block_id":"([^"]+)"', prompt)
    case_ids = []
    for case_id in re.findall(r'"case_id":"([^"]+)"', prompt):
        if case_id not in case_ids:
            case_ids.append(case_id)
    if match is None or len(case_ids) < 12:
        raise AssertionError("fixture prompt did not contain one canonical task block")
    return {
        "schema_version": "2.0",
        "block_id": match.group(1),
        "results": [
            {
                "case_id": case_id,
                "answer": ["1", "2", "3", "4", "5"],
                "confidence": 0.5,
                "rule_summary": "Fixture exact rule.",
                "check_summary": "Fixture checked.",
            }
            for case_id in case_ids[:12]
        ],
    }


def self_test() -> None:
    script_dir = Path(__file__).resolve().parent
    experiment_root = script_dir.parent
    task = load_json(experiment_root / "benchmark" / "public" / "development_block.json")
    call = {
        "call_id": "fixture-light-independent-s01",
        "block_id": task["block_id"],
        "case_ids": [case["case_id"] for case in task["cases"]],
        "condition_label": "light",
        "reasoning_effort": "low",
        "architecture": "independent",
        "role": "solver",
        "role_index": 1,
        "slot_id": "S01",
        "output_schema": "solver",
        "prompt_identity_id": "independent.solver",
    }
    prompts = experiment_root / "prompts"
    components = ["COMMON_PREFIX.txt", "INDEPENDENT_SOLVER.txt", "ROLE_CATALOG.json", "SCHEMAS.json"]
    identity = sha256_bytes(canonical_bytes([
        {"path": f"prompts/{name}", "sha256": sha256_file(prompts / name)} for name in components
    ]))
    call["prompt_identity_sha256"] = identity
    manifest = {
        "schedule_seed": "fixture",
        "calls": [call],
        "prompt_identities": {
            "independent.solver": {
                "template": "prompts/INDEPENDENT_SOLVER.txt",
                "identity_sha256": identity,
            }
        },
    }
    prompt, compact = render_prompt(experiment_root, manifest, call, task, [])
    assert "{{" not in prompt and compact["after_characters"] == 0
    response = _fake_solver_response(prompt)
    validation = validate_raw_output(
        json.dumps(response), "solver", expected_case_ids=call["case_ids"], expected_block_id=call["block_id"]
    )
    assert validation["valid"], validation
    sample_events = [
        {"type": "thread.started", "thread_id": "123e4567-e89b-42d3-a456-426614174000"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(response)}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]
    raw = "\n".join(json.dumps(event) for event in sample_events)
    parsed, failures, tool_event = parse_codex_jsonl(raw)
    assert failures == 0 and not tool_event and parsed[0]["thread_id"].startswith("123e4567")
    with tempfile.TemporaryDirectory() as directory:
        last = Path(directory) / "missing.txt"
        assert final_agent_message(parsed, last) == json.dumps(response)
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        fake = fixture / "fake_codex.py"
        raw_fixture = (
            '{"type":"thread.started","thread_id":"00000000-0000-4000-8000-000000000000"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"ok\\":true}"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":4}}\n'
        )
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "_ = sys.stdin.buffer.read()\n"
            "p=pathlib.Path(args[args.index('--output-last-message')+1])\n"
            "p.write_text('{\\\"ok\\\":true}', encoding='utf-8')\n"
            f"sys.stdout.write({raw_fixture!r})\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        schema = fixture / "schema.json"
        schema.write_text("{}\n", encoding="utf-8")
        attempt = fixture / "attempt"
        result = invoke_codex(
            binary=fake,
            call={"call_id": "fixture-call", "reasoning_effort": "low"},
            prompt="fixture prompt\n",
            schema_path=schema,
            attempt_dir=attempt,
            timeout_seconds=30,
            active_counter=ActiveCounter(),
        )
        assert (attempt / "events.jsonl").read_bytes() == raw_fixture.encode("utf-8")
        assert result["response_text"] == '{"ok":true}' and result["jsonl_integrity"] is True
        with RunDirectoryLock(fixture / "locked"):
            try:
                with RunDirectoryLock(fixture / "locked"):
                    raise AssertionError("nested run lock unexpectedly succeeded")
            except RunnerError:
                pass
    assert provider_usage(parsed) == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    command = build_command(Path("/frozen/codex"), "low", Path("/schema"), Path("/empty"), Path("/last"))
    for feature in (
        "shell_tool", "browser_use", "image_generation", "workspace_dependencies",
        "multi_agent", "remote_plugin", "standalone_web_search",
    ):
        position = command.index(feature)
        assert command[position - 1] == "--disable"
    assert "--ephemeral" in command and "--ignore-user-config" in command and "--ignore-rules" in command
    print("run_codex_cli.py self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="execute or resume a manifest selection")
    run.add_argument("--experiment-root", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--tasks", type=Path, required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--codex-binary", type=Path, required=True)
    run.add_argument(
        "--freeze-manifest", type=Path,
        help="required for final collection; verifies every frozen input before execution",
    )
    run.add_argument("--concurrency", type=int, required=True)
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument("--condition", choices=("light", "medium"))
    run.add_argument("--architecture", choices=("independent", "swarm10", "tournament20"))
    run.add_argument("--block")
    run.add_argument("--call-id", action="append")
    run.add_argument("--max-calls", type=int)

    load = sub.add_parser("load-report", help="derive the monitored 20-call operational report")
    load.add_argument("--manifest", type=Path, required=True)
    load.add_argument("--attempts", type=Path, required=True)
    load.add_argument("--operational-report", type=Path, required=True)
    load.add_argument("--condition", choices=("light", "medium"), required=True)
    load.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.command == "run":
            return run_collection(args)
        if args.command == "load-report":
            return derive_load_report(args)
        parser.print_help()
        return 2
    except (RunnerError, AttemptLogError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"runner error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
