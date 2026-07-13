#!/usr/bin/env python3
"""Fail-closed, standard-library release audit for Experiment 03."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent

RUNS = (
    ("generation-00", "runs/search/generation-00", "stage-04-judge.json", 60, "search-g0", ("training-b01",)),
    ("generation-01", "runs/search/generation-01", "stage-04-judge.json", 60, "search-g1", ("training-b01",)),
    ("generation-02", "runs/search/generation-02", "stage-04-judge.json", 60, "search-g2", ("training-b01",)),
    ("validation", "runs/validation", "stage-04-judge.json", 60, "validation", ("validation-b01", "validation-b02")),
    ("final-structured", "runs/final/structured", "stage-04-judge.json", 120, "final", ("final-b01", "final-b02", "final-b03", "final-b04")),
    ("final-vote10", "runs/final/vote10", "vote10.json", 40, "final", ("final-b01", "final-b02", "final-b03", "final-b04")),
    ("final-vote10-generalist", "runs/final/vote10-generalist", "vote10-generalist.json", 40, "final-amendment-01", ("final-b01", "final-b02", "final-b03", "final-b04")),
)

SCORE_TARGETS = (
    ("generation-00", "runs/search/generation-00/predictions.json", "results/search/generation-00/summary.json", 12),
    ("generation-01", "runs/search/generation-01/predictions.json", "results/search/generation-01/summary.json", 12),
    ("generation-02", "runs/search/generation-02/predictions.json", "results/search/generation-02/summary.json", 12),
    ("validation", "runs/validation/predictions.json", "results/validation/summary.json", 24),
    ("final", "runs/final/predictions.json", "results/final/summary.json", 48),
    ("final-diversified-vote", "runs/final/predictions-diversified-vote.json", "results/final-diversified-vote/summary.json", 48),
)

EXPECTED_PLAN = {
    "evolution": 180,
    "validation": 60,
    "final_structured": 120,
    "final_vote10": 40,
    "final": 160,
    "total": 400,
}

EXPECTED_BINARY_SHA256 = "718724d7221cf1298071ca92411cb74caa8422809154150cedca7b569a4518e3"
REGISTERED_TIMEOUT_SECONDS = 300
AMENDMENT_TIMEOUT_SECONDS = 600

METHOD_SOURCES = {
    "generation-00": "genomes/generation-00.json",
    "generation-01": "genomes/generation-01.json",
    "generation-02": "genomes/generation-02.json",
    "validation": "genomes/validation-population.json",
    "final-structured": "genomes/final-population.json",
}

DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "computer_use", "enable_mcp_apps", "goals", "hooks", "image_generation",
    "in_app_browser", "multi_agent", "multi_agent_v2", "plugin_sharing", "plugins",
    "remote_plugin", "shell_tool", "skill_mcp_dependency_install",
    "standalone_web_search", "tool_suggest", "unified_exec", "workspace_dependencies",
)

SECRET_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|password|client[_-]?secret|private[_-]?key)$", re.I)
SECRET_TEXT = re.compile(r"(?:\bsk-[A-Za-z0-9_-]{16,}|\bgh[opusr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|\bBearer\s+[A-Za-z0-9._~+/=-]{16,})")
HOME_PATH = re.compile(r"(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+)(?:/[^\s\"',]*)?")
THREAD_KEY = re.compile(r"^(?:thread|conversation|session|task)[_-]?id$", re.I)
THREAD_TEXT = re.compile(r"\b(?:thread|conversation|session|task)[_-]?id\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]{8,}", re.I)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(encoded)


def expected_request_sha256(job: dict[str, object], binary_hash: str, timeout: int) -> str:
    identity = {
        "prompt_sha256": sha256_bytes(str(job["prompt"]).encode("utf-8")),
        "schema_sha256": canonical_sha256(job["output_schema"]),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "binary_sha256": binary_hash,
        "timeout": timeout,
        "disabled_features": list(DISABLED_FEATURES),
    }
    return canonical_sha256(identity)


def sorted_counts(values: object) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def peak_concurrency(attempts: list[dict[str, object]]) -> tuple[int, list[str]]:
    """Return peak overlap for half-open [started_at, finished_at) intervals."""
    events: list[tuple[datetime, int]] = []
    errors = []
    for event in attempts:
        job_id = str(event.get("job_id"))
        try:
            started = datetime.fromisoformat(str(event["started_at"]).replace("Z", "+00:00"))
            finished = datetime.fromisoformat(str(event["finished_at"]).replace("Z", "+00:00"))
            if finished < started:
                raise ValueError("finished before started")
        except (KeyError, ValueError) as exc:
            errors.append(f"{job_id}: {exc}")
            continue
        events.extend(((started, 1), (finished, -1)))
    active = peak = 0
    # End events sort before start events at equal timestamps: intervals are half-open.
    for _timestamp, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    if active != 0:
        errors.append(f"unbalanced interval sweep ended at {active}")
    return peak, errors


def frozen_public_command() -> dict[str, object]:
    argv = [
        "<FROZEN_CODEX_BINARY>", "exec", "--model", "gpt-5.6-luna", "-c",
        'model_reasoning_effort="low"', "--ephemeral", "--ignore-user-config",
        "--ignore-rules", "--strict-config", "--skip-git-repo-check", "--sandbox",
        "read-only",
    ]
    for feature in DISABLED_FEATURES:
        argv.extend(("--disable", feature))
    argv.extend((
        "--json", "--color", "never", "--output-schema", "<OUTPUT_SCHEMA>",
        "--output-last-message", "<LAST_MESSAGE>", "-C", "<FRESH_EMPTY_WORKSPACE>", "-",
    ))
    return {"argv": argv, "prompt_transport": "stdin"}


class Audit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.checks: list[dict[str, object]] = []

    def check(self, name: str, condition: bool, detail: object) -> None:
        self.checks.append({"name": name, "passed": bool(condition), "detail": detail})

    def audit_freeze(self) -> dict[str, object]:
        path = self.root / "freeze_manifest.json"
        manifest = load_json(path)
        assert isinstance(manifest, dict)
        declared = manifest.get("files", {})
        mismatches = []
        for relative, expected in sorted(declared.items()):
            candidate = self.root / relative
            actual = file_sha256(candidate) if candidate.is_file() else None
            if actual != expected:
                mismatches.append({"path": relative, "expected": expected, "actual": actual})
        without_self = dict(manifest)
        declared_self = without_self.pop("freeze_sha256", None)
        computed_self = canonical_sha256(without_self)
        expected_fields = {
            "call_budget_per_method_block": 10,
            "generation_count": 3,
            "infrastructure_retries": 2,
            "maximum_concurrency": 50,
            "population_size": 6,
            "schema_invalid_retries": 1,
            "validation_finalists": 3,
            "planned_calls": {"evolution": 180, "final": 160, "total": 400, "validation": 60},
        }
        field_mismatches = {key: {"expected": value, "actual": manifest.get(key)} for key, value in expected_fields.items() if manifest.get(key) != value}
        self.check("freeze.file_hashes", not mismatches, {"files_checked": len(declared), "mismatches": mismatches})
        self.check("freeze.self_hash", declared_self == computed_self, {"declared": declared_self, "computed": computed_self})
        self.check("freeze.protocol_fields", not field_mismatches, {"mismatches": field_mismatches})
        return {
            "freeze_sha256": declared_self,
            "files_checked": len(declared),
            "file_mismatches": mismatches,
            "field_mismatches": field_mismatches,
            "verified": not mismatches and declared_self == computed_self and not field_mismatches,
        }

    def audit_run(self, spec: tuple[object, ...]) -> tuple[dict[str, object], list[dict[str, object]]]:
        name, relative, manifest_name, expected_jobs, expected_phase, expected_blocks = spec
        base = self.root / str(relative)
        manifest = load_json(base / "manifests" / str(manifest_name))
        jobs = manifest.get("jobs", [])
        job_ids = [job.get("job_id") for job in jobs]
        expected_set = set(job_ids)
        job_by_id = {str(job.get("job_id")): job for job in jobs}
        expected_timeout = AMENDMENT_TIMEOUT_SECONDS if name == "final-vote10-generalist" else REGISTERED_TIMEOUT_SECONDS
        preflight = load_json(base / "runner" / "preflight.json")
        binary_hash = str(preflight.get("binary_sha256", ""))
        preflight_errors = [] if binary_hash == EXPECTED_BINARY_SHA256 else [
            {"field": "binary_sha256", "expected": EXPECTED_BINARY_SHA256, "actual": binary_hash}
        ]
        ledger = [json.loads(line) for line in (base / "runner" / "attempts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        attempts = [event for event in ledger if event.get("event_type") == "attempt"]
        closes = [event for event in ledger if event.get("event_type") == "job_closed"]
        attempts_by_job: dict[str, list[dict[str, object]]] = defaultdict(list)
        closes_by_job: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event in attempts:
            attempts_by_job[str(event.get("job_id"))].append(event)
        for event in closes:
            closes_by_job[str(event.get("job_id"))].append(event)
        result_missing = []
        result_invalid = []
        execution_contract_errors = []
        response_hash_errors = []
        request_hash_errors = []
        duration_errors = []
        for job_id in job_ids:
            job_dir = base / "runner" / "jobs" / str(job_id)
            result_path = job_dir / "result.json"
            if not result_path.is_file():
                result_missing.append(job_id)
            else:
                result = load_json(result_path)
                if result.get("job_id") != job_id or result.get("outcome") != "valid_output" or result.get("attempt_count") != len(attempts_by_job[str(job_id)]):
                    result_invalid.append(job_id)
            attempt_dirs = sorted(path.name for path in job_dir.glob("attempt-*") if path.is_dir())
            attempt_dir = job_dir / "attempt-01"
            command_path = attempt_dir / "command.json"
            last_message_path = attempt_dir / "last_message.txt"
            job_attempts = attempts_by_job[str(job_id)]
            if (
                attempt_dirs != ["attempt-01"]
                or len(job_attempts) != 1
                or job_attempts[0].get("attempt_number") != 1
                or job_attempts[0].get("artifact_relpath") != f"jobs/{job_id}/attempt-01"
                or not command_path.is_file()
                or not last_message_path.is_file()
            ):
                execution_contract_errors.append(str(job_id))
                continue
            try:
                command = load_json(command_path)
            except (OSError, json.JSONDecodeError):
                execution_contract_errors.append(str(job_id))
                continue
            if command != frozen_public_command():
                execution_contract_errors.append(str(job_id))
            if file_sha256(last_message_path) != job_attempts[0].get("response_sha256"):
                response_hash_errors.append(str(job_id))
            job = job_by_id[str(job_id)]
            expected_request = expected_request_sha256(job, binary_hash, expected_timeout)
            if job_attempts[0].get("request_sha256") != expected_request:
                request_hash_errors.append(str(job_id))
            duration_ms = job_attempts[0].get("duration_ms")
            if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
                duration_errors.append(str(job_id))
        status_counts = sorted_counts(event.get("status") for event in attempts)
        outcome_counts = sorted_counts(event.get("outcome") for event in closes)
        retry_jobs = sorted(job_id for job_id, values in attempts_by_job.items() if len(values) > 1)
        unstable_requests = sorted(job_id for job_id, values in attempts_by_job.items() if len({value.get("request_sha256") for value in values}) > 1)
        ledger_ids = set(attempts_by_job) | set(closes_by_job)
        exactly_terminal = all(len(closes_by_job[str(job_id)]) == 1 for job_id in job_ids)
        operational = load_json(base / "runner" / "operational_summary.json")
        observed_concurrency, concurrency_errors = peak_concurrency(attempts)
        valid_durations = [int(event["duration_ms"]) for event in attempts if isinstance(event.get("duration_ms"), int) and not isinstance(event.get("duration_ms"), bool) and int(event["duration_ms"]) >= 0]
        max_attempt_duration_ms = max(valid_durations, default=None)
        timed_out_attempts = sorted(str(event.get("job_id")) for event in attempts if event.get("timed_out") is True)
        predictions = load_json(base / "predictions.json")
        records = predictions.get("records", [])
        records_by_job = Counter(record.get("job_id") for record in records)
        prediction_identity_errors = []
        for job_id, job in job_by_id.items():
            job_records = [record for record in records if record.get("job_id") == job_id]
            expected_cases = set(job.get("expected_case_ids", []))
            actual_cases = [record.get("case_id") for record in job_records]
            metadata_fields = ("block_id", "call_index", "genome_id", "method", "phase", "role")
            if (
                len(actual_cases) != len(expected_cases)
                or set(actual_cases) != expected_cases
                or len(set(actual_cases)) != len(actual_cases)
                or any(record.get(field) != job.get(field) for record in job_records for field in metadata_fields)
                or any(record.get("format_valid") is not True for record in job_records)
            ):
                prediction_identity_errors.append(job_id)
        expected_records = int(expected_jobs) * 12
        prediction_ids = set(records_by_job)
        prediction_hash_ok = predictions.get("records_sha256") == canonical_sha256(records)
        if name in {"final-vote10", "final-vote10-generalist"}:
            planned_methods = {"Vote10"}
        else:
            population = load_json(self.root / METHOD_SOURCES[str(name)])
            planned_methods = {genome.get("genome_id") for genome in population.get("genomes", [])}
        manifest_methods = {job.get("method") for job in jobs}
        method_block_counts = Counter((str(job.get("method")), str(job.get("block_id"))) for job in jobs)
        dimensions_ok = (
            set(job.get("phase") for job in jobs) == {expected_phase}
            and set(job.get("block_id") for job in jobs) == set(expected_blocks)
            and manifest_methods == planned_methods
            and set(method_block_counts.values()) == {10}
            and all(isinstance(job.get("call_index"), int) and job.get("call_index") >= 1 for job in jobs)
        )
        valid = (
            len(jobs) == expected_jobs
            and len(expected_set) == expected_jobs
            and ledger_ids == expected_set
            and len(attempts) == expected_jobs
            and status_counts == {"valid_output": expected_jobs}
            and len(closes) == expected_jobs
            and outcome_counts == {"valid_output": expected_jobs}
            and exactly_terminal
            and not result_missing
            and not result_invalid
            and not execution_contract_errors
            and not response_hash_errors
            and not request_hash_errors
            and not duration_errors
            and not timed_out_attempts
            and not preflight_errors
            and not unstable_requests
            and not concurrency_errors
            and observed_concurrency <= 50
            and len(records) == expected_records
            and predictions.get("job_count") == expected_jobs
            and prediction_ids == expected_set
            and set(records_by_job.values()) == {12}
            and not prediction_identity_errors
            and prediction_hash_ok
            and dimensions_ok
            and operational.get("selected_jobs") == expected_jobs
            and operational.get("valid_jobs") == expected_jobs
            and operational.get("failed_jobs") == 0
            and operational.get("open_jobs") == 0
        )
        contract_error_ids = set(execution_contract_errors) | set(response_hash_errors) | set(request_hash_errors) | set(duration_errors)
        verified_jobs = 0 if preflight_errors else int(expected_jobs) - len(contract_error_ids)
        details = {
            "planned_jobs": expected_jobs,
            "manifest_jobs": len(jobs),
            "unique_jobs": len(expected_set),
            "job_identity_sha256": canonical_sha256(sorted(job_ids)),
            "attempts": len(attempts),
            "attempt_statuses": status_counts,
            "retry_jobs": retry_jobs,
            "schema_invalid_attempts": status_counts.get("schema_invalid", 0),
            "infrastructure_failures": status_counts.get("infrastructure_failure", 0),
            "protocol_violations": status_counts.get("protocol_violation", 0),
            "terminal_outcomes": outcome_counts,
            "terminal_results": expected_jobs - len(result_missing) - len(result_invalid),
            "max_observed_concurrency": observed_concurrency,
            "concurrency_source": "half-open overlap sweep of attempt started_at/finished_at timestamps",
            "concurrency_errors": concurrency_errors,
            "operational_summary_max_active_processes": operational.get("max_active_processes"),
            "prediction_records": len(records),
            "prediction_records_sha256": predictions.get("records_sha256"),
            "phase_counts": sorted_counts(job.get("phase") for job in jobs),
            "method_counts": sorted_counts(job.get("method") for job in jobs),
            "planned_methods": sorted(planned_methods),
            "method_block_counts": {f"{method} / {block}": count for (method, block), count in sorted(method_block_counts.items())},
            "block_counts": sorted_counts(job.get("block_id") for job in jobs),
            "role_counts": sorted_counts(job.get("role") for job in jobs),
            "missing_results": result_missing,
            "invalid_results": result_invalid,
            "execution_contract": {
                "verified_jobs": verified_jobs,
                "expected_model": "gpt-5.6-luna",
                "expected_reasoning_effort": "low",
                "expected_sandbox": "read-only",
                "expected_ephemeral": True,
                "expected_timeout_seconds": expected_timeout,
                "expected_binary_sha256": EXPECTED_BINARY_SHA256,
                "observed_binary_sha256": binary_hash,
                "disabled_features": list(DISABLED_FEATURES),
                "preflight_errors": preflight_errors,
                "artifact_or_command_errors": sorted(execution_contract_errors),
                "last_message_sha256_errors": sorted(response_hash_errors),
                "request_sha256_errors": sorted(request_hash_errors),
                "duration_errors": sorted(duration_errors),
                "timed_out_attempts": timed_out_attempts,
                "max_attempt_duration_ms": max_attempt_duration_ms,
            },
            "ledger_identity_mismatch": sorted((ledger_ids ^ expected_set)),
            "prediction_identity_mismatch": sorted((prediction_ids ^ expected_set)),
            "prediction_record_identity_errors": sorted(prediction_identity_errors),
            "request_hash_changed_on_retry": unstable_requests,
        }
        self.check(f"run.{name}", valid, details)
        return details, jobs

    def audit_amendment(self, run_results: dict[str, dict[str, object]]) -> dict[str, object]:
        chronology_path = self.root / "AMENDMENT-01.md"
        chronology = chronology_path.read_text(encoding="utf-8") if chronology_path.is_file() else ""
        chronology_markers = (
            "post-unblinding implementation correction",
            "The registered run used 400 calls.",
            "The correction adds 40 calls",
            "total recorded experimental execution to 440 calls",
        )
        chronology_ok = chronology_path.is_file() and all(marker in chronology for marker in chronology_markers)
        chronology_detail = {
            "path": "AMENDMENT-01.md",
            "sha256": file_sha256(chronology_path) if chronology_path.is_file() else None,
            "required_chronology_markers_present": chronology_ok,
        }
        self.check("amendment.chronology", chronology_ok, chronology_detail)

        registered_names = (
            "generation-00", "generation-01", "generation-02", "validation",
            "final-structured", "final-vote10",
        )
        correction_contract = run_results["final-vote10-generalist"]["execution_contract"]
        observed_max_ms = correction_contract.get("max_attempt_duration_ms")
        timeout_markers = (
            "300-second subprocess ceiling",
            "600-second default",
            "82.308 seconds",
            "No correction call timed out",
        )
        timeout_disclosure_ok = all(marker in chronology for marker in timeout_markers)
        registered_identity_ok = all(
            run_results[name]["execution_contract"].get("expected_timeout_seconds") == REGISTERED_TIMEOUT_SECONDS
            and not run_results[name]["execution_contract"].get("request_sha256_errors")
            for name in registered_names
        )
        correction_identity_ok = (
            correction_contract.get("expected_timeout_seconds") == AMENDMENT_TIMEOUT_SECONDS
            and not correction_contract.get("request_sha256_errors")
        )
        timeout_deviation_ok = (
            timeout_disclosure_ok
            and registered_identity_ok
            and correction_identity_ok
            and observed_max_ms == 82_308
            and observed_max_ms < REGISTERED_TIMEOUT_SECONDS * 1000
            and not correction_contract.get("timed_out_attempts")
        )
        timeout_detail = {
            "registered_calls": 400,
            "registered_timeout_seconds": REGISTERED_TIMEOUT_SECONDS,
            "registered_request_identities_verified": registered_identity_ok,
            "correction_calls": 40,
            "correction_timeout_seconds": AMENDMENT_TIMEOUT_SECONDS,
            "correction_request_identities_verified": correction_identity_ok,
            "correction_max_attempt_duration_ms": observed_max_ms,
            "correction_timed_out_attempts": correction_contract.get("timed_out_attempts"),
            "all_correction_calls_finished_below_registered_ceiling": isinstance(observed_max_ms, int) and observed_max_ms < REGISTERED_TIMEOUT_SECONDS * 1000,
            "required_disclosure_markers_present": timeout_disclosure_ok,
            "verified": timeout_deviation_ok,
        }
        self.check("amendment.timeout_deviation", timeout_deviation_ok, timeout_detail)

        base = self.root / "runs/final/vote10-generalist"
        manifest = load_json(base / "manifests/vote10-generalist.json")
        summary = load_json(base / "run_summary.json")
        lenses = load_json(self.root / "prompts/LENSES.json")
        frozen_lens = lenses.get("worker", {}).get("generalist")
        frozen_lens_hash = sha256_bytes(str(frozen_lens).encode("utf-8"))
        common_prefix_path = self.root / "prompts/COMMON_PREFIX.txt"
        common_prefix = common_prefix_path.read_text(encoding="utf-8")
        jobs = manifest.get("jobs", [])
        expected_prompt_paths = {base / "prompts" / f"{job.get('job_id')}.txt" for job in jobs}
        actual_prompt_paths = set((base / "prompts").glob("*.txt"))
        prompt_contract_errors = []
        for job in jobs:
            job_id = str(job.get("job_id"))
            manifest_prompt = job.get("prompt")
            prompt_path = base / "prompts" / f"{job_id}.txt"
            prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else None
            try:
                manifest_lens = str(manifest_prompt).split("\nLENS\n", 1)[1].split("\n\nTASK BLOCK JSON\n", 1)[0]
                file_lens = str(prompt_text).split("\nLENS\n", 1)[1].split("\n\nTASK BLOCK JSON\n", 1)[0]
            except IndexError:
                manifest_lens = file_lens = None
            if (
                prompt_text != manifest_prompt
                or manifest_lens != frozen_lens
                or file_lens != frozen_lens
                or not str(manifest_prompt).startswith(common_prefix.rstrip("\n") + "\n\nROLE\n")
            ):
                prompt_contract_errors.append(job_id)
        predictions = load_json(base / "predictions.json")
        contract_ok = (
            len(jobs) == 40
            and actual_prompt_paths == expected_prompt_paths
            and not prompt_contract_errors
            and summary.get("amendment") == "AMENDMENT-01.md"
            and summary.get("planned_calls") == 40
            and summary.get("phase") == "final-amendment-01"
            and summary.get("worker_lens") == "generalist"
            and summary.get("generalist_lens_sha256") == frozen_lens_hash
            and summary.get("common_prefix_sha256") == file_sha256(common_prefix_path)
            and summary.get("prediction_records_sha256") == predictions.get("records_sha256")
        )
        contract_detail = {
            "jobs": len(jobs),
            "prompt_files": len(actual_prompt_paths),
            "frozen_lens_source": "prompts/LENSES.json worker.generalist",
            "frozen_generalist_lens_sha256": frozen_lens_hash,
            "declared_generalist_lens_sha256": summary.get("generalist_lens_sha256"),
            "common_prefix_sha256": file_sha256(common_prefix_path),
            "prompt_set_mismatch": sorted(path.relative_to(self.root).as_posix() for path in actual_prompt_paths ^ expected_prompt_paths),
            "prompt_contract_errors": sorted(prompt_contract_errors),
            "verified": contract_ok,
        }
        self.check("amendment.generalist_prompt_contract", contract_ok, contract_detail)
        return {
            "chronology": chronology_detail,
            "timeout_deviation": timeout_detail,
            "generalist_prompt_contract": contract_detail,
        }

    def audit_scores(self) -> dict[str, object]:
        results = {}
        for name, prediction_rel, summary_rel, expected_cases in SCORE_TARGETS:
            prediction_path = self.root / prediction_rel
            predictions = load_json(prediction_path)
            summary = load_json(self.root / summary_rel)
            records = predictions.get("records", [])
            methods = summary.get("methods", {})
            ok = (
                summary.get("inputs", {}).get("predictions_sha256") == file_sha256(prediction_path)
                and summary.get("inputs", {}).get("completed_jobs") == len(records)
                and summary.get("n_cases") == expected_cases
                and all(value.get("malformed_calls") == 0 and value.get("completed_calls") == value.get("calls") for value in methods.values())
            )
            results[name] = {
                "prediction_records": len(records),
                "prediction_file_sha256": file_sha256(prediction_path),
                "case_count": summary.get("n_cases"),
                "method_calls": {method: value.get("calls") for method, value in sorted(methods.items())},
                "malformed_calls": sum(value.get("malformed_calls", 0) for value in methods.values()),
                "verified": ok,
            }
            self.check(f"score.{name}", ok, results[name])
        merges = (
            ("final-primary", "runs/final/predictions.json", ("runs/final/structured/predictions.json", "runs/final/vote10-generalist/predictions.json")),
            ("final-diversified-vote", "runs/final/predictions-diversified-vote.json", ("runs/final/structured/predictions.json", "runs/final/vote10/predictions.json")),
        )
        for name, merged_rel, expected_sources in merges:
            merged = load_json(self.root / merged_rel)
            declared_sources = merged.get("sources", [])
            expected_documents = [load_json(self.root / relative) for relative in expected_sources]
            expected_records = [record for document in expected_documents for record in document.get("records", [])]
            source_errors = []
            if len(declared_sources) != len(expected_sources):
                source_errors.append("source count")
            else:
                for declared, relative, document in zip(declared_sources, expected_sources, expected_documents):
                    declared_path = str(declared.get("path", ""))
                    if not (declared_path == relative or declared_path.endswith("/" + relative)):
                        source_errors.append(f"path:{relative}")
                    if declared.get("sha256") != file_sha256(self.root / relative):
                        source_errors.append(f"sha256:{relative}")
                    if declared.get("record_count") != len(document.get("records", [])):
                        source_errors.append(f"record_count:{relative}")
            merged_ok = (
                not source_errors
                and merged.get("records") == expected_records
                and merged.get("record_count") == 1920
                and merged.get("records_sha256") == canonical_sha256(expected_records)
            )
            detail = {
                "merged_file": merged_rel,
                "expected_sources": list(expected_sources),
                "source_record_counts": [len(document.get("records", [])) for document in expected_documents],
                "record_count": len(merged.get("records", [])),
                "source_errors": source_errors,
                "verified": merged_ok,
            }
            self.check(f"score.{name}.merge", merged_ok, detail)
            results[f"{name}_merge"] = detail
        return results

    def privacy_files(self) -> tuple[list[Path], list[str]]:
        repo = Path(subprocess.check_output(
            ("git", "-C", str(self.root), "rev-parse", "--show-toplevel"),
            text=True,
        ).strip())
        relative_root = self.root.relative_to(repo).as_posix()
        raw = subprocess.check_output(
            ("git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", relative_root)
        )
        listed = [repo / value.decode("utf-8") for value in raw.split(b"\0") if value]
        missing = sorted(path.relative_to(repo).as_posix() for path in listed if not path.is_file())
        return sorted(path for path in listed if path.is_file()), missing

    def audit_privacy(self) -> dict[str, object]:
        findings = []
        files, missing = self.privacy_files()
        for path in files:
            relative = path.relative_to(self.root).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            for kind, pattern in (("absolute_home_path", HOME_PATH), ("secret_token", SECRET_TEXT), ("thread_identifier", THREAD_TEXT)):
                if pattern.search(text):
                    findings.append({"path": relative, "kind": kind})
            if path.suffix in {".json", ".jsonl"}:
                documents = []
                try:
                    documents = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(text)]
                except json.JSONDecodeError:
                    findings.append({"path": relative, "kind": "invalid_json"})
                stack = list(documents)
                while stack:
                    value = stack.pop()
                    if isinstance(value, dict):
                        for key, child in value.items():
                            if SECRET_KEY.search(str(key)) and child not in (None, "", [], {}):
                                findings.append({"path": relative, "kind": "secret_field", "key": str(key)})
                            if THREAD_KEY.search(str(key)) and child not in (None, "", [], {}):
                                findings.append({"path": relative, "kind": "thread_identifier_field", "key": str(key)})
                            stack.append(child)
                    elif isinstance(value, list):
                        stack.extend(value)
        findings = [dict(item) for item in {json.dumps(item, sort_keys=True): item for item in findings}.values()]
        result = {
            "scope": "exact Git-visible release set under the experiment root, enumerated by git ls-files --cached --others --exclude-standard",
            "files_scanned": len(files),
            "missing_git_visible_files": missing,
            "findings": sorted(findings, key=lambda item: (item["path"], item["kind"])),
            "passed": not findings and not missing,
        }
        self.check("privacy.git_visible_release_set", not findings and not missing, result)
        return result

    def run(self) -> dict[str, object]:
        freeze = self.audit_freeze()
        run_results = {}
        all_jobs = []
        for spec in RUNS:
            details, jobs = self.audit_run(spec)
            run_results[str(spec[0])] = details
            all_jobs.extend(jobs)
        execution_errors = {
            name: value["execution_contract"]
            for name, value in run_results.items()
            if value["execution_contract"]["verified_jobs"] != value["planned_jobs"]
        }
        execution_verified = sum(int(value["execution_contract"]["verified_jobs"]) for value in run_results.values())
        self.check("execution.contract", execution_verified == 440 and not execution_errors, {
            "verified_jobs": execution_verified,
            "expected_jobs": 440,
            "registered_jobs": 400,
            "amendment_01_correction_jobs": 40,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "ephemeral": True,
            "sandbox": "read-only",
            "registered_timeout_seconds": REGISTERED_TIMEOUT_SECONDS,
            "amendment_01_timeout_seconds": AMENDMENT_TIMEOUT_SECONDS,
            "amendment_01_timeout_deviation": "disclosed and separately audited",
            "disabled_features": list(DISABLED_FEATURES),
            "violations": execution_errors,
            "response_integrity": "SHA-256(last_message.txt) equals attempt ledger response_sha256",
        })
        all_ids = [job.get("job_id") for job in all_jobs]
        aggregate = {
            "registered_plan": EXPECTED_PLAN,
            "registered_observed": {
                "evolution": sum(int(run_results[name]["manifest_jobs"]) for name in ("generation-00", "generation-01", "generation-02")),
                "validation": int(run_results["validation"]["manifest_jobs"]),
                "final_structured": int(run_results["final-structured"]["manifest_jobs"]),
                "final_vote10": int(run_results["final-vote10"]["manifest_jobs"]),
                "final": int(run_results["final-structured"]["manifest_jobs"]) + int(run_results["final-vote10"]["manifest_jobs"]),
                "total": len(all_jobs) - int(run_results["final-vote10-generalist"]["manifest_jobs"]),
            },
            "amendment_01_correction": {
                "vote10_generalist": int(run_results["final-vote10-generalist"]["manifest_jobs"]),
                "total": int(run_results["final-vote10-generalist"]["manifest_jobs"]),
            },
            "registered_jobs": 400,
            "correction_jobs": 40,
            "total_recorded_calls": len(all_jobs),
            "jobs": len(all_jobs),
            "unique_jobs": len(set(all_ids)),
            "job_identity_sha256": canonical_sha256(sorted(all_ids)),
            "attempts": sum(int(value["attempts"]) for value in run_results.values()),
            "retries": sum(len(value["retry_jobs"]) for value in run_results.values()),
            "schema_invalid_attempts": sum(int(value["schema_invalid_attempts"]) for value in run_results.values()),
            "infrastructure_failures": sum(int(value["infrastructure_failures"]) for value in run_results.values()),
            "protocol_violations": sum(int(value["protocol_violations"]) for value in run_results.values()),
            "terminal_valid_jobs": sum(int(value["terminal_outcomes"].get("valid_output", 0)) for value in run_results.values()),
            "prediction_records": sum(int(value["prediction_records"]) for value in run_results.values()),
            "max_observed_concurrency": max(int(value["max_observed_concurrency"]) for value in run_results.values()),
        }
        aggregate_ok = (
            aggregate["registered_observed"] == EXPECTED_PLAN
            and aggregate["registered_jobs"] == EXPECTED_PLAN["total"]
            and aggregate["correction_jobs"] == 40
            and aggregate["total_recorded_calls"] == 440
            and aggregate["jobs"] == 440
            and aggregate["unique_jobs"] == 440
            and aggregate["attempts"] == 440
            and aggregate["terminal_valid_jobs"] == 440
            and aggregate["prediction_records"] == 5280
            and aggregate["max_observed_concurrency"] <= 50
        )
        self.check("plan.aggregate", aggregate_ok, aggregate)
        amendment = self.audit_amendment(run_results)
        scores = self.audit_scores()
        privacy = self.audit_privacy()
        passed = all(bool(check["passed"]) for check in self.checks)
        return {
            "schema_version": "experiment-03-release-audit-v1",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed" if passed else "failed",
            "freeze": freeze,
            "amendment_01": amendment,
            "collection": {"aggregate": aggregate, "runs": run_results},
            "scores": scores,
            "privacy": privacy,
            "checks": self.checks,
            "release_exclusions": [
                "runs/smoke/, runs/smoke-unsandboxed/, and runs/preflight/ (development/preflight activity outside the 400-call plan)",
                "runs/**/runner/jobs/**/{events.jsonl,process.json,stderr.txt,transport_result.json} (local process/session diagnostics excluded by .gitignore)",
                "runs/**/runner/.run.lock, __pycache__/, and *.py[cod] (ephemeral local state excluded by .gitignore)",
                "Sanitized command.json is Git-visible and may remain in the release.",
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=EXPERIMENT_DIR)
    parser.add_argument("--output", type=Path, default=Path("results/release-audit.json"))
    args = parser.parse_args()
    root = args.experiment_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        report = Audit(root).run()
    except (AssertionError, FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        print(f"audit could not complete: {exc}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": output.relative_to(root).as_posix(), "status": report["status"], "checks": len(report["checks"])}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
