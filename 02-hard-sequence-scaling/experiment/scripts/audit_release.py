#!/usr/bin/env python3
"""Audit Experiment 02 evidence before public release (standard library only)."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable


SCHEMA_VERSION = "experiment-02-release-audit-v1"
EXPECTED_METHODS = {"Direct expected", "Vote10", "Vote20", "Swarm10", "Tournament20"}
EXPECTED_REASONING = {"Light reasoning", "Medium reasoning"}
EXPECTED_BLOCKS = {"B01", "B02", "B03", "B04"}
PRIVATE_PATTERNS = (
    ("absolute user path", re.compile(r"/(?:Users|home)/[^/\s]+/")),
    ("internal task identifier", re.compile(r"\b(?:source_task|task_uuid|thread_uuid|codex_task_id)\b", re.I)),
    ("UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)),
    ("secret-like value", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
)


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, condition: bool, name: str, detail: str = "") -> None:
        self.checks.append({"status": "pass" if condition else "fail", "check": name, "detail": detail})

    def warn(self, name: str, detail: str) -> None:
        self.checks.append({"status": "warning", "check": name, "detail": detail})

    def report(self) -> dict[str, Any]:
        counts = Counter(row["status"] for row in self.checks)
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "pass" if counts["fail"] == 0 else "fail",
            "summary": {"passed": counts["pass"], "failed": counts["fail"], "warnings": counts["warning"]},
            "checks": self.checks,
        }


def load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as first:
        rows = []
        try:
            for line in text.splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError(f"not valid JSON or JSONL: {path}") from first
        return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def records(data: Any, keys: Iterable[str]) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def audit_run_manifest(audit: Audit, data: Any) -> None:
    calls = records(data, ("calls", "records", "items"))
    audit.check(len(calls) == 400, "planned call count", f"found {len(calls)}, expected 400")
    call_ids = [str(call.get("call_id")) for call in calls if isinstance(call, dict)]
    audit.check(len(call_ids) == len(set(call_ids)), "unique planned call IDs")
    blocks = {str(call.get("block_id")) for call in calls if isinstance(call, dict)}
    audit.check(blocks == EXPECTED_BLOCKS, "four frozen blocks", f"found {sorted(blocks)}")
    for call in calls:
        if not isinstance(call, dict):
            continue
        case_ids = call.get("case_ids", [])
        audit.check(len(case_ids) == 12 and len(set(map(str, case_ids))) == 12,
                    "12 unique cases per planned call", str(call.get("call_id")))
    condition_counts = Counter()
    architecture_counts = Counter()
    for call in calls:
        if not isinstance(call, dict):
            continue
        condition = str(call.get("condition_label", call.get("reasoning", ""))).lower()
        condition_counts[(str(call.get("block_id")), condition)] += 1
        architecture = str(call.get("architecture", ""))
        role = str(call.get("role", ""))
        architecture_counts[(str(call.get("block_id")), condition, architecture, role)] += 1
    audit.check(all(value == 50 for value in condition_counts.values()) and len(condition_counts) == 8,
                "50 calls per block and reasoning condition", str(dict(condition_counts)))
    expected_roles = {
        ("independent", "solver"): 20,
        ("swarm10", "proposer"): 5, ("swarm10", "critic"): 2,
        ("swarm10", "verifier"): 2, ("swarm10", "judge"): 1,
        ("tournament20", "explorer"): 8, ("tournament20", "breaker"): 4,
        ("tournament20", "verifier"): 4, ("tournament20", "synthesizer"): 2,
        ("tournament20", "red_team"): 1, ("tournament20", "judge"): 1,
    }
    exact_roles = True
    for block in EXPECTED_BLOCKS:
        for condition in ("light", "medium"):
            for (architecture, role), expected in expected_roles.items():
                exact_roles &= architecture_counts[(block, condition, architecture, role)] == expected
    audit.check(exact_roles and sum(architecture_counts.values()) == 400,
                "exact architecture and role call graph", str(dict(architecture_counts)))
    prior_roles = {
        ("independent", "solver"): (),
        ("swarm10", "proposer"): (), ("swarm10", "critic"): ("proposer",),
        ("swarm10", "verifier"): ("proposer", "critic"),
        ("swarm10", "judge"): ("proposer", "critic", "verifier"),
        ("tournament20", "explorer"): (), ("tournament20", "breaker"): ("explorer",),
        ("tournament20", "verifier"): ("explorer", "breaker"),
        ("tournament20", "synthesizer"): ("explorer", "breaker", "verifier"),
        ("tournament20", "red_team"): ("explorer", "breaker", "verifier", "synthesizer"),
        ("tournament20", "judge"): ("explorer", "breaker", "verifier", "synthesizer", "red_team"),
    }
    grouped_calls: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        if isinstance(call, dict):
            grouped_calls[(str(call.get("block_id")), str(call.get("condition_label")),
                           str(call.get("architecture")))].append(call)
    dependency_ok = True
    for group in grouped_calls.values():
        for call in group:
            roles = prior_roles.get((str(call.get("architecture")), str(call.get("role"))))
            expected_ids = {str(other.get("call_id")) for other in group if other.get("role") in (roles or ())}
            dependency_ok &= roles is not None and set(map(str, call.get("dependency_call_ids", []))) == expected_ids
    audit.check(dependency_ok, "exact frozen role dependency graph")


def audit_attempts(audit: Audit, attempts_data: Any, manifest_data: Any) -> None:
    events = records(attempts_data, ("events", "records", "attempts"))
    calls = records(manifest_data, ("calls", "records", "items"))
    expected = {str(call.get("call_id")) for call in calls if isinstance(call, dict)}
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    attempt_module = importlib.import_module("attempt_log")
    try:
        attempt_module.validate_events(events, expected)
    except Exception as exc:
        audit.check(False, "append-only attempt log passes strict lineage validation", str(exc))
    else:
        audit.check(True, "append-only attempt log passes strict lineage validation")
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if not isinstance(event, dict) or "call_id" not in event:
            continue
        destination = closes if event.get("event_type") == "call_closed" else attempts
        destination[str(event["call_id"])].append(event)
    audit.check(all(len(value) <= 1 for value in closes.values()), "at most one close event per planned call")
    derived_closed = {
        call_id for call_id in expected
        if len(closes.get(call_id, [])) == 1
        or any(row.get("status") in {"semantic_response", "malformed_output"} for row in attempts.get(call_id, []))
    }
    audit.check(derived_closed == expected, "every planned call has a terminal outcome",
                f"closed or substantively complete {len(derived_closed)}/{len(expected)}")
    interrupted_markers = sorted(call_id for call_id in derived_closed if not closes.get(call_id))
    if interrupted_markers:
        audit.warn("interrupted close-marker appends recovered from substantive attempts",
                   f"{len(interrupted_markers)} calls: {', '.join(interrupted_markers[:10])}")
    audit.check(not (set(attempts) | set(closes)) - expected, "no unplanned call events")
    substantive_count = sum(
        sum(row.get("status") in {"semantic_response", "malformed_output"} for row in attempts.get(call_id, []))
        for call_id in expected
    )
    exhausted_count = sum(
        len(attempts.get(call_id, [])) == 3
        and all(row.get("status") == "infrastructure_failure" for row in attempts.get(call_id, []))
        for call_id in expected
    )
    audit.check(substantive_count == len(expected), "exactly one substantive terminal response per planned call")
    audit.check(exhausted_count == 0, "zero infrastructure-exhausted call lineages")
    for call_id in sorted(expected):
        lineage = sorted(attempts.get(call_id, []), key=lambda row: int(row.get("attempt_number", 0)))
        audit.check(1 <= len(lineage) <= 3, "one to three attempts per call", call_id)
        numbers = [int(row.get("attempt_number", 0)) for row in lineage]
        audit.check(numbers == list(range(1, len(lineage) + 1)), "contiguous attempt numbering", call_id)
        request_hashes = {row.get("request_sha256") for row in lineage}
        prompt_hashes = {row.get("prompt_identity_sha256") for row in lineage}
        audit.check(len(request_hashes) <= 1 and None not in request_hashes,
                    "identical request hash across retries", call_id)
        audit.check(len(prompt_hashes) <= 1 and None not in prompt_hashes,
                    "identical prompt hash across retries", call_id)
        expected_prompt = next(
            (call.get("prompt_identity_sha256") for call in calls if str(call.get("call_id")) == call_id), None
        )
        audit.check(prompt_hashes == {expected_prompt}, "attempt prompt identity matches run manifest", call_id)
        if len(lineage) > 1:
            prior = [row.get("status") for row in lineage[:-1]]
            audit.check(all(status == "infrastructure_failure" for status in prior),
                        "retry only after infrastructure failure", call_id)
        substantive = [row for row in lineage if row.get("status") in {"semantic_response", "malformed_output"}]
        audit.check(len(substantive) <= 1, "at most one substantive attempt", call_id)


def audit_scored(audit: Audit, scored: dict[str, Any]) -> None:
    audit.check(scored.get("metadata", {}).get("collection_closed") is True,
                "scoring performed only after collection closed")
    tie = scored.get("metadata", {}).get("vote_tie_break", [])
    audit.check(len(tie) == 4 and "confidence" in " ".join(map(str, tie)).lower(), "frozen four-stage vote tie-break")
    audit.check(scored.get("metadata", {}).get("vote10_slots") == [f"S{i:02d}" for i in range(1, 11)],
                "Vote10 fixed S01-S10")
    audit.check(scored.get("metadata", {}).get("vote20_slots") == [f"S{i:02d}" for i in range(1, 21)],
                "Vote20 fixed S01-S20")
    cases = scored.get("cases", [])
    audit.check(len(cases) == 96, "96 case-reasoning score rows", f"found {len(cases)}")
    identities = {(str(case.get("reasoning")), str(case.get("case_id"))) for case in cases}
    audit.check(len(identities) == len(cases), "unique case-reasoning score rows")
    reasoning = {str(case.get("reasoning")) for case in cases}
    audit.check(reasoning == EXPECTED_REASONING, "public reasoning labels", f"found {sorted(reasoning)}")
    block_counts = Counter(str(case.get("block")) for case in cases)
    audit.check(block_counts == Counter({block: 24 for block in EXPECTED_BLOCKS}),
                "24 score rows per block", str(dict(block_counts)))
    derived = 0
    for case in cases:
        attempts = case.get("independent_attempts", [])
        slots = [row.get("slot") for row in attempts if isinstance(row, dict)]
        audit.check(slots == [f"S{i:02d}" for i in range(1, 21)], "20 ordered independent slots", str(case.get("case_id")))
        methods = set(case.get("methods", {}))
        audit.check(methods == EXPECTED_METHODS, "five derived methods per score row", str(case.get("case_id")))
        derived += len(methods)
    audit.check(derived == 480, "480 derived case-method-reasoning scores", f"found {derived}")
    reliability = scored.get("operational_reliability", {})
    required = {
        "planned_calls", "initial_attempts", "retry_attempts", "infrastructure_exhausted",
        "final_agent_message_present", "exit_code_counts", "timeouts", "raw_jsonl_present",
        "jsonl_parse_failures", "usage_telemetry_present", "usage_telemetry_missing",
        "cli_metadata_drift", "model_metadata_drift", "selected_concurrency", "missing_case_records",
    }
    audit.check(isinstance(reliability, dict) and required.issubset(reliability),
                "canonical operational reliability summary")
    if isinstance(reliability, dict):
        audit.check(reliability.get("planned_calls") == 400 and reliability.get("initial_attempts") == 400,
                    "400 planned and initial attempts")
        audit.check(reliability.get("infrastructure_exhausted") == 0,
                    "no exhausted infrastructure lineages")
        audit.check(reliability.get("raw_jsonl_present") is True and reliability.get("jsonl_parse_failures") == 0,
                    "raw JSONL present and parseable")
        audit.check(reliability.get("selected_concurrency") in {10, 20},
                    "selected frozen concurrency is 10 or 20")
        audit.check(reliability.get("load_gate_evidence_available") is True and
                    isinstance(reliability.get("load_gate_evidence"), dict),
                    "frozen concurrency load-gate evidence preserved")
        audit.check(set(reliability.get("by_block", {})) == EXPECTED_BLOCKS and
                    set(reliability.get("by_condition", {})) == EXPECTED_REASONING,
                    "operational reliability reported by block and condition")
        audit.check(all("missing_case_records" in row for row in reliability.get("by_condition", {}).values()),
                    "missing-case counts reported by condition")
        audit.check(all(reliability.get(key, 0) == 0 for key in (
            "cli_metadata_drift", "model_metadata_drift", "reasoning_metadata_drift",
            "prompt_identity_drift", "session_resume_count",
        )), "no CLI/model/reasoning/prompt/session drift")


def _close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def audit_analysis(audit: Audit, analysis: dict[str, Any], scored: dict[str, Any]) -> None:
    bootstrap = analysis.get("bootstrap", {})
    audit.check(int(bootstrap.get("replicates", 0)) >= 50_000, "at least 50,000 bootstrap replicates")
    audit.check(isinstance(bootstrap.get("seed"), int), "published bootstrap seed")
    audit.check(isinstance(bootstrap.get("derived_seeds"), dict) and
                bootstrap.get("quantile_probabilities") == {"ci95": [0.025, 0.975], "ci90": [0.05, 0.95]},
                "derived bootstrap seeds and interval quantiles published")
    methods = analysis.get("methods", [])
    audit.check(len(methods) == 10, "ten method-by-reasoning summaries", f"found {len(methods)}")
    scored_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for case in scored.get("cases", []):
        for method, result in case.get("methods", {}).items():
            scored_values[(str(case.get("reasoning")), method)].append(float(result["exact"]))
    for summary in methods:
        key = (str(summary.get("reasoning")), str(summary.get("method")))
        values = scored_values.get(key, [])
        estimate = summary.get("exact_accuracy", {}).get("estimate")
        audit.check(bool(values) and estimate is not None and _close(float(estimate), sum(values) / len(values)),
                    "analysis exact estimate matches scored cases", "/".join(key))
        for metric in ("exact_accuracy", "term_accuracy", "format_rate"):
            item = summary.get(metric)
            audit.check(isinstance(item, dict) and len(item.get("ci95", [])) == 2,
                        "95% method interval present", f"{'/'.join(key)}/{metric}")
    primary = analysis.get("primary")
    audit.check(isinstance(primary, dict), "primary contrast present")
    if isinstance(primary, dict):
        audit.check(primary.get("left") == "Medium reasoning Vote20" and
                    primary.get("right") == "Medium reasoning Tournament20",
                    "primary contrast identity")
        audit.check(len(primary.get("ci95", [])) == 2 and len(primary.get("ci90", [])) == 2,
                    "primary 95% and 90% intervals")
        audit.check(primary.get("mcnemar", {}).get("test") == "exact two-sided McNemar",
                    "primary exact McNemar")
        sensitivity = primary.get("block_sensitivity", {})
        audit.check(set(sensitivity.get("block_effects", {})) == EXPECTED_BLOCKS,
                    "primary block sensitivity includes all blocks")
        audit.check("block_sensitive" in sensitivity and len(sensitivity.get("whole_block_ci95", [])) == 2,
                    "whole-block and sensitivity flag present")
    secondary = analysis.get("confirmatory_secondary", [])
    audit.check(len(secondary) == 11, "complete 11-comparison confirmatory family", f"found {len(secondary)}")
    audit.check({row.get("id") for row in secondary} == {f"S{i:02d}" for i in range(1, 12)},
                "stable secondary comparison IDs")
    audit.check(all("raw_p" in row and "holm_adjusted_p" in row for row in secondary),
                "raw and Holm-adjusted secondary p-values")
    audit.check(analysis.get("operational_reliability") == scored.get("operational_reliability"),
                "analysis preserves operational reliability summary")


def audit_provenance(audit: Audit, scored: dict[str, Any], paths: dict[str, Path]) -> None:
    provenance = scored.get("provenance", {})
    mapping = {
        "results_sha256": "attempts",
        "run_manifest_sha256": "manifest",
        "answers_sha256": "answers",
    }
    for field, path_key in mapping.items():
        if path_key not in paths:
            continue
        expected = provenance.get(field)
        actual = sha256(paths[path_key])
        audit.check(expected == actual, f"provenance hash {field}", f"expected {expected}, actual {actual}")


def audit_freeze(audit: Audit, freeze: Any, experiment: Path) -> None:
    pairs: list[tuple[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            path_value = value.get("path", value.get("file"))
            hash_value = value.get("sha256", value.get("hash"))
            if isinstance(path_value, str) and isinstance(hash_value, str) and re.fullmatch(r"[0-9a-f]{64}", hash_value):
                pairs.append((path_value, hash_value))
            for key, child in value.items():
                if isinstance(child, str) and re.fullmatch(r"[0-9a-f]{64}", child) and isinstance(key, str) and ("/" in key or "." in key):
                    pairs.append((key, child))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(freeze)
    if isinstance(freeze, dict) and isinstance(freeze.get("immutable_files"), dict):
        for relative, record in freeze["immutable_files"].items():
            if isinstance(relative, str) and isinstance(record, dict):
                digest = record.get("sha256")
                if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                    pairs.append((relative, digest))
    audit.check(bool(pairs), "freeze manifest contains file hashes", f"found {len(pairs)} path/hash entries")
    checked: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, expected in pairs:
        candidate = Path(relative)
        if not candidate.is_absolute():
            candidate = experiment / candidate
        if not candidate.is_file():
            missing.append(relative)
            continue
        checked.append(relative)
        if sha256(candidate) != expected:
            mismatched.append(relative)
    audit.check(not missing, "every frozen file still exists", ", ".join(missing))
    audit.check(not mismatched, "frozen file hashes still match", ", ".join(mismatched))
    if isinstance(freeze, dict):
        copied = dict(freeze)
        self_hash = copied.pop("freeze_manifest_sha256", None)
        audit.check(self_hash == hashlib.sha256(
            json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(), "freeze manifest self-hash")
        immutable = freeze.get("immutable_files")
        immutable_hash = freeze.get("immutable_set_sha256")
        audit.check(isinstance(immutable, dict) and immutable_hash == hashlib.sha256(
            json.dumps(immutable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(), "freeze immutable-set hash")
    required_fragments = (
        "PROTOCOL.md", "ANALYSIS_PLAN.md", "CALIBRATION_PLAN.md",
        "run_codex_cli.py", "run_manifest.py", "attempt_log.py", "build_packets.py",
        "validate_outputs.py", "score_results.py", "analyze_results.py",
        "evaluate_calibration.py", "prepare_gate_reports.py", "audit_release.py",
        "SCHEMAS.json", "ROLE_CATALOG.json",
        "benchmark/manifest.json",
    )
    audit.check(all(any(path.endswith(fragment) for path in checked) for fragment in required_fragments),
                "core protocol, schema, scoring, and analysis files frozen", f"verified {len(checked)} files")


def audit_recomputation(audit: Audit, paths: dict[str, Path], scored: dict[str, Any], analysis: dict[str, Any]) -> None:
    """Recompute scoring and statistics from raw evidence and compare exactly."""
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    score_module = importlib.import_module("score_results")
    analysis_module = importlib.import_module("analyze_results")
    score_args = SimpleNamespace(
        results=str(paths["attempts"]),
        answers=str(paths["answers"]),
        manifest=str(paths["manifest"]),
        case_manifest=str(paths["case_manifest"]),
        collection_closed=str(paths["collection_closed"]),
        execution_metadata=None,
        allow_incomplete=False,
    )
    recomputed_scored = score_module.run_score(score_args)
    audit.check(
        json.dumps(recomputed_scored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == json.dumps(scored, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "published scored results exactly recompute from raw attempts and hidden truth",
    )


def audit_attempt_artifacts(
    audit: Audit, attempts_data: Any, attempts_path: Path, collection_closed_path: Path
) -> None:
    """Bind every append-only attempt event to the exact provider JSONL bytes."""
    artifact_manifest_path = attempts_path.parent / "attempt_artifacts.json"
    audit.check(artifact_manifest_path.is_file(), "attempt artifact manifest exists", str(artifact_manifest_path))
    if not artifact_manifest_path.is_file():
        return
    artifact_manifest = load_json_or_jsonl(artifact_manifest_path)
    if not isinstance(artifact_manifest, dict):
        audit.check(False, "attempt artifact manifest is a JSON object")
        return
    artifacts = artifact_manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        audit.check(False, "attempt artifact manifest contains artifact records")
        return
    canonical = json.dumps(artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    audit.check(
        artifact_manifest.get("artifact_set_sha256") == hashlib.sha256(canonical).hexdigest(),
        "attempt artifact-set hash is valid",
    )
    missing_or_changed: list[str] = []
    for relative, record in artifacts.items():
        path = (attempts_path.parent / relative).resolve()
        try:
            path.relative_to(attempts_path.parent.resolve())
        except ValueError:
            missing_or_changed.append(f"unsafe:{relative}")
            continue
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or sha256(path) != record.get("sha256")
        ):
            missing_or_changed.append(relative)
    audit.check(not missing_or_changed, "all raw attempt artifacts match their hashes", "; ".join(missing_or_changed[:20]))
    attempt_events = [
        event for event in records(attempts_data, ("events", "records", "attempts"))
        if isinstance(event, dict) and event.get("event_type") == "attempt"
    ]
    linked = True
    for event in attempt_events:
        relative = event.get("artifact_relpath")
        if not isinstance(relative, str):
            linked = False
            continue
        expected = {
            f"{relative}/events.jsonl": (event.get("raw_events_sha256"), event.get("raw_events_bytes")),
            f"{relative}/stderr.txt": (event.get("stderr_sha256"), event.get("stderr_bytes")),
        }
        if event.get("last_message_bytes", 0):
            expected[f"{relative}/last_message.txt"] = (
                event.get("last_message_sha256"), event.get("last_message_bytes")
            )
        for path, (digest, size) in expected.items():
            record = artifacts.get(path)
            linked &= isinstance(record, dict) and record.get("sha256") == digest and record.get("bytes") == size
    audit.check(linked, "attempt log cryptographically links every provider stream and message")
    closure = load_json_or_jsonl(collection_closed_path)
    audit.check(
        isinstance(closure, dict)
        and closure.get("attempt_artifact_manifest_sha256") == sha256(artifact_manifest_path),
        "collection closure binds the attempt artifact manifest",
    )
    bootstrap = analysis.get("bootstrap", {})
    replicates = bootstrap.get("replicates")
    seed = bootstrap.get("seed")
    if not isinstance(replicates, int) or not isinstance(seed, int):
        audit.check(False, "analysis publishes integer bootstrap replicates and seed")
        return
    recomputed_analysis = analysis_module.analyze(
        recomputed_scored, replicates=replicates, seed=seed, require_four_blocks=True
    )
    audit.check(
        json.dumps(recomputed_analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == json.dumps(analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "published statistics exactly recompute from scored evidence",
    )


def audit_public_files(audit: Audit, release_dir: Path) -> None:
    text_suffixes = {".md", ".json", ".jsonl", ".txt", ".csv", ".py", ".yml", ".yaml", ".toml"}
    findings: list[str] = []
    for path in sorted(release_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PRIVATE_PATTERNS:
            if pattern.search(text):
                findings.append(f"{path.relative_to(release_dir)}: {label}")
    audit.check(not findings, "no private paths, UUIDs, source-task IDs, or secrets", "; ".join(findings[:20]))

    broken: list[str] = []
    markdown_link = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    for path in sorted(release_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for target in markdown_link.findall(text):
            target = target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(release_dir)} -> {target}")
    audit.check(not broken, "local Markdown links resolve", "; ".join(broken[:20]))


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    experiment = Path(args.experiment_dir).resolve()
    paths = {
        "manifest": Path(args.manifest or experiment / "run_manifest.json"),
        "attempts": Path(args.attempts or experiment / "attempts.jsonl"),
        "answers": Path(args.answers or experiment / "benchmark" / "hidden" / "final_answers.jsonl"),
        "freeze": Path(args.freeze_manifest or experiment / "freeze_manifest.json"),
        "scored": Path(args.scored or experiment / "results" / "scored_results.json"),
        "analysis": Path(args.analysis or experiment / "results" / "analysis.json"),
        "collection_closed": Path(args.collection_closed or experiment / "raw" / "final" / "collection_closed.json"),
        "case_manifest": Path(args.case_manifest or experiment / "benchmark" / "public" / "final_blocks.json"),
    }
    audit = Audit()
    for label, path in paths.items():
        audit.check(path.is_file(), f"required {label} artifact exists", str(path))
    if any(not path.is_file() for path in paths.values()):
        return audit.report()
    manifest = load_json_or_jsonl(paths["manifest"])
    attempts = load_json_or_jsonl(paths["attempts"])
    scored = load_json_or_jsonl(paths["scored"])
    analysis = load_json_or_jsonl(paths["analysis"])
    freeze = load_json_or_jsonl(paths["freeze"])
    if not isinstance(scored, dict) or not isinstance(analysis, dict):
        raise ValueError("scored and analysis artifacts must be JSON objects")
    audit_run_manifest(audit, manifest)
    audit_attempts(audit, attempts, manifest)
    audit_attempt_artifacts(audit, attempts, paths["attempts"], paths["collection_closed"])
    audit_scored(audit, scored)
    audit_analysis(audit, analysis, scored)
    audit_provenance(audit, scored, paths)
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    freeze_module = importlib.import_module("freeze_experiment")
    try:
        freeze_module.verify_freeze(paths["freeze"], experiment)
    except Exception as exc:
        audit.check(False, "freeze verifier accepts every immutable input", str(exc))
    else:
        audit.check(True, "freeze verifier accepts every immutable input")
    audit_freeze(audit, freeze, experiment)
    audit_recomputation(audit, paths, scored, analysis)
    audit_public_files(audit, Path(args.release_dir).resolve() if args.release_dir else experiment.parent)
    return audit.report()


def self_test() -> None:
    audit = Audit()
    audit.check(True, "true")
    audit.warn("warning", "expected")
    report = audit.report()
    assert report["status"] == "pass" and report["summary"] == {"passed": 1, "failed": 0, "warnings": 1}
    audit.check(False, "false")
    assert audit.report()["status"] == "fail"
    assert _close(0.1 + 0.2, 0.3)
    role_plan = {
        ("independent", "solver"): (20, 0),
        ("swarm10", "proposer"): (5, 0), ("swarm10", "critic"): (2, 5),
        ("swarm10", "verifier"): (2, 7), ("swarm10", "judge"): (1, 9),
        ("tournament20", "explorer"): (8, 0), ("tournament20", "breaker"): (4, 8),
        ("tournament20", "verifier"): (4, 12), ("tournament20", "synthesizer"): (2, 16),
        ("tournament20", "red_team"): (1, 18), ("tournament20", "judge"): (1, 19),
    }
    calls = []
    group_prior: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for block in sorted(EXPECTED_BLOCKS):
        for condition in ("light", "medium"):
            for (architecture, role), (count, dependencies) in role_plan.items():
                role_call_ids = []
                for index in range(count):
                    group = (block, condition, architecture)
                    call_id = f"{block}-{condition}-{architecture}-{role}-{index}"
                    calls.append({
                        "call_id": call_id,
                        "block_id": block, "condition_label": condition,
                        "architecture": architecture, "role": role,
                        "case_ids": [f"{block}-C{i:02d}" for i in range(12)],
                        "dependency_call_ids": list(group_prior[group]),
                        "prompt_identity_sha256": "a" * 64,
                    })
                    role_call_ids.append(call_id)
                group_prior[(block, condition, architecture)].extend(role_call_ids)
    integration = Audit()
    audit_run_manifest(integration, {"calls": calls})
    assert integration.report()["status"] == "pass"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        immutable: dict[str, Any] = {}
        for relative in (
            "PROTOCOL.md", "ANALYSIS_PLAN.md", "CALIBRATION_PLAN.md",
            "scripts/run_codex_cli.py", "scripts/run_manifest.py", "scripts/attempt_log.py",
            "scripts/build_packets.py", "scripts/validate_outputs.py", "scripts/score_results.py",
            "scripts/analyze_results.py", "scripts/evaluate_calibration.py", "scripts/audit_release.py",
            "scripts/prepare_gate_reports.py",
            "prompts/SCHEMAS.json", "prompts/ROLE_CATALOG.json", "benchmark/manifest.json",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
            immutable[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}
        freeze = {
            "freeze_schema_version": "2.1",
            "immutable_files": immutable,
            "immutable_set_sha256": hashlib.sha256(
                json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        freeze["freeze_manifest_sha256"] = hashlib.sha256(
            json.dumps(freeze, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        freeze_audit = Audit()
        audit_freeze(freeze_audit, freeze, root)
        assert freeze_audit.report()["status"] == "pass"
    print("audit_release.py self-test: ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--manifest")
    parser.add_argument("--attempts")
    parser.add_argument("--answers")
    parser.add_argument("--freeze-manifest")
    parser.add_argument("--scored")
    parser.add_argument("--analysis")
    parser.add_argument("--collection-closed")
    parser.add_argument("--case-manifest")
    parser.add_argument("--release-dir")
    parser.add_argument("--output", help="write audit JSON; stdout if omitted")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        report = run_audit(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"audit error: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
