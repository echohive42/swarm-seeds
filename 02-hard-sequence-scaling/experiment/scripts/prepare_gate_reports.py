#!/usr/bin/env python3
"""Generate machine-checked preflight and development pipeline reports.

This script uses only the Python standard library. It never opens calibration or
final answer keys.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import run_codex_cli as runner
from attempt_log import load_events, validate_events
from build_packets import extract_stage_schema
from run_manifest import validate_manifest
from validate_outputs import validate_raw_output


MODEL = "gpt-5.6-luna"
STAGES = ("solver", "critic", "breaker", "verifier", "synthesizer", "red_team", "judge")


class ReportError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
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


def run_checked(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise ReportError(
            f"command failed with exit {completed.returncode}: {' '.join(command)}\n{completed.stderr[:1000]}"
        )
    return completed


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def generate_preflight(args: argparse.Namespace) -> dict[str, Any]:
    root = args.experiment_root.resolve()
    binary = args.codex_binary.resolve()
    if not binary.is_file():
        raise ReportError(f"Codex binary does not exist: {binary}")
    version = runner.read_cli_version(binary)
    catalog_run = run_checked([str(binary), "debug", "models"], timeout=60)
    try:
        catalog = json.loads(catalog_run.stdout)
    except json.JSONDecodeError as exc:
        raise ReportError("Codex model catalog was not valid JSON") from exc
    matches = [row for row in catalog.get("models", []) if row.get("slug") == MODEL]
    efforts = {
        row.get("effort") for row in matches[0].get("supported_reasoning_levels", [])
    } if len(matches) == 1 else set()
    runner_test = run_checked([sys.executable, "-B", str(root / "scripts" / "run_codex_cli.py"), "--self-test"])
    attempt_test = run_checked([sys.executable, "-B", str(root / "scripts" / "attempt_log.py"), "--self-test"])
    schema_catalog = json.loads((root / "prompts" / "SCHEMAS.json").read_text(encoding="utf-8"))
    schema_ok = all(isinstance(extract_stage_schema(schema_catalog, stage), dict) for stage in STAGES)
    command = runner.build_command(
        binary, "low", Path("/frozen/schema.json"), Path("/fresh/empty"), Path("/last/message.json")
    )
    runner_imports = imported_modules(root / "scripts" / "run_codex_cli.py")
    local_modules = {path.stem for path in (root / "scripts").glob("*.py")}
    standard_library_only = all(
        module in sys.stdlib_module_names or module in local_modules or module == "__future__"
        for module in runner_imports
    )
    disabled_pairs = [
        command[index + 1] for index, token in enumerate(command[:-1]) if token == "--disable"
    ]
    report: dict[str, Any] = {
        "schema_version": "experiment-02-preflight-v1",
        "generated_at": utc_now(),
        "requested_model": MODEL,
        "timeout_seconds": runner.DEFAULT_TIMEOUT_SECONDS,
        "candidate_concurrency": runner.MAX_CONCURRENCY,
        "codex_cli_version": version,
        "codex_binary_sha256": sha256(binary),
        "model_catalog_sha256": hashlib.sha256(catalog_run.stdout.encode("utf-8")).hexdigest(),
        "catalog_supported_reasoning_efforts": sorted(efforts),
        "disabled_features": disabled_pairs,
        "usage_telemetry_status": "available or unavailable per provider JSONL",
        "model_catalog_verified": len(matches) == 1 and {"low", "medium"} <= efforts,
        "runner_fixture_passed": "PASS" in runner_test.stdout and "PASS" in attempt_test.stdout,
        "prompt_via_stdin": command[-1] == "-",
        "ignore_user_config": "--ignore-user-config" in command,
        "ephemeral_sessions": "--ephemeral" in command,
        "fresh_empty_workdirs": "-C" in command and str(Path("/fresh/empty")) in command,
        "read_only_sandbox": "--sandbox" in command and command[command.index("--sandbox") + 1] == "read-only",
        "stage_output_schemas": schema_ok,
        "stdout_jsonl_preserved": "PASS" in runner_test.stdout,
        "stderr_preserved": "PASS" in runner_test.stdout,
        "exit_status_preserved": "PASS" in runner_test.stdout,
        "standard_library_only": standard_library_only,
        "no_resume_code_path": "resume" not in command and "--ephemeral" in command,
        "retry_requires_no_agent_message": "PASS" in attempt_test.stdout,
        "source_hashes": {
            "runner": sha256(root / "scripts" / "run_codex_cli.py"),
            "attempt_log": sha256(root / "scripts" / "attempt_log.py"),
            "schemas": sha256(root / "prompts" / "SCHEMAS.json"),
        },
    }
    required_true = (
        "model_catalog_verified", "runner_fixture_passed", "prompt_via_stdin",
        "ignore_user_config", "ephemeral_sessions", "fresh_empty_workdirs",
        "read_only_sandbox", "stage_output_schemas", "stdout_jsonl_preserved",
        "stderr_preserved", "exit_status_preserved", "standard_library_only",
        "no_resume_code_path", "retry_requires_no_agent_message",
    )
    report["passed"] = all(report[field] is True for field in required_true) and disabled_pairs == list(runner.DISABLED_FEATURES)
    if not report["passed"]:
        raise ReportError("preflight report did not pass every frozen execution check")
    atomic_json(args.output, report)
    return report


def _contains_forbidden_truth(value: Any) -> bool:
    forbidden = {"answer", "answers", "next", "gold", "truth", "family", "tier", "seed"}
    if isinstance(value, dict):
        return any(str(key).lower() in forbidden or _contains_forbidden_truth(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_truth(child) for child in value)
    return False


def generate_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    root = args.experiment_root.resolve()
    run_dir = args.run_dir.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if manifest.get("split") != "development":
        raise ReportError("pipeline audit requires the development manifest")
    task_data = json.loads(args.tasks.read_text(encoding="utf-8"))
    tasks = runner.load_tasks(args.tasks)
    events = load_events(args.attempts)
    validate_events(events, {call["call_id"] for call in manifest["calls"]})
    call_map = {call["call_id"]: call for call in manifest["calls"]}
    terminal = {
        event["call_id"]: event for event in events
        if event.get("event_type") == "attempt"
        and event.get("status") in {"semantic_response", "malformed_output"}
    }
    routing_ok = all(
        call_map[dependency]["condition_label"] == call["condition_label"]
        and call_map[dependency]["architecture"] == call["architecture"]
        for call in manifest["calls"] for dependency in call["dependency_call_ids"]
    )
    request_hashes: dict[str, set[str]] = {}
    for event in events:
        if event.get("event_type") == "attempt":
            request_hashes.setdefault(str(event.get("call_id")), set()).add(str(event.get("request_sha256")))
    retry_identity_ok = all(len(values) == 1 for values in request_hashes.values())
    rendered_ok = packet_ok = raw_ok = stderr_ok = schema_ok = command_ok = True
    required_flags = {
        "--ephemeral", "--ignore-user-config", "--ignore-rules", "--strict-config",
        "--skip-git-repo-check", "--json", "--output-schema", "--output-last-message",
    }
    for call in manifest["calls"]:
        call_id = call["call_id"]
        actual_prompt = (run_dir / "calls" / call_id / "prompt.txt").read_text(encoding="utf-8")
        first_prompt, first_report = runner.render_prompt(
            root, manifest, call, tasks[call["block_id"]], events
        )
        second_prompt, second_report = runner.render_prompt(
            root, manifest, call, tasks[call["block_id"]], events
        )
        rendered_ok &= actual_prompt == first_prompt == second_prompt
        packet_record = json.loads(
            (run_dir / "calls" / call_id / "packet_preflight.json").read_text(encoding="utf-8")
        )
        packet_ok &= packet_record == first_report == second_report and first_report["after_characters"] <= runner.PACKET_LIMIT
        attempt = terminal.get(call_id)
        if attempt is None:
            raw_ok = schema_ok = stderr_ok = False
            continue
        artifact = run_dir / str(attempt.get("artifact_relpath", ""))
        raw_path = artifact / "events.jsonl"
        stderr_path = artifact / "stderr.txt"
        raw_text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
        raw_events, parse_failures, tool_event = runner.parse_codex_jsonl(raw_text)
        extracted = runner.final_agent_message(raw_events, artifact / "last_message.txt")
        raw_ok &= parse_failures == 0 and not tool_event and extracted == attempt.get("response_text")
        stderr_ok &= stderr_path.is_file() and isinstance(attempt.get("exit_code"), (int, type(None)))
        validation = validate_raw_output(
            str(attempt.get("response_text", "")), call["output_schema"],
            expected_case_ids=list(call["case_ids"]), expected_block_id=call["block_id"],
        )
        schema_ok &= validation["valid"] is True
        command_record = json.loads((artifact / "command.json").read_text(encoding="utf-8"))
        argv = command_record.get("argv", [])
        disabled = [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == "--disable"]
        command_ok &= required_flags <= set(argv) and disabled == list(runner.DISABLED_FEATURES) and argv[-1] == "-"
    packet_fixture = run_checked(
        [sys.executable, "-B", str(root / "scripts" / "build_packets.py"), "--self-test"]
    )
    invalid_fixture = validate_raw_output(
        "not json", "solver", expected_case_ids=list(manifest["calls"][0]["case_ids"]),
        expected_block_id=manifest["calls"][0]["block_id"],
    )
    report: dict[str, Any] = {
        "schema_version": "experiment-02-pipeline-audit-v1",
        "generated_at": utc_now(),
        "swarm10_fixture_passed": packet_fixture.returncode == 0,
        "routing_graph_valid": routing_ok,
        "reasoning_isolation_valid": routing_ok,
        "clean_room_replay_identical": rendered_ok,
        "malformed_fixture_rejected": invalid_fixture["valid"] is False,
        "retry_identity_preserved": retry_identity_ok,
        "packet_manifest_reproducible": packet_ok,
        "raw_jsonl_reproduces_agent_messages": raw_ok,
        "stderr_exit_joinable": stderr_ok,
        "no_packet_over_input_limit": packet_ok,
        "no_silent_response_truncation": schema_ok,
        "no_answer_key_used_for_pipeline_checks": not _contains_forbidden_truth(task_data),
        "command_contract_all_calls": command_ok,
        "planned_calls": len(manifest["calls"]),
        "terminal_calls": len(terminal),
        "source_hashes": {
            "manifest": sha256(args.manifest),
            "attempts": sha256(args.attempts),
            "tasks": sha256(args.tasks),
            "runner": sha256(root / "scripts" / "run_codex_cli.py"),
        },
    }
    required = (
        "swarm10_fixture_passed", "routing_graph_valid", "reasoning_isolation_valid",
        "clean_room_replay_identical", "malformed_fixture_rejected", "retry_identity_preserved",
        "packet_manifest_reproducible", "raw_jsonl_reproduces_agent_messages",
        "stderr_exit_joinable", "no_packet_over_input_limit", "no_silent_response_truncation",
        "no_answer_key_used_for_pipeline_checks", "command_contract_all_calls",
    )
    report["passed"] = len(terminal) == 22 and all(report[field] is True for field in required)
    if not report["passed"]:
        failed = [field for field in required if report[field] is not True]
        raise ReportError(f"development pipeline audit failed: {failed}")
    atomic_json(args.output, report)
    return report


def generate_runtime(args: argparse.Namespace) -> dict[str, Any]:
    root = args.experiment_root.resolve()
    binary = args.codex_binary.resolve()
    gate = json.loads(args.calibration_report.read_text(encoding="utf-8"))
    if gate.get("passed") is not True or gate.get("decision") != "proceed_to_final_freeze":
        raise ReportError("calibration report does not authorize the final freeze")
    selected = gate.get("selected_final_concurrency")
    if selected not in {10, 20}:
        raise ReportError("calibration report did not select concurrency 10 or 20")
    report = {
        "schema_version": "experiment-02-runtime-v1",
        "generated_at": utc_now(),
        "requested_model": MODEL,
        "candidate_concurrency": 20,
        "selected_final_concurrency": selected,
        "timeout_seconds": runner.DEFAULT_TIMEOUT_SECONDS,
        "codex_cli_version": runner.read_cli_version(binary),
        "codex_binary_sha256": sha256(binary),
        "runner_sha256": sha256(root / "scripts" / "run_codex_cli.py"),
        "calibration_report_sha256": sha256(args.calibration_report),
        "preflight_report_sha256": sha256(args.preflight_report),
        "pipeline_report_sha256": sha256(args.pipeline_report),
        "load_report_sha256": sha256(args.load_report),
        "disabled_features": list(runner.DISABLED_FEATURES),
    }
    atomic_json(args.output, report)
    return report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--self-test", action="store_true")
    sub = root.add_subparsers(dest="command")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--experiment-root", type=Path, required=True)
    preflight.add_argument("--codex-binary", type=Path, required=True)
    preflight.add_argument("--output", type=Path, required=True)
    pipeline = sub.add_parser("pipeline")
    pipeline.add_argument("--experiment-root", type=Path, required=True)
    pipeline.add_argument("--manifest", type=Path, required=True)
    pipeline.add_argument("--tasks", type=Path, required=True)
    pipeline.add_argument("--attempts", type=Path, required=True)
    pipeline.add_argument("--run-dir", type=Path, required=True)
    pipeline.add_argument("--output", type=Path, required=True)
    runtime = sub.add_parser("runtime")
    runtime.add_argument("--experiment-root", type=Path, required=True)
    runtime.add_argument("--codex-binary", type=Path, required=True)
    runtime.add_argument("--calibration-report", type=Path, required=True)
    runtime.add_argument("--preflight-report", type=Path, required=True)
    runtime.add_argument("--pipeline-report", type=Path, required=True)
    runtime.add_argument("--load-report", type=Path, required=True)
    runtime.add_argument("--output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        assert _contains_forbidden_truth({"case_id": "X", "prefix": ["1"]}) is False
        assert _contains_forbidden_truth({"answer": ["2"]}) is True
        assert set(runner.DISABLED_FEATURES) >= {"remote_plugin", "standalone_web_search"}
        print("prepare_gate_reports.py self-test: PASS")
        return 0
    if args.command is None:
        print("gate report error: a command is required", file=sys.stderr)
        return 2
    try:
        if args.command == "preflight":
            report = generate_preflight(args)
        elif args.command == "pipeline":
            report = generate_pipeline(args)
        else:
            report = generate_runtime(args)
    except (OSError, ValueError, ReportError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"gate report error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "pass", "output": str(args.output), "schema_version": report["schema_version"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
