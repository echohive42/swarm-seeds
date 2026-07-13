#!/usr/bin/env python3
"""Fail-closed, standard-library release audit for Experiment 04.

The audit distinguishes frozen request configuration from provider-reported
runtime identity.  A missing provider model report is a warning; conflicting
provider metadata is a hard failure.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
SEED_DIR = EXPERIMENT_DIR.parent
SWARM_SEEDS_DIR = SEED_DIR.parent

SCHEMA_VERSION = "experiment-04-release-audit-v1"
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"
PUBLIC_LABEL = "Light reasoning"
SERVICE_TIER = "standard"
TIMEOUT_SECONDS = 300
MAX_CONCURRENCY = 60
LEDGER_VERSION = "experiment-04-attempts-v1"
EXPECTED_BINARY_SHA256 = "718724d7221cf1298071ca92411cb74caa8422809154150cedca7b569a4518e3"

EXPECTED_PLAN = {"search": 1_920, "validation": 360, "final": 320, "total": 2_600}
EXPECTED_SPLITS = {"search": 192, "validation": 72, "final": 96}
EXPECTED_FINAL_METHODS = (
    "evolved_champion",
    "best_initial_founder",
    "generalist_vote10",
    "diversified_vote10",
)
EXPECTED_COMPARISONS = (
    ("evolved_champion", "diversified_vote10"),
    ("evolved_champion", "best_initial_founder"),
    ("evolved_champion", "generalist_vote10"),
)

DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "computer_use", "enable_mcp_apps", "goals", "hooks", "image_generation",
    "in_app_browser", "multi_agent", "multi_agent_v2", "plugin_sharing", "plugins",
    "remote_plugin", "shell_tool", "skill_mcp_dependency_install",
    "standalone_web_search", "tool_suggest", "unified_exec", "workspace_dependencies",
)

DECISION_LAYOUTS = {
    "vote_10p": {"proposer": 10},
    "judge_9p1j": {"proposer": 9, "judge": 1},
    "gated_7p2c1j": {"proposer": 7, "critic": 2, "judge": 1},
    "dual_8p2j": {"proposer": 8, "judge": 2},
    "verified_7p2v1j": {"proposer": 7, "verifier": 2, "judge": 1},
    "deliberative_6p2c2j": {"proposer": 6, "critic": 2, "judge": 2},
}

ALLOWED_ATTEMPT_STATUSES = {
    "valid_output", "schema_invalid", "infrastructure_failure", "protocol_violation",
}
ALLOWED_TERMINAL_OUTCOMES = {
    "valid_output", "schema_invalid_exhausted", "infrastructure_exhausted", "protocol_violation",
}

SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|password|"
    r"client[_-]?secret|private[_-]?key)$",
    re.I,
)
SECRET_TEXT = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}|\bgh[opusr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
LOCAL_PATH = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|/private/var/folders/[A-Za-z0-9._/-]+|"
    r"/tmp/[A-Za-z0-9._/-]+|[A-Za-z]:\\\\Users\\\\[^\s\"']+)(?:/[^\s\"',)]*)?"
)
UUID_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.I,
)
THREAD_KEY = re.compile(r"^(?:thread|conversation|session|task)[_-]?id$|^(?:source_task|task_uuid|thread_uuid|codex_task_id)$", re.I)
THREAD_TEXT = re.compile(
    r"\b(?:thread|conversation|session|task)[_-]?id\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]{8,}",
    re.I,
)

TRANSPORT_NAMES = {"events.jsonl", "process.json", "stderr.txt", "transport_result.json"}
REQUIRED_IGNORE_MARKERS = {
    "transport_events": "events.jsonl",
    "transport_process": "process.json",
    "transport_stderr": "stderr.txt",
    "transport_result": "transport_result.json",
    "run_locks": ".run.lock",
    "smoke_runs": "runs/smoke",
    "preflight_runs": "runs/preflight",
    "python_cache": "__pycache__",
    "python_bytecode": "*.py[cod]",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{number} is not a JSON object")
        rows.append(value)
    return rows


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def relative(path: Path, base: Path = EXPERIMENT_DIR) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def bounded(values: Iterable[Any], limit: int = 40) -> list[Any]:
    result = list(values)
    if len(result) <= limit:
        return result
    return result[:limit] + [{"omitted": len(result) - limit}]


def sorted_counts(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def sealed_artifact_ok(value: Any) -> bool:
    if not isinstance(value, dict) or not is_sha256(value.get("artifact_sha256")):
        return False
    body = dict(value)
    declared = body.pop("artifact_sha256")
    return declared == canonical_sha256(body)


def genome_ok(genome: Any) -> bool:
    if not isinstance(genome, dict) or not isinstance(genome.get("genes"), dict):
        return False
    genes = genome["genes"]
    lenses = genes.get("worker_lens_ids")
    if set(genes) != {"decision_system_id", "worker_lens_ids", "judge_policy_id"}:
        return False
    if genes.get("decision_system_id") not in DECISION_LAYOUTS or not isinstance(lenses, list) or len(lenses) != 10:
        return False
    digest = canonical_sha256(genes)
    return genome.get("genome_sha256") == digest and genome.get("genome_id") == "G-" + digest[:12].upper()


def expected_request_sha256(job: dict[str, Any], binary_hash: str) -> str:
    identity = {
        "prompt_sha256": sha256_bytes(str(job["prompt"]).encode("utf-8")),
        "schema_sha256": canonical_sha256(job["output_schema"]),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "binary_sha256": binary_hash,
        "timeout": TIMEOUT_SECONDS,
        "disabled_features": list(DISABLED_FEATURES),
    }
    return canonical_sha256(identity)


def frozen_public_command() -> dict[str, Any]:
    argv = [
        "<FROZEN_CODEX_BINARY>", "exec", "--model", MODEL, "-c",
        'model_reasoning_effort="low"', "--ephemeral", "--ignore-user-config",
        "--ignore-rules", "--strict-config", "--skip-git-repo-check", "--sandbox", "read-only",
    ]
    for feature in DISABLED_FEATURES:
        argv.extend(("--disable", feature))
    argv.extend((
        "--json", "--color", "never", "--output-schema", "<OUTPUT_SCHEMA>",
        "--output-last-message", "<LAST_MESSAGE>", "-C", "<FRESH_EMPTY_WORKSPACE>", "-",
    ))
    return {"argv": argv, "prompt_transport": "stdin"}


def terminal_outcome(statuses: list[str]) -> str | None:
    if "valid_output" in statuses:
        return "valid_output"
    if "protocol_violation" in statuses:
        return "protocol_violation"
    if statuses.count("schema_invalid") >= 2:
        return "schema_invalid_exhausted"
    if statuses.count("infrastructure_failure") >= 3:
        return "infrastructure_exhausted"
    return None


def peak_concurrency(attempts: Iterable[dict[str, Any]]) -> tuple[int, list[str]]:
    events: list[tuple[datetime, int]] = []
    errors: list[str] = []
    for row in attempts:
        try:
            started = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
            finished = datetime.fromisoformat(str(row["finished_at"]).replace("Z", "+00:00"))
            if finished < started:
                raise ValueError("finished before started")
            events.extend(((started, 1), (finished, -1)))
        except (KeyError, ValueError) as exc:
            errors.append(f"{row.get('job_id')}: {exc}")
    active = peak = 0
    for _timestamp, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    if active:
        errors.append(f"unbalanced interval sweep ended at {active}")
    return peak, errors


@dataclass(frozen=True)
class RunSpec:
    name: str
    relative: str
    phase: str
    blocks: tuple[str, ...]
    candidates: tuple[str, ...]
    methods: tuple[str, ...]
    expected_jobs: int
    baseline: bool = False


class Audit:
    def __init__(self, root: Path, output: Path) -> None:
        self.root = root
        self.seed = root.parent
        self.output = output
        self.checks: list[dict[str, Any]] = []
        self.release_files: list[Path] = []
        self.block_cases: dict[str, tuple[str, ...]] = {}

    def hard(self, name: str, condition: bool, detail: Any) -> None:
        self.checks.append({
            "name": name,
            "severity": "hard",
            "status": "passed" if condition else "failed",
            "detail": detail,
        })

    def warn(self, name: str, condition: bool, detail: Any) -> None:
        self.checks.append({
            "name": name,
            "severity": "warning",
            "status": "passed" if condition else "warning",
            "detail": detail,
        })

    def safe_error(self, exc: Exception) -> dict[str, str]:
        message = str(exc).replace(str(self.seed), ".").replace(str(self.root), "experiment")
        return {"type": type(exc).__name__, "message": message}

    def section(self, name: str, function: Callable[[], Any]) -> Any:
        try:
            return function()
        except (OSError, ValueError, TypeError, KeyError, AssertionError, json.JSONDecodeError, csv.Error, subprocess.SubprocessError) as exc:
            detail = self.safe_error(exc)
            self.hard(f"{name}.completed", False, detail)
            return {"error": detail}

    def audit_release_surface(self) -> dict[str, Any]:
        repo = Path(subprocess.check_output(
            ("git", "-C", str(self.seed), "rev-parse", "--show-toplevel"), text=True,
        ).strip()).resolve()
        relative_seed = self.seed.resolve().relative_to(repo).as_posix()
        raw = subprocess.check_output((
            "git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard",
            "-z", "--", relative_seed,
        ))
        listed = [repo / os.fsdecode(item) for item in raw.split(b"\0") if item]
        missing = sorted(path.relative_to(repo).as_posix() for path in listed if not path.is_file())
        outside = sorted(str(path) for path in listed if self.seed.resolve() not in path.resolve().parents)
        self.release_files = sorted((path for path in listed if path.is_file()), key=lambda path: path.relative_to(self.seed).as_posix())
        detail = {
            "scope": "Git-visible tracked plus intended-untracked files under the seed, via git ls-files --cached --others --exclude-standard",
            "files": len(self.release_files),
            "bytes": sum(path.stat().st_size for path in self.release_files),
            "missing": missing,
            "outside_seed": outside,
            "audit_output_present_at_scan_start": self.output.is_file(),
        }
        self.hard("release.surface_enumeration", not missing and not outside and bool(self.release_files), detail)
        return detail

    @staticmethod
    def exclusion_kind(path: Path, seed: Path) -> str | None:
        rel = path.relative_to(seed)
        parts = rel.parts
        if path.name in TRANSPORT_NAMES and "runner" in parts and "jobs" in parts:
            return "transport_process_diagnostics"
        if path.name == ".run.lock" and "runner" in parts:
            return "run_locks"
        if "__pycache__" in parts or path.suffix in {".pyc", ".pyo", ".pyd"}:
            return "python_cache"
        joined = rel.as_posix()
        if joined.startswith("experiment/runs/smoke/") or joined.startswith("experiment/runs/preflight/"):
            return "smoke_preflight"
        return None

    def audit_exclusions(self) -> dict[str, Any]:
        ignore_path = self.seed / ".gitignore"
        lines = {line.strip() for line in ignore_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")}
        missing_rules = sorted(
            category for category, marker in REQUIRED_IGNORE_MARKERS.items()
            if not any(marker in line for line in lines)
        )
        visible_violations = [
            path.relative_to(self.seed).as_posix()
            for path in self.release_files
            if self.exclusion_kind(path, self.seed) is not None
        ]
        filesystem_counts: Counter[str] = Counter()
        for path in self.seed.rglob("*"):
            if path.is_file():
                kind = self.exclusion_kind(path, self.seed)
                if kind:
                    filesystem_counts[kind] += 1
        detail = {
            "required_ignore_categories": dict(sorted(REQUIRED_IGNORE_MARKERS.items())),
            "missing_ignore_categories": missing_rules,
            "excluded_files_present_locally": dict(sorted(filesystem_counts.items())),
            "git_visible_exclusion_violations": bounded(visible_violations),
            "sanitized_command_json_is_release_intended": True,
        }
        self.hard("release.excluded_transport_and_process_artifacts", not missing_rules and not visible_violations, detail)
        return detail

    def audit_freeze(self) -> dict[str, Any]:
        manifest_path = self.root / "freeze_manifest.json"
        manifest = load_json(manifest_path)
        declared = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(declared, dict):
            raise ValueError("freeze manifest lacks files mapping")
        malformed = [name for name, digest in declared.items() if not isinstance(name, str) or not is_sha256(digest)]
        mismatches: list[dict[str, Any]] = []
        escapes: list[str] = []
        for name, expected in sorted(declared.items()):
            path = self.root / name
            try:
                path.resolve().relative_to(self.root.resolve())
            except ValueError:
                escapes.append(name)
                continue
            actual = file_sha256(path) if path.is_file() else None
            if actual != expected:
                mismatches.append({"path": name, "expected": expected, "actual": actual})
        external_paths = {
            "experiment_03_generator": SWARM_SEEDS_DIR / "03-evolving-light-swarms/experiment/scripts/generate_benchmark.py",
            "experiment_03_runner": SWARM_SEEDS_DIR / "03-evolving-light-swarms/experiment/scripts/run_jobs.py",
            "experiment_03_scorer": SWARM_SEEDS_DIR / "03-evolving-light-swarms/experiment/scripts/score.py",
        }
        actual_external = {name: file_sha256(path) if path.is_file() else None for name, path in external_paths.items()}
        external_mismatches = {
            name: {"expected": manifest.get("external_dependencies", {}).get(name), "actual": actual}
            for name, actual in actual_external.items()
            if manifest.get("external_dependencies", {}).get(name) != actual
        }
        metadata_ok = (
            manifest.get("schema_version") == "1.0"
            and manifest.get("experiment") == "swarm-seeds-04"
            and manifest.get("hash_algorithm") == "sha256"
            and manifest.get("file_count") == len(declared) == 68
        )
        self.hard("freeze.declared_file_hashes", not mismatches and not malformed and not escapes, {
            "files_checked": len(declared), "mismatches": bounded(mismatches),
            "malformed_entries": malformed, "path_escapes": escapes,
        })
        self.hard("freeze.metadata", metadata_ok, {
            "schema_version": manifest.get("schema_version"), "experiment": manifest.get("experiment"),
            "hash_algorithm": manifest.get("hash_algorithm"), "declared_file_count": manifest.get("file_count"),
            "mapping_file_count": len(declared), "expected_file_count": 68,
        })
        self.hard("freeze.repository_local_dependencies", not external_mismatches, {
            "verified": actual_external, "mismatches": external_mismatches,
        })
        return {
            "manifest_sha256": file_sha256(manifest_path),
            "files_checked": len(declared),
            "file_mismatches": mismatches,
            "external_dependencies": actual_external,
            "verified": not mismatches and not malformed and not escapes and metadata_ok and not external_mismatches,
            "scope_note": "Post-freeze release-only audit and reporting files are not treated as experimental inputs.",
        }

    def _benchmark_description(self, benchmark: Path) -> dict[str, Any]:
        manifest_path = benchmark / "manifest.json"
        manifest = load_json(manifest_path)
        public: list[dict[str, Any]] = []
        for path in sorted((benchmark / "public").glob("*_cases.jsonl")):
            public.extend(load_jsonl(path))
        recognizer = load_json(benchmark / "hidden/recognizer_audit.json")
        audited = recognizer.get("cases") if isinstance(recognizer, dict) else None
        if not isinstance(audited, list) or len(audited) != len(public):
            raise ValueError(f"public/recognizer count mismatch for {benchmark.name}")
        prefixes = [tuple(str(item) for item in row["terms"]) for row in public]
        programs = [str(row["program_sha256"]) for row in audited]
        targets = [str(row["target_sha256"]) for row in audited]
        return {
            "benchmark_id": manifest.get("benchmark_id"),
            "manifest_sha256": file_sha256(manifest_path),
            "case_count": len(public),
            "prefixes": set(prefixes), "programs": set(programs), "targets": set(targets),
            "unique_visible_prefix_count": len(set(prefixes)),
            "unique_program_count": len(set(programs)),
            "unique_target_count": len(set(targets)),
        }

    def audit_benchmark(self) -> dict[str, Any]:
        benchmark = self.root / "benchmark"
        manifest_path = benchmark / "manifest.json"
        manifest = load_json(manifest_path)
        checksums = manifest.get("checksums")
        if not isinstance(checksums, dict):
            raise ValueError("benchmark manifest lacks checksums")
        checksum_errors = []
        for name, expected in sorted(checksums.items()):
            path = benchmark / name
            actual = file_sha256(path) if path.is_file() else None
            if actual != expected:
                checksum_errors.append({"path": name, "expected": expected, "actual": actual})
        shape_ok = (
            manifest.get("experiment_id") == "swarm-seeds-04"
            and manifest.get("benchmark_id") == "ruleweave-5-decider-v1"
            and manifest.get("splits") == EXPECTED_SPLITS
            and manifest.get("blocks_per_split") == {"search": 16, "validation": 6, "final": 8}
            and manifest.get("cases_per_block") == 12
            and manifest.get("provider_reasoning_setting_for_light") == "low"
            and manifest.get("public_reasoning_labels") == ["light"]
            and manifest.get("all_consecutive_block_pairs_cover_all_24_family_tier_cells_once") is True
        )
        case_counts: dict[str, int] = {}
        case_ids: dict[str, list[str]] = {}
        block_errors: list[str] = []
        self.block_cases = {}
        for split, expected_cases in EXPECTED_SPLITS.items():
            records = load_jsonl(benchmark / f"public/{split}_cases.jsonl")
            ids = [str(row.get("case_id")) for row in records]
            case_counts[split] = len(records)
            case_ids[split] = ids
            expected_blocks = int(manifest["blocks_per_split"][split])
            for number in range(1, expected_blocks + 1):
                block = load_json(benchmark / f"public/{split}_B{number:02d}.json")
                block_id = f"{split}-b{number:02d}"
                observed = tuple(str(row.get("case_id")) for row in block.get("cases", []))
                if block.get("block_id") != block_id or len(observed) != 12 or any(item not in ids for item in observed):
                    block_errors.append(block_id)
                self.block_cases[block_id] = observed
            if len(records) != expected_cases or len(set(ids)) != expected_cases:
                block_errors.append(f"{split}:case_count_or_identity")
        current = self._benchmark_description(benchmark)
        references = [
            self._benchmark_description(SWARM_SEEDS_DIR / "02-hard-sequence-scaling/experiment/benchmark"),
            self._benchmark_description(SWARM_SEEDS_DIR / "03-evolving-light-swarms/experiment/benchmark"),
        ]
        overlap_by_reference: dict[str, dict[str, int]] = {}
        for reference in references:
            overlap_by_reference[str(reference["benchmark_id"])] = {
                "visible_prefixes": len(current["prefixes"] & reference["prefixes"]),
                "generator_programs": len(current["programs"] & reference["programs"]),
                "next_five_targets": len(current["targets"] & reference["targets"]),
            }
        total_overlap = {
            key: sum(row[key] for row in overlap_by_reference.values())
            for key in ("visible_prefixes", "generator_programs", "next_five_targets")
        }
        internal_duplicates = {
            "visible_prefixes": current["case_count"] - current["unique_visible_prefix_count"],
            "generator_programs": current["case_count"] - current["unique_program_count"],
            "next_five_targets": current["case_count"] - current["unique_target_count"],
        }
        declared_overlap = load_json(benchmark / "overlap_with_experiments_02_03.json")
        report_ok = (
            declared_overlap.get("schema_version") == "experiment-04-overlap-audit-v1"
            and declared_overlap.get("status") == "passed"
            and declared_overlap.get("cross_experiment_overlap_counts_by_reference") == overlap_by_reference
            and declared_overlap.get("cross_experiment_overlap_counts_total") == total_overlap
            and declared_overlap.get("current_internal_duplicate_counts") == internal_duplicates
            and declared_overlap.get("current", {}).get("manifest_sha256") == current["manifest_sha256"]
        )
        self.hard("benchmark.frozen_checksums", not checksum_errors, {
            "files_checked": len(checksums), "mismatches": bounded(checksum_errors),
        })
        self.hard("benchmark.registered_shape", shape_ok and not block_errors, {
            "splits": case_counts, "blocks": manifest.get("blocks_per_split"), "block_errors": block_errors,
        })
        self.hard("benchmark.zero_overlap", not any(total_overlap.values()) and not any(internal_duplicates.values()) and report_ok, {
            "cross_experiment": overlap_by_reference,
            "total": total_overlap,
            "internal_duplicates": internal_duplicates,
            "declared_report_matches_recomputation": report_ok,
        })
        return {
            "manifest_sha256": file_sha256(manifest_path),
            "case_counts": case_counts,
            "overlap": {"by_reference": overlap_by_reference, "total": total_overlap, "internal_duplicates": internal_duplicates},
            "verified": not checksum_errors and shape_ok and not block_errors and report_ok and not any(total_overlap.values()) and not any(internal_duplicates.values()),
        }

    @staticmethod
    def _genes_flat(genes: dict[str, Any]) -> dict[str, str]:
        result = {"decision_system_id": str(genes["decision_system_id"]), "judge_policy_id": str(genes["judge_policy_id"])}
        result.update({f"worker_lens_ids.{index}": str(value) for index, value in enumerate(genes["worker_lens_ids"])})
        return result

    @staticmethod
    def _fitness_valid(value: Any, cases: int, calls: int) -> bool:
        if not isinstance(value, dict):
            return False
        block = value.get("block_exact")
        expected = [
            value.get("exact_cases"), value.get("weakest_block_exact"),
            -value.get("harmful_overrides", -10**9), value.get("term_correct"), value.get("format_valid"),
        ]
        return (
            isinstance(block, dict) and block
            and value.get("case_count") == cases and value.get("calls") == calls
            and value.get("weakest_block_exact") == min(block.values())
            and value.get("exact_cases") == sum(block.values())
            and value.get("fitness_key") == expected
        )

    def audit_evolution(self) -> dict[str, Any]:
        genomes_dir = self.root / "genomes"
        catalog_path = genomes_dir / "GENOME_CATALOG.json"
        catalog = load_json(catalog_path)
        catalog_hash = file_sha256(catalog_path)
        catalog_expected = {
            "experiment_id": "swarm-seeds-04", "public_condition_label": PUBLIC_LABEL,
            "provider_reasoning_effort": REASONING_EFFORT, "evolution_seed": "swarm-seeds-04-evolution-v1",
            "rounds": 8, "parent_slots": 6, "candidates_per_round": 12, "calls_per_block": 10,
            "search_blocks_per_round": 2, "search_cases_per_candidate": 24,
            "search_calls_per_candidate": 20, "validation_cases_per_candidate": 72,
            "validation_calls_per_candidate": 60,
        }
        catalog_errors = {key: {"expected": expected, "actual": catalog.get(key)} for key, expected in catalog_expected.items() if catalog.get(key) != expected}
        expected_candidate_names = {f"round-{number:02d}-candidates.json" for number in range(1, 9)}
        expected_survivor_names = {f"round-{number:02d}-survivors.json" for number in range(1, 9)}
        actual_candidate_names = {path.name for path in genomes_dir.glob("round-*-candidates.json")}
        actual_survivor_names = {path.name for path in genomes_dir.glob("round-*-survivors.json")}
        population_path = genomes_dir / "round-00-parents.json"
        population = load_json(population_path)
        artifact_errors: list[str] = []
        chain_errors: list[str] = []
        reproduction_errors: list[str] = []
        if not sealed_artifact_ok(population) or population.get("round_completed") != 0 or len(population.get("slots", [])) != 6:
            artifact_errors.append("round-00-parents")
        best_path = genomes_dir / "best-founder-freeze.json"
        best = load_json(best_path)
        best_hash = best.get("artifact_sha256")
        if not sealed_artifact_ok(best):
            artifact_errors.append("best-founder-freeze")
        prior_path = population_path
        prior = population
        round_details: list[dict[str, Any]] = []
        round_one_receipts: list[dict[str, Any]] = []
        round_one_lookup: dict[str, dict[str, Any]] = {}
        for number in range(1, 9):
            candidate_path = genomes_dir / f"round-{number:02d}-candidates.json"
            survivor_path = genomes_dir / f"round-{number:02d}-survivors.json"
            candidates = load_json(candidate_path)
            survivors = load_json(survivor_path)
            if not sealed_artifact_ok(candidates):
                artifact_errors.append(f"round-{number:02d}-candidates")
            if not sealed_artifact_ok(survivors):
                artifact_errors.append(f"round-{number:02d}-survivors")
            prior_slots = prior.get("slots", [])
            prior_by_slot = {str(item.get("slot_id")): item.get("genome") for item in prior_slots}
            prior_by_id = {str(genome.get("genome_id")): genome for genome in prior_by_slot.values() if isinstance(genome, dict)}
            genome_list = candidates.get("genomes", [])
            genome_by_id = {str(item.get("genome_id")): item for item in genome_list if isinstance(item, dict)}
            pairs = candidates.get("parent_child_pairs", [])
            operations = Counter(str(pair.get("operation")) for pair in pairs if isinstance(pair, dict))
            expected_blocks = [f"search-b{2 * number - 1:02d}", f"search-b{2 * number:02d}"]
            if (
                candidates.get("round") != number or candidates.get("search_blocks") != expected_blocks
                or candidates.get("reproduction_summary") != {"parents": 6, "one_gene_mutations": 4, "crossovers": 2}
                or len(genome_list) != 12 or len(genome_by_id) != 12 or len(pairs) != 6
                or operations != Counter({"one_gene_mutation": 4, "crossover": 2})
                or any(not genome_ok(item) for item in genome_list)
            ):
                reproduction_errors.append(f"round-{number:02d}:shape")
            if (
                candidates.get("source_parent_artifact_sha256") != prior.get("artifact_sha256")
                or candidates.get("source_parent_file_sha256") != file_sha256(prior_path)
                or candidates.get("catalog_file_sha256") != catalog_hash
                or candidates.get("best_founder_freeze_artifact_sha256") != (None if number == 1 else best_hash)
            ):
                chain_errors.append(f"round-{number:02d}:candidate_source")
            pair_slots: list[str] = []
            for pair in pairs:
                slot = str(pair.get("slot_id"))
                pair_slots.append(slot)
                parent_id = str(pair.get("parent_genome_id"))
                child_id = str(pair.get("child_genome_id"))
                parent_genome = prior_by_slot.get(slot)
                child = genome_by_id.get(child_id)
                if not isinstance(parent_genome, dict) or parent_genome.get("genome_id") != parent_id or not isinstance(child, dict):
                    reproduction_errors.append(f"round-{number:02d}:{slot}:identity")
                    continue
                lineage = child.get("lineage", {})
                operation = pair.get("operation")
                if lineage.get("operation") != operation or lineage.get("round") != number or lineage.get("designated_parent_slot") != slot:
                    reproduction_errors.append(f"round-{number:02d}:{slot}:lineage")
                if operation == "one_gene_mutation":
                    parent_flat = self._genes_flat(parent_genome["genes"])
                    child_flat = self._genes_flat(child["genes"])
                    differences = [key for key in parent_flat if parent_flat[key] != child_flat[key]]
                    mutation = lineage.get("mutation") or {}
                    if (
                        differences != [mutation.get("locus")]
                        or mutation.get("from") != parent_flat.get(str(mutation.get("locus")))
                        or mutation.get("to") != child_flat.get(str(mutation.get("locus")))
                        or lineage.get("parents") != [parent_id]
                    ):
                        reproduction_errors.append(f"round-{number:02d}:{slot}:mutation")
                elif operation == "crossover":
                    source_ids = lineage.get("parents")
                    if not isinstance(source_ids, list) or len(source_ids) != 2 or parent_id not in source_ids or any(item not in prior_by_id for item in source_ids):
                        reproduction_errors.append(f"round-{number:02d}:{slot}:crossover_parents")
                    else:
                        source_flats = [self._genes_flat(prior_by_id[item]["genes"]) for item in source_ids]
                        child_flat = self._genes_flat(child["genes"])
                        if any(child_flat[key] not in {source_flats[0][key], source_flats[1][key]} for key in child_flat):
                            reproduction_errors.append(f"round-{number:02d}:{slot}:crossover_genes")
            if pair_slots != [f"S{index:02d}" for index in range(1, 7)]:
                reproduction_errors.append(f"round-{number:02d}:slot_order")
            expected_ids = {str(pair.get(key)) for pair in pairs for key in ("parent_genome_id", "child_genome_id")}
            if set(genome_by_id) != expected_ids:
                reproduction_errors.append(f"round-{number:02d}:population_members")
            before = candidates.get("history_genome_sha256s_before")
            history = candidates.get("history_genome_sha256s")
            child_hashes = {genome_by_id[str(pair.get("child_genome_id"))]["genome_sha256"] for pair in pairs if str(pair.get("child_genome_id")) in genome_by_id}
            if (
                before != prior.get("history_genome_sha256s") or not isinstance(history, list)
                or len(history) != len(set(history)) or set(history) != set(before or []) | child_hashes
            ):
                reproduction_errors.append(f"round-{number:02d}:global_history")
            receipts = survivors.get("comparison_receipts", [])
            survivor_slots = survivors.get("slots", [])
            survivor_by_slot = {str(item.get("slot_id")): item.get("genome") for item in survivor_slots if isinstance(item, dict)}
            if len(receipts) != 6 or len(survivor_by_slot) != 6 or survivors.get("round_completed") != number:
                reproduction_errors.append(f"round-{number:02d}:survivor_shape")
            accepted = 0
            for pair, receipt in zip(pairs, receipts):
                parent_key = tuple(receipt.get("parent_fitness", {}).get("fitness_key", []))
                child_key = tuple(receipt.get("child_fitness", {}).get("fitness_key", []))
                if not self._fitness_valid(receipt.get("parent_fitness"), 24, 20) or not self._fitness_valid(receipt.get("child_fitness"), 24, 20):
                    reproduction_errors.append(f"round-{number:02d}:{pair.get('slot_id')}:fitness")
                if child_key > parent_key:
                    expected_decision, survivor_id = "replace_parent", pair.get("child_genome_id")
                    accepted += 1
                elif child_key == parent_key:
                    expected_decision, survivor_id = "keep_parent_exact_tie", pair.get("parent_genome_id")
                else:
                    expected_decision, survivor_id = "keep_better_parent", pair.get("parent_genome_id")
                slot_genome = survivor_by_slot.get(str(pair.get("slot_id")))
                if (
                    receipt.get("parent_genome_id") != pair.get("parent_genome_id")
                    or receipt.get("child_genome_id") != pair.get("child_genome_id")
                    or receipt.get("decision") != expected_decision
                    or receipt.get("survivor_genome_id") != survivor_id
                    or not isinstance(slot_genome, dict) or slot_genome.get("genome_id") != survivor_id
                ):
                    reproduction_errors.append(f"round-{number:02d}:{pair.get('slot_id')}:selection")
            answer_path = self.root / f"benchmark/hidden/search_R{number:02d}_answers.jsonl"
            summary_path = self.root / f"results/search/round-{number:02d}/summary.json"
            matrix_path = self.root / f"results/search/round-{number:02d}/case_matrix.csv"
            prediction_path = self.root / f"runs/search/round-{number:02d}/predictions.json"
            expected_sources = {
                "source_candidates_artifact_sha256": candidates.get("artifact_sha256"),
                "source_candidates_file_sha256": file_sha256(candidate_path),
                "source_summary_file_sha256": file_sha256(summary_path),
                "source_case_matrix_file_sha256": file_sha256(matrix_path),
                "source_answers_file_sha256": file_sha256(answer_path),
                "source_predictions_file_sha256": file_sha256(prediction_path),
                "best_founder_freeze_artifact_sha256": best_hash,
            }
            if any(survivors.get(key) != value for key, value in expected_sources.items()):
                chain_errors.append(f"round-{number:02d}:survivor_sources")
            if number == 1:
                round_one_receipts = receipts
                round_one_lookup = genome_by_id
            round_details.append({
                "round": number, "candidates": len(genome_list), "survivors": len(survivor_slots),
                "one_gene_mutations": operations["one_gene_mutation"], "crossovers": operations["crossover"],
                "accepted_children": accepted, "search_blocks": expected_blocks,
            })
            prior_path, prior = survivor_path, survivors
        best_candidates = []
        for receipt in round_one_receipts:
            genome = round_one_lookup.get(str(receipt.get("parent_genome_id")))
            if genome:
                best_candidates.append((tuple(receipt["parent_fitness"]["fitness_key"]), str(genome["genome_sha256"]), genome, receipt["parent_fitness"]))
        expected_best = sorted(best_candidates, key=lambda item: (tuple(-part for part in item[0]), item[1]))[0] if best_candidates else None
        best_ok = bool(expected_best) and (
            best.get("schema_version") == "experiment-04-best-founder-freeze-v1"
            and best.get("round_frozen") == 1
            and best.get("freeze_status") == "best_founder_frozen_after_round_1_before_validation_or_final_answers"
            and best.get("founder_genome", {}).get("genome_id") == expected_best[2].get("genome_id")
            and best.get("fitness") == expected_best[3]
            and best.get("source_answers_file_sha256") == file_sha256(self.root / "benchmark/hidden/search_R01_answers.jsonl")
            and best.get("source_predictions_file_sha256") == file_sha256(self.root / "runs/search/round-01/predictions.json")
        )
        final_ids = tuple(str(item["genome"]["genome_id"]) for item in prior.get("slots", []))
        self.hard("evolution.catalog", not catalog_errors, {"mismatches": catalog_errors, "catalog_sha256": catalog_hash})
        self.hard("evolution.exact_eight_rounds_no_early_stop", (
            actual_candidate_names == expected_candidate_names and actual_survivor_names == expected_survivor_names
            and prior.get("round_completed") == 8 and len(round_details) == 8
        ), {
            "candidate_files": sorted(actual_candidate_names), "survivor_files": sorted(actual_survivor_names),
            "final_round_completed": prior.get("round_completed"),
        })
        self.hard("evolution.population_and_reproduction", not artifact_errors and not reproduction_errors, {
            "rounds": round_details, "artifact_errors": artifact_errors, "reproduction_errors": bounded(reproduction_errors),
        })
        self.hard("evolution.content_addressed_chain", not chain_errors, {"errors": bounded(chain_errors)})
        self.hard("evolution.best_founder_frozen_after_round_one", best_ok, {
            "founder_genome_id": best.get("founder_genome", {}).get("genome_id"),
            "freeze_status": best.get("freeze_status"), "verified": best_ok,
        })
        return {
            "catalog_sha256": catalog_hash, "rounds": round_details, "final_survivor_ids": final_ids,
            "round_08_population_path": relative(prior_path), "round_08_population_sha256": file_sha256(prior_path),
            "best_founder_id": best.get("founder_genome", {}).get("genome_id"),
            "best_founder_artifact_sha256": best_hash,
            "verified": not catalog_errors and not artifact_errors and not reproduction_errors and not chain_errors and best_ok,
        }

    def run_specs(self, evolution: dict[str, Any]) -> list[RunSpec]:
        specs: list[RunSpec] = []
        for number in range(1, 9):
            candidates = load_json(self.root / f"genomes/round-{number:02d}-candidates.json")
            ids = tuple(str(item["genome_id"]) for item in candidates["genomes"])
            specs.append(RunSpec(
                f"search-round-{number:02d}", f"runs/search/round-{number:02d}", f"search-round-{number:02d}",
                (f"search-b{2 * number - 1:02d}", f"search-b{2 * number:02d}"), ids, ids, 240,
            ))
        survivors = load_json(self.root / "genomes/round-08-survivors.json")
        survivor_ids = tuple(str(item["genome"]["genome_id"]) for item in survivors["slots"])
        specs.append(RunSpec(
            "validation", "runs/validation", "validation", tuple(f"validation-b{i:02d}" for i in range(1, 7)),
            survivor_ids, survivor_ids, 360,
        ))
        champion = load_json(self.root / "genomes/champion-freeze.json")
        champion_id = str(champion["champion_genome"]["genome_id"])
        founder_id = str(champion["best_founder_genome"]["genome_id"])
        final_blocks = tuple(f"final-b{i:02d}" for i in range(1, 9))
        specs.extend((
            RunSpec("final-evolved-champion", "runs/final/evolved_champion", "final-evolved_champion", final_blocks, (champion_id,), (champion_id,), 80),
            RunSpec("final-best-initial-founder", "runs/final/best_initial_founder", "final-best_initial_founder", final_blocks, (founder_id,), (founder_id,), 80),
            RunSpec("final-generalist-vote10", "runs/final/generalist_vote10", "final-generalist_vote10", final_blocks, ("GENERALIST-VOTE10",), ("generalist_vote10",), 80, True),
            RunSpec("final-diversified-vote10", "runs/final/diversified_vote10", "final-diversified_vote10", final_blocks, ("DIVERSIFIED-VOTE10",), ("diversified_vote10",), 80, True),
        ))
        return specs

    def audit_run(self, spec: RunSpec) -> tuple[dict[str, Any], set[str], list[Any]]:
        base = self.root / spec.relative
        manifest_paths = sorted((base / "manifests").glob("stage-*.json"))
        if not manifest_paths:
            raise ValueError(f"{spec.name} has no manifests")
        final_manifest = load_json(manifest_paths[-1])
        jobs = final_manifest.get("jobs", [])
        job_by_id = {str(job.get("job_id")): job for job in jobs if isinstance(job, dict)}
        job_ids = set(job_by_id)
        final_stage = max((int(job.get("stage_index", -1)) for job in jobs), default=-1)
        manifest_errors: list[str] = []
        expected_manifest_names = [f"stage-{index:02d}.json" for index in range(final_stage + 1)]
        if [path.name for path in manifest_paths] != expected_manifest_names:
            manifest_errors.append("stage manifest set")
        for index, path in enumerate(manifest_paths):
            manifest = load_json(path)
            stage_jobs = manifest.get("jobs", [])
            expected_jobs = [job for job in jobs if int(job.get("stage_index", -1)) <= index]
            if (
                manifest.get("schema_version") != "4.0"
                or manifest.get("artifact_type") != "experiment-04-job-manifest"
                or manifest.get("model") != MODEL or manifest.get("reasoning_effort") != REASONING_EFFORT
                or manifest.get("public_condition_label") != PUBLIC_LABEL or manifest.get("service_tier") != SERVICE_TIER
                or manifest.get("stage_index") != index or stage_jobs != expected_jobs
            ):
                manifest_errors.append(path.name)
        dimension_errors: list[str] = []
        frozen_schema = load_json(self.root / "prompts/answer_block.schema.json")
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        prompt_paths = {path.name for path in (base / "prompts").glob("*.txt")}
        expected_prompt_paths = {f"{job_id}.txt" for job_id in job_ids}
        for job_id, job in job_by_id.items():
            grouped[(str(job.get("genome_id")), str(job.get("block_id")))].append(job)
            block_id = str(job.get("block_id"))
            prompt_path = base / "prompts" / f"{job_id}.txt"
            prompt = job.get("prompt")
            if (
                job.get("phase") != spec.phase or block_id not in spec.blocks
                or job.get("genome_id") not in spec.candidates or job.get("method") not in spec.methods
                or job.get("baseline") is not spec.baseline or job.get("expected_block_id") != block_id
                or tuple(job.get("expected_case_ids", [])) != self.block_cases.get(block_id)
                or job.get("output_schema") != frozen_schema
                or not isinstance(prompt, str) or job.get("prompt_sha256") != sha256_bytes(str(prompt).encode("utf-8"))
                or not prompt_path.is_file() or prompt_path.read_text(encoding="utf-8") != prompt
            ):
                dimension_errors.append(job_id)
        for (candidate, block), group in grouped.items():
            systems = {str(job.get("decision_system_id")) for job in group}
            expected_roles = DECISION_LAYOUTS.get(next(iter(systems), ""))
            roles = Counter(str(job.get("role")) for job in group)
            indexes = sorted(int(job.get("call_index", 0)) for job in group)
            group_ids = {str(job.get("job_id")) for job in group}
            dependency_ok = all(
                set(job.get("dependency_ids", [])) == {
                    str(other.get("job_id")) for other in group
                    if int(other.get("stage_index", -1)) < int(job.get("stage_index", -1))
                }
                for job in group
            )
            if len(systems) != 1 or expected_roles is None or roles != Counter(expected_roles) or indexes != list(range(1, 11)) or not dependency_ok:
                dimension_errors.append(f"{candidate}/{block}")
            if len(group_ids) != 10:
                dimension_errors.append(f"{candidate}/{block}/identity")
        dimensions_ok = (
            len(jobs) == spec.expected_jobs and len(job_by_id) == spec.expected_jobs
            and {str(job.get("genome_id")) for job in jobs} == set(spec.candidates)
            and {str(job.get("method")) for job in jobs} == set(spec.methods)
            and {str(job.get("block_id")) for job in jobs} == set(spec.blocks)
            and len(grouped) == len(spec.candidates) * len(spec.blocks)
            and prompt_paths == expected_prompt_paths and not dimension_errors
        )
        preflight = load_json(base / "runner/preflight.json")
        binary_hash = str(preflight.get("binary_sha256", ""))
        ledger = load_jsonl(base / "runner/attempts.jsonl")
        attempts_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
        closes_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ledger_errors: list[str] = []
        artifact_errors: list[str] = []
        reported_models: list[Any] = []
        closed: set[str] = set()
        attempt_events: list[dict[str, Any]] = []
        for index, event in enumerate(ledger):
            job_id = str(event.get("job_id"))
            event_type = event.get("event_type")
            if event.get("ledger_version") != LEDGER_VERSION or job_id not in job_ids:
                ledger_errors.append(f"line-{index + 1}:version-or-job")
                continue
            if event_type == "attempt":
                if job_id in closed:
                    ledger_errors.append(f"{job_id}:attempt-after-close")
                attempts_by_job[job_id].append(event)
                attempt_events.append(event)
                reported_models.append(event.get("reported_model"))
            elif event_type == "job_closed":
                if job_id in closed:
                    ledger_errors.append(f"{job_id}:duplicate-close")
                closed.add(job_id)
                closes_by_job[job_id].append(event)
            else:
                ledger_errors.append(f"line-{index + 1}:event-type")
        retry_jobs: list[str] = []
        status_counter: Counter[str] = Counter()
        outcome_counter: Counter[str] = Counter()
        for job_id, job in job_by_id.items():
            attempts = attempts_by_job.get(job_id, [])
            closes = closes_by_job.get(job_id, [])
            statuses = [str(item.get("status")) for item in attempts]
            status_counter.update(statuses)
            outcome_counter.update(str(item.get("outcome")) for item in closes)
            if len(attempts) > 1:
                retry_jobs.append(job_id)
            if (
                not attempts or len(closes) != 1 or any(status not in ALLOWED_ATTEMPT_STATUSES for status in statuses)
                or str(closes[0].get("outcome")) not in ALLOWED_TERMINAL_OUTCOMES
                or closes[0].get("outcome") != terminal_outcome(statuses)
                or [item.get("attempt_number") for item in attempts] != list(range(1, len(attempts) + 1))
                or len({item.get("request_sha256") for item in attempts}) != 1
                or statuses.count("schema_invalid") > 1 or statuses.count("infrastructure_failure") > 2
            ):
                ledger_errors.append(f"{job_id}:terminal-or-retry")
            expected_request = expected_request_sha256(job, binary_hash)
            for attempt_number, event in enumerate(attempts, 1):
                attempt_dir = base / "runner/jobs" / job_id / f"attempt-{attempt_number:02d}"
                response_path = attempt_dir / "last_message.txt"
                try:
                    command_ok = load_json(attempt_dir / "command.json") == frozen_public_command()
                    schema_ok = load_json(attempt_dir / "output_schema.json") == job["output_schema"]
                    response_ok = (
                        event.get("response_sha256") is None
                        or (response_path.is_file() and file_sha256(response_path) == event.get("response_sha256"))
                    )
                except (OSError, json.JSONDecodeError):
                    command_ok = schema_ok = response_ok = False
                duration = event.get("duration_ms")
                if (
                    event.get("attempt_number") != attempt_number
                    or event.get("artifact_relpath") != f"jobs/{job_id}/attempt-{attempt_number:02d}"
                    or event.get("request_sha256") != expected_request
                    or not command_ok or not schema_ok or not response_ok
                    or isinstance(duration, bool) or not isinstance(duration, int) or duration < 0
                ):
                    artifact_errors.append(f"{job_id}/attempt-{attempt_number:02d}")
            actual_dirs = sorted(path.name for path in (base / "runner/jobs" / job_id).glob("attempt-*") if path.is_dir())
            expected_dirs = [f"attempt-{number:02d}" for number in range(1, len(attempts) + 1)]
            result_path = base / "runner/jobs" / job_id / "result.json"
            result = load_json(result_path) if result_path.is_file() else {}
            terminal_attempt = attempts[-1] if attempts else {}
            if (
                actual_dirs != expected_dirs or result.get("job_id") != job_id
                or result.get("outcome") != (closes[0].get("outcome") if closes else None)
                or result.get("attempt_count") != len(attempts)
                or result.get("response_sha256") != terminal_attempt.get("response_sha256")
                or result.get("terminal_artifact_relpath") != terminal_attempt.get("artifact_relpath")
            ):
                artifact_errors.append(f"{job_id}/result")
        peak, concurrency_errors = peak_concurrency(attempt_events)
        operational = load_json(base / "runner/operational_summary.json")
        operational_ok = (
            operational.get("selected_jobs") == spec.expected_jobs
            and operational.get("valid_jobs") == spec.expected_jobs
            and operational.get("failed_jobs") == 0 and operational.get("open_jobs") == 0
            and operational.get("attempts") == len(attempt_events)
            and isinstance(operational.get("max_active_processes"), int)
            and 0 <= operational.get("max_active_processes") <= MAX_CONCURRENCY
        )
        predictions_path = base / "predictions.json"
        predictions = load_json(predictions_path)
        records = predictions.get("records", [])
        paid_records = [row for row in records if row.get("calls") == 1 and row.get("is_final_output") is not True]
        aggregate_records = [row for row in records if row.get("is_final_output") is True]
        record_errors: list[str] = []
        paid_by_job: Counter[str] = Counter(str(row.get("job_id")) for row in paid_records)
        for row in paid_records:
            job_id = str(row.get("job_id"))
            job = job_by_id.get(job_id)
            if not job:
                record_errors.append(f"{job_id}:unknown")
                continue
            if (
                row.get("case_id") not in job.get("expected_case_ids", [])
                or row.get("block_id") != job.get("block_id") or row.get("method") != job.get("method")
                or row.get("candidate_id") != job.get("genome_id") or row.get("role") != job.get("role")
                or row.get("call_index") != job.get("call_index") or row.get("prompt_sha256") != job.get("prompt_sha256")
                or row.get("terminal_outcome") != "valid_output"
                or row.get("attempt_count") != len(attempts_by_job[job_id])
            ):
                record_errors.append(job_id)
        aggregate_keys = {
            (str(row.get("candidate_id")), str(row.get("block_id")), str(row.get("case_id")))
            for row in aggregate_records
        }
        expected_aggregate = len(spec.candidates) * len(spec.blocks) * 12
        projection = [
            {key: row.get(key) for key in (
                "phase", "method", "candidate_id", "block_id", "case_id", "role",
                "call_index", "answer", "format_valid", "aggregate_rule", "gate_open",
            )}
            for row in records
        ]
        prediction_ok = (
            predictions.get("job_count") == spec.expected_jobs
            and predictions.get("paid_call_count") == spec.expected_jobs
            and predictions.get("aggregate_record_count") == expected_aggregate
            and len(paid_records) == spec.expected_jobs * 12
            and set(paid_by_job) == job_ids and set(paid_by_job.values()) == {12}
            and len(aggregate_records) == expected_aggregate and len(aggregate_keys) == expected_aggregate
            and predictions.get("records_sha256") == canonical_sha256(records)
            and predictions.get("decision_records_sha256") == canonical_sha256(projection)
            and not record_errors
        )
        summary = load_json(base / "run_summary.json")
        summary_ok = (
            summary.get("schema_version") == "4.0" and summary.get("artifact_type") == "experiment-04-run-summary"
            and summary.get("phase") == spec.phase and tuple(summary.get("blocks", [])) == spec.blocks
            and set(summary.get("genomes", [])) == set(spec.candidates) and summary.get("planned_calls") == spec.expected_jobs
            and summary.get("model") == MODEL and summary.get("reasoning_effort") == REASONING_EFFORT
            and summary.get("public_condition_label") == PUBLIC_LABEL and summary.get("service_tier") == SERVICE_TIER
            and summary.get("concurrency") == MAX_CONCURRENCY
            and summary.get("common_prefix_sha256") == file_sha256(self.root / "prompts/COMMON_PREFIX.txt")
            and summary.get("answer_schema_sha256") == file_sha256(self.root / "prompts/answer_block.schema.json")
            and summary.get("prediction_records_sha256") == predictions.get("records_sha256")
        )
        valid = (
            not manifest_errors and dimensions_ok and binary_hash == EXPECTED_BINARY_SHA256
            and not ledger_errors and not artifact_errors and not concurrency_errors and peak <= MAX_CONCURRENCY
            and len(attempt_events) >= spec.expected_jobs
            and status_counter["valid_output"] == spec.expected_jobs
            and outcome_counter == Counter({"valid_output": spec.expected_jobs})
            and operational_ok and prediction_ok and summary_ok
        )
        detail = {
            "planned_identities": spec.expected_jobs, "manifest_identities": len(jobs),
            "unique_identities": len(job_ids), "identity_sha256": canonical_sha256(sorted(job_ids)),
            "blocks": list(spec.blocks), "candidates": len(spec.candidates), "methods": list(spec.methods),
            "attempts": len(attempt_events), "retry_attempts": len(attempt_events) - len(job_ids),
            "retried_jobs": sorted(retry_jobs), "attempt_statuses": dict(sorted(status_counter.items())),
            "terminal_outcomes": dict(sorted(outcome_counter.items())), "max_observed_concurrency": peak,
            "requested_configuration": {
                "model": MODEL, "reasoning_effort": REASONING_EFFORT, "public_label": PUBLIC_LABEL,
                "service_tier": SERVICE_TIER,
                "service_tier_evidence": "manifests and summaries request Standard; command has no non-default tier override",
                "timeout_seconds": TIMEOUT_SECONDS, "sandbox": "read-only", "ephemeral": True,
            },
            "preflight": preflight,
            "prediction_records": len(records), "aggregate_records": len(aggregate_records),
            "errors": {
                "manifests": bounded(manifest_errors), "dimensions": bounded(dimension_errors),
                "ledger": bounded(ledger_errors), "artifacts": bounded(artifact_errors),
                "concurrency": bounded(concurrency_errors), "predictions": bounded(record_errors),
                "prompt_set_mismatch": bounded(sorted(prompt_paths ^ expected_prompt_paths)),
            },
            "verified": valid,
        }
        self.hard(f"collection.{spec.name}", valid, detail)
        return detail, job_ids, reported_models

    def audit_collection(self, evolution: dict[str, Any]) -> dict[str, Any]:
        specs = self.run_specs(evolution)
        runs: dict[str, Any] = {}
        all_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        all_reported: list[Any] = []
        for spec in specs:
            detail, ids, reported = self.audit_run(spec)
            duplicate_ids.update(all_ids & ids)
            all_ids.update(ids)
            all_reported.extend(reported)
            runs[spec.name] = detail
        search_calls = sum(runs[f"search-round-{number:02d}"]["planned_identities"] for number in range(1, 9))
        validation_calls = runs["validation"]["planned_identities"]
        final_calls = sum(runs[name]["planned_identities"] for name in (
            "final-evolved-champion", "final-best-initial-founder", "final-generalist-vote10", "final-diversified-vote10",
        ))
        attempts = sum(int(row["attempts"]) for row in runs.values())
        retries = sum(int(row["retry_attempts"]) for row in runs.values())
        statuses = Counter()
        outcomes = Counter()
        for row in runs.values():
            statuses.update(row["attempt_statuses"])
            outcomes.update(row["terminal_outcomes"])
        nonempty_models = [str(item) for item in all_reported if isinstance(item, str) and item]
        conflicts = sorted(set(nonempty_models) - {MODEL})
        aggregate = {
            "registered_plan": EXPECTED_PLAN,
            "observed_planned_identities": {
                "search": search_calls, "validation": validation_calls, "final": final_calls,
                "total": search_calls + validation_calls + final_calls,
            },
            "unique_planned_identities": len(all_ids),
            "identity_sha256": canonical_sha256(sorted(all_ids)),
            "duplicate_identities": bounded(sorted(duplicate_ids)),
            "actual_model_attempts": attempts,
            "retry_attempts": retries,
            "attempt_statuses": dict(sorted(statuses.items())),
            "terminal_outcomes": dict(sorted(outcomes.items())),
            "provider_reported_model_values": sorted(set(nonempty_models)),
            "provider_model_reports_available": len(nonempty_models),
            "provider_model_reports_unavailable": len(all_reported) - len(nonempty_models),
        }
        aggregate_ok = (
            aggregate["observed_planned_identities"] == EXPECTED_PLAN
            and len(all_ids) == EXPECTED_PLAN["total"] and not duplicate_ids
            and attempts == 2_604 and retries == 4
            and statuses == Counter({"valid_output": 2_600, "schema_invalid": 4})
            and outcomes == Counter({"valid_output": 2_600})
        )
        self.hard("collection.aggregate_plan_and_retry_accounting", aggregate_ok, aggregate)
        self.hard("collection.provider_reported_model_no_conflict", not conflicts, {
            "requested_model": MODEL, "reported_values": sorted(set(nonempty_models)), "conflicts": conflicts,
        })
        self.warn("collection.provider_reported_model_identity", len(nonempty_models) == len(all_reported), {
            "status": "provider-reported model identity unavailable" if len(nonempty_models) != len(all_reported) else "available",
            "requested_model": MODEL,
            "reported_attempts": len(nonempty_models), "unreported_attempts": len(all_reported) - len(nonempty_models),
            "interpretation": "The frozen request configuration is verified, but an unreported provider identity is not claimed as observed.",
        })
        return {"aggregate": aggregate, "runs": runs, "verified": aggregate_ok and not conflicts}

    @staticmethod
    def _matrix_shape(path: Path, expected_ids: set[str], expected_blocks: set[str]) -> tuple[bool, dict[str, Any]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        ids = [str(row.get("case_id")) for row in rows]
        blocks = Counter(str(row.get("block")) for row in rows)
        ok = set(ids) == expected_ids and len(ids) == len(set(ids)) == len(expected_ids) and set(blocks) == expected_blocks and set(blocks.values()) == {12}
        return ok, {"rows": len(rows), "unique_case_ids": len(set(ids)), "blocks": dict(sorted(blocks.items()))}

    @staticmethod
    def _protocol_key(method: dict[str, Any]) -> list[int]:
        return [
            int(method.get("exact_cases", -1)), int(method.get("weakest_block_exact", -1)),
            -int(method.get("harmful_overrides", -1)), int(method.get("term_correct", -1)),
            int(method.get("format_valid", -1)),
        ]

    def audit_scoring(self) -> dict[str, Any]:
        score_details: dict[str, Any] = {}
        legacy_fields: list[str] = []
        score_errors: list[str] = []
        for number in range(1, 9):
            name = f"search-round-{number:02d}"
            prediction_path = self.root / f"runs/search/round-{number:02d}/predictions.json"
            answer_path = self.root / f"benchmark/hidden/search_R{number:02d}_answers.jsonl"
            result_dir = self.root / f"results/search/round-{number:02d}"
            candidate = load_json(self.root / f"genomes/round-{number:02d}-candidates.json")
            methods_expected = {str(item["genome_id"]) for item in candidate["genomes"]}
            expected_ids = set(self.block_cases[f"search-b{2 * number - 1:02d}"]) | set(self.block_cases[f"search-b{2 * number:02d}"])
            summary = load_json(result_dir / "summary.json")
            methods = summary.get("methods", {})
            matrix_ok, matrix_detail = self._matrix_shape(result_dir / "case_matrix.csv", expected_ids, {
                f"search-b{2 * number - 1:02d}", f"search-b{2 * number:02d}",
            })
            comparisons = load_json(result_dir / "comparisons.json")
            method_ok = set(methods) == methods_expected and all(
                row.get("calls") == 20 and row.get("completed_calls") == 20 and row.get("case_count") == 24
                and row.get("malformed_calls") == 0 and row.get("protocol_fitness_key") == self._protocol_key(row)
                for row in methods.values()
            )
            input_ok = (
                summary.get("inputs", {}).get("predictions_sha256") == file_sha256(prediction_path)
                and summary.get("inputs", {}).get("answers_sha256") == file_sha256(answer_path)
                and summary.get("inputs", {}).get("completed_jobs") == len(load_json(prediction_path).get("records", []))
            )
            ok = summary.get("n_cases") == 24 and method_ok and input_ok and matrix_ok and comparisons.get("comparisons") == [] and comparisons.get("primary") is None
            if not ok:
                score_errors.append(name)
            score_details[name] = {"n_cases": summary.get("n_cases"), "methods": len(methods), "calls_per_method": sorted_counts(row.get("calls") for row in methods.values()), "matrix": matrix_detail, "verified": ok}
        validation_prediction = self.root / "runs/validation/predictions.json"
        validation_answers = self.root / "benchmark/hidden/validation_answers.jsonl"
        validation_dir = self.root / "results/validation"
        validation_summary = load_json(validation_dir / "summary.json")
        validation_methods = validation_summary.get("methods", {})
        validation_ids = set().union(*(set(self.block_cases[f"validation-b{i:02d}"]) for i in range(1, 7)))
        validation_matrix_ok, validation_matrix = self._matrix_shape(validation_dir / "case_matrix.csv", validation_ids, {f"validation-b{i:02d}" for i in range(1, 7)})
        validation_comparisons = load_json(validation_dir / "comparisons.json")
        survivor_ids = {str(item["genome"]["genome_id"]) for item in load_json(self.root / "genomes/round-08-survivors.json")["slots"]}
        validation_ok = (
            validation_summary.get("n_cases") == 72 and set(validation_methods) == survivor_ids
            and all(row.get("calls") == 60 and row.get("completed_calls") == 60 and row.get("case_count") == 72 and row.get("malformed_calls") == 0 and row.get("protocol_fitness_key") == self._protocol_key(row) for row in validation_methods.values())
            and validation_summary.get("inputs", {}).get("predictions_sha256") == file_sha256(validation_prediction)
            and validation_summary.get("inputs", {}).get("answers_sha256") == file_sha256(validation_answers)
            and validation_matrix_ok and validation_comparisons.get("comparisons") == [] and validation_comparisons.get("primary") is None
        )
        if not validation_ok:
            score_errors.append("validation")
        score_details["validation"] = {"n_cases": validation_summary.get("n_cases"), "methods": len(validation_methods), "calls_per_method": sorted_counts(row.get("calls") for row in validation_methods.values()), "matrix": validation_matrix, "verified": validation_ok}
        merged_path = self.root / "runs/final/predictions.json"
        merged = load_json(merged_path)
        source_dirs = {
            "evolved_champion": "evolved_champion", "best_initial_founder": "best_initial_founder",
            "generalist_vote10": "generalist_vote10", "diversified_vote10": "diversified_vote10",
        }
        source_errors: list[str] = []
        for method, dirname in source_dirs.items():
            source_path = self.root / f"runs/final/{dirname}/predictions.json"
            source = load_json(source_path)
            declared = merged.get("sources", {}).get(method, {})
            if (
                declared.get("file") != "predictions.json" or declared.get("file_sha256") != file_sha256(source_path)
                or declared.get("source_records_sha256") != source.get("records_sha256")
                or declared.get("paid_call_count") != 80
            ):
                source_errors.append(method)
        final_records = merged.get("records", [])
        merge_ok = (
            merged.get("artifact_type") == "experiment-04-final-predictions"
            and merged.get("methods") == list(EXPECTED_FINAL_METHODS)
            and merged.get("paid_call_count") == 320 and merged.get("aggregate_record_count") == 384
            and len(final_records) == 4_224 and merged.get("records_sha256") == canonical_sha256(final_records)
            and not source_errors
        )
        final_dir = self.root / "results/final"
        final_summary = load_json(final_dir / "summary.json")
        final_methods = final_summary.get("methods", {})
        final_ids = set().union(*(set(self.block_cases[f"final-b{i:02d}"]) for i in range(1, 9)))
        final_matrix_ok, final_matrix = self._matrix_shape(final_dir / "case_matrix.csv", final_ids, {f"final-b{i:02d}" for i in range(1, 9)})
        authoritative_errors: list[str] = []
        for method, row in final_methods.items():
            if "fitness_key_without_hash" in row:
                legacy_fields.append(f"methods.{method}.fitness_key_without_hash")
            if row.get("protocol_fitness_key") != self._protocol_key(row):
                authoritative_errors.append(method)
        genome_scores = final_summary.get("genome_scores", [])
        genome_score_ok = len(genome_scores) == 2 and all(
            row.get("fitness_key_without_hash") == [
                row.get("exact_cases"), row.get("weakest_block_exact"), -row.get("harmful_overrides"),
                row.get("term_correct"), row.get("format_valid"),
            ]
            for row in genome_scores
        )
        final_summary_ok = (
            final_summary.get("n_cases") == 96 and set(final_methods) == set(EXPECTED_FINAL_METHODS)
            and all(row.get("calls") == 80 and row.get("completed_calls") == 80 and row.get("case_count") == 96 and row.get("malformed_calls") == 0 for row in final_methods.values())
            and final_summary.get("inputs", {}).get("predictions_sha256") == file_sha256(merged_path)
            and final_summary.get("inputs", {}).get("answers_sha256") == file_sha256(self.root / "benchmark/hidden/final_answers.jsonl")
            and not authoritative_errors and genome_score_ok and final_matrix_ok and merge_ok
        )
        comparisons = load_json(final_dir / "comparisons.json")
        rows = comparisons.get("comparisons", [])
        identities = tuple((row.get("left"), row.get("right")) for row in rows)
        comparison_ok = (
            identities == EXPECTED_COMPARISONS and len(rows) == 3 and comparisons.get("primary") == rows[0]
            and all(
                row.get("n") == 96 and row.get("both_correct", 0) + row.get("both_wrong", 0) + row.get("left_only_wins", 0) + row.get("right_only_wins", 0) == 96
                and row.get("mcnemar", {}).get("test") == "exact two-sided McNemar"
                and isinstance(row.get("ci95"), list) and len(row["ci95"]) == 2
                for row in rows
            )
        )
        if not final_summary_ok or not comparison_ok:
            score_errors.append("final")
        score_details["final"] = {
            "n_cases": final_summary.get("n_cases"), "methods": len(final_methods),
            "calls_per_method": sorted_counts(row.get("calls") for row in final_methods.values()),
            "matrix": final_matrix, "comparison_identities": [list(item) for item in identities],
            "merge_source_errors": source_errors, "authoritative_protocol_key_errors": authoritative_errors,
            "genome_scores_authoritative": genome_score_ok, "verified": final_summary_ok and comparison_ok,
        }
        self.hard("scoring.registered_sample_sizes_and_sources", not score_errors, {"errors": score_errors, "scores": score_details})
        self.hard("scoring.exact_three_registered_final_comparisons", comparison_ok, score_details["final"])
        self.warn("scoring.obsolete_four_part_fitness_key_without_hash", not legacy_fields, {
            "legacy_fields": legacy_fields,
            "status": "warning: obsolete convenience field retained" if legacy_fields else "absent",
            "authoritative_fields": ["methods.*.protocol_fitness_key", "genome_scores", "genome freezes", "selection receipts"],
            "interpretation": "The obsolete four-part convenience field is not used to audit fitness or selection.",
        })
        return {"scores": score_details, "legacy_fitness_fields": legacy_fields, "verified": not score_errors and comparison_ok}

    def audit_final_freeze(self) -> dict[str, Any]:
        champion_path = self.root / "genomes/champion-freeze.json"
        champion = load_json(champion_path)
        best_path = self.root / "genomes/best-founder-freeze.json"
        best = load_json(best_path)
        population_path = self.root / "genomes/round-08-survivors.json"
        validation_summary_path = self.root / "results/validation/summary.json"
        validation_matrix_path = self.root / "results/validation/case_matrix.csv"
        validation_predictions_path = self.root / "runs/validation/predictions.json"
        validation_answers_path = self.root / "benchmark/hidden/validation_answers.jsonl"
        validation_summary = load_json(validation_summary_path)
        population = load_json(population_path)
        entries = []
        for slot in population.get("slots", []):
            genome = slot["genome"]
            method = validation_summary["methods"][genome["genome_id"]]
            key = tuple(method["protocol_fitness_key"])
            entries.append((key, str(genome["genome_sha256"]), str(slot["slot_id"]), genome))
        best_key = max(item[0] for item in entries)
        expected_champion = min((item for item in entries if item[0] == best_key), key=lambda item: item[1])
        sources_ok = (
            champion.get("source_population_artifact_sha256") == population.get("artifact_sha256")
            and champion.get("source_population_file_sha256") == file_sha256(population_path)
            and champion.get("source_summary_file_sha256") == file_sha256(validation_summary_path)
            and champion.get("source_case_matrix_file_sha256") == file_sha256(validation_matrix_path)
            and champion.get("source_predictions_file_sha256") == file_sha256(validation_predictions_path)
            and champion.get("source_answers_file_sha256") == file_sha256(validation_answers_path)
            and champion.get("source_best_founder_artifact_sha256") == best.get("artifact_sha256")
            and champion.get("source_best_founder_file_sha256") == file_sha256(best_path)
        )
        selection_ok = (
            sealed_artifact_ok(champion) and champion.get("schema_version") == "experiment-04-champion-freeze-v1"
            and champion.get("freeze_status") == "validation_champion_frozen_before_hidden_final_answers"
            and champion.get("champion_slot_id") == expected_champion[2]
            and champion.get("champion_genome") == expected_champion[3]
            and champion.get("champion_fitness", {}).get("fitness_key") == list(expected_champion[0])
            and champion.get("best_founder_genome") == best.get("founder_genome")
            and sources_ok
        )
        packet_errors: list[str] = []
        for filename, role, expected_genome in (
            ("final-champion.json", "evolved_champion", champion.get("champion_genome")),
            ("final-founder.json", "best_initial_founder", champion.get("best_founder_genome")),
        ):
            packet = load_json(self.root / "genomes" / filename)
            if (
                packet.get("artifact_type") != "experiment-04-finalist-run-packet"
                or packet.get("source_champion_freeze") != "champion-freeze.json"
                or packet.get("source_champion_freeze_sha256") != file_sha256(champion_path)
                or packet.get("role") != role or packet.get("population") != [expected_genome]
            ):
                packet_errors.append(filename)
        detail = {
            "champion_genome_id": champion.get("champion_genome", {}).get("genome_id"),
            "champion_slot_id": champion.get("champion_slot_id"),
            "freeze_status": champion.get("freeze_status"),
            "source_hashes_verified": sources_ok,
            "final_packet_errors": packet_errors,
            "chronology_evidence": "The validation-only sealed freeze is content-addressed into both final run packets before their jobs are defined; hidden-final answers are absent from the freeze sources.",
        }
        self.hard("finalization.champion_frozen_pre_final", selection_ok and not packet_errors, detail)
        return {**detail, "verified": selection_ok and not packet_errors}

    def audit_analysis(self) -> dict[str, Any]:
        analysis_path = self.root / "results/analysis.json"
        analysis = load_json(analysis_path)
        experiment = analysis.get("experiment", {})
        operations = analysis.get("operations", {})
        registered = experiment.get("registered_logical_call_identities", experiment.get("registered_paid_calls"))
        actual_attempts = experiment.get("actual_model_attempts", operations.get("total_attempts"))
        operations_registered = operations.get("registered_call_identities", operations.get("planned_paid_calls"))
        clarified_keys_present = (
            "registered_logical_call_identities" in experiment
            and "actual_model_attempts" in experiment
            and "registered_call_identities" in operations
            and "total_attempts" in operations
        )
        source_errors = []
        for receipt in analysis.get("source_artifacts", []):
            path = self.root / str(receipt.get("path", ""))
            try:
                path.resolve().relative_to(self.root.resolve())
            except ValueError:
                source_errors.append(str(receipt.get("path")))
                continue
            if not path.is_file() or receipt.get("sha256") != file_sha256(path):
                source_errors.append(str(receipt.get("path")))
        analysis_ok = (
            analysis.get("schema_version") == "experiment-04-analysis-v1"
            and experiment.get("fixed_rounds") == 8 and experiment.get("early_stopping") is False
            and registered == 2_600 and actual_attempts == 2_604 and operations_registered == 2_600
            and operations.get("total_attempts") == 2_604 and operations.get("retry_attempts") == 4
            and operations.get("valid_output_jobs") == 2_600
            and experiment.get("model") == MODEL and experiment.get("provider_reasoning_effort") == REASONING_EFFORT
            and experiment.get("public_reasoning_label") == PUBLIC_LABEL and str(experiment.get("service_tier", "")).lower() == SERVICE_TIER
            and not source_errors and clarified_keys_present
        )
        build_script = self.root / "postprocessing/build_report.py"
        completed = subprocess.run(
            (sys.executable, str(build_script), "--check", "--images-dir", str(self.seed / "images")),
            cwd=self.root, text=True, capture_output=True, timeout=180, check=False,
        )
        artifact_paths = [
            self.root / "results/analysis.json", self.root / "results/analysis.md",
            self.seed / "images/final-exact-accuracy.svg", self.seed / "images/eight-round-trajectory.svg",
            self.seed / "images/decision-system-evolution.svg",
        ]
        deterministic = completed.returncode == 0 and all(path.is_file() for path in artifact_paths)
        detail = {
            "registered_logical_call_identities": registered, "actual_model_attempts": actual_attempts,
            "operations_registered_call_identities": operations_registered,
            "clarified_accounting_keys_present": clarified_keys_present,
            "source_receipts": len(analysis.get("source_artifacts", [])), "source_errors": bounded(source_errors),
            "byte_check": {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()},
            "artifacts": {path.relative_to(self.seed).as_posix(): file_sha256(path) if path.is_file() else None for path in artifact_paths},
        }
        self.hard("analysis.accounting_and_source_receipts", analysis_ok, detail)
        self.hard("analysis.deterministic_report_and_chart_byte_check", deterministic, detail["byte_check"] | {"artifacts": detail["artifacts"]})
        return {**detail, "verified": analysis_ok and deterministic}

    def audit_dependencies(self) -> dict[str, Any]:
        stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
        imports: dict[str, list[str]] = {}
        third_party: list[dict[str, str]] = []
        parse_errors: list[str] = []
        python_files = [path for path in self.release_files if path.suffix == ".py"]
        for path in python_files:
            rel = path.relative_to(self.seed).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, UnicodeError) as exc:
                parse_errors.append(f"{rel}: {exc}")
                continue
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names.add(node.module.split(".", 1)[0])
            imports[rel] = sorted(names)
            for name in names:
                if name not in stdlib:
                    third_party.append({"path": rel, "module": name})
        dependency_manifests = [
            path.relative_to(self.seed).as_posix() for path in self.release_files
            if path.name in {"requirements.txt", "pyproject.toml", "Pipfile", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock"}
        ]
        detail = {
            "python_files": len(python_files), "imports": imports,
            "non_stdlib_imports": third_party, "parse_errors": parse_errors,
            "external_package_manifests": dependency_manifests,
            "repository_local_frozen_adapters": [
                "scripts/generate_benchmark.py -> Experiment 03 generator",
                "scripts/run_jobs.py -> Experiment 03 runner",
                "scripts/score.py -> Experiment 03 scorer",
            ],
        }
        self.hard("dependencies.python_standard_library_only", not third_party and not parse_errors and not dependency_manifests, detail)
        return {**detail, "verified": not third_party and not parse_errors and not dependency_manifests}

    def audit_documentation(self) -> dict[str, Any]:
        expected = (
            "README.md", "SKILL.md", "experiment/README.md", "experiment/REPORT.md",
            "experiment/genomes/README.md",
        )
        missing = [name for name in expected if not (self.seed / name).is_file()]
        malformed: list[str] = []
        for name in expected:
            path = self.seed / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if not text.strip() or (name == "SKILL.md" and not (text.startswith("---\n") and "name:" in text and "description:" in text)):
                malformed.append(name)
        broken: list[dict[str, str]] = []
        markdown_paths = [path for path in self.release_files if path.suffix.lower() == ".md"]
        inline = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        reference = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.M)
        for path in markdown_paths:
            text = path.read_text(encoding="utf-8")
            targets = [match.group(1).strip().split()[0] for match in inline.finditer(text)]
            targets.extend(match.group(1).strip() for match in reference.finditer(text))
            for raw in targets:
                target = raw.strip("<>").strip("\"'")
                if not target or target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                    continue
                target = unquote(target.split("#", 1)[0].split("?", 1)[0])
                candidate = (path.parent / target).resolve()
                try:
                    candidate.relative_to(self.seed.resolve())
                    inside = True
                except ValueError:
                    inside = False
                exists = candidate.exists() or candidate == self.output.resolve()
                if not inside or not exists:
                    broken.append({"path": path.relative_to(self.seed).as_posix(), "target": raw, "reason": "escapes seed" if not inside else "missing"})
        self.warn("documentation.expected_release_documents", not missing, {
            "expected": list(expected), "missing": missing,
            "interpretation": "Missing publication wrappers are non-blocking while the evidence audit remains rerunnable.",
        })
        self.hard("documentation.present_documents_and_local_links", not malformed and not broken, {
            "markdown_files_checked": len(markdown_paths), "malformed_expected_documents": malformed,
            "broken_or_escaping_links": bounded(broken),
        })
        return {"expected": list(expected), "missing": missing, "malformed": malformed, "broken_links": broken, "verified_present_files": not malformed and not broken}

    def audit_privacy(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        for path in self.release_files:
            rel = path.relative_to(self.seed).as_posix()
            raw = path.read_bytes()
            if b"\0" in raw:
                findings.append({"path": rel, "kind": "binary_or_nul_file_not_scannable"})
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                findings.append({"path": rel, "kind": "non_utf8_file_not_scannable"})
                continue
            for kind, pattern in (
                ("secret_token", SECRET_TEXT), ("local_absolute_path", LOCAL_PATH),
                ("ephemeral_uuid", UUID_TEXT), ("thread_or_session_identifier", THREAD_TEXT),
            ):
                if pattern.search(text):
                    findings.append({"path": rel, "kind": kind})
            documents: list[Any] = []
            try:
                if path.suffix == ".json":
                    documents = [json.loads(text)]
                elif path.suffix == ".jsonl":
                    documents = [json.loads(line) for line in text.splitlines() if line.strip()]
            except json.JSONDecodeError as exc:
                findings.append({"path": rel, "kind": "invalid_json_release_file", "detail": str(exc)})
            stack = list(documents)
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    for key, child in value.items():
                        if SECRET_KEY.search(str(key)) and child not in (None, "", [], {}):
                            findings.append({"path": rel, "kind": "nonempty_secret_field", "key": str(key)})
                        if THREAD_KEY.search(str(key)) and child not in (None, "", [], {}):
                            findings.append({"path": rel, "kind": "thread_or_session_field", "key": str(key)})
                        stack.append(child)
                elif isinstance(value, list):
                    stack.extend(value)
        deduplicated = list({json.dumps(item, sort_keys=True): item for item in findings}.values())
        deduplicated.sort(key=lambda item: (str(item.get("path")), str(item.get("kind")), str(item.get("key", ""))))
        detail = {
            "scope": "exact Git-visible tracked plus intended-untracked release surface enumerated at audit start",
            "files_scanned": len(self.release_files),
            "bytes_scanned": sum(path.stat().st_size for path in self.release_files),
            "finding_count": len(deduplicated),
            "findings": bounded(deduplicated),
        }
        self.hard("privacy.secrets_local_paths_and_ephemeral_identifiers", not deduplicated, detail)
        return {**detail, "passed": not deduplicated}

    def run(self) -> dict[str, Any]:
        release_surface = self.section("release_surface", self.audit_release_surface)
        exclusions = self.section("release_exclusions", self.audit_exclusions)
        freeze = self.section("freeze", self.audit_freeze)
        benchmark = self.section("benchmark", self.audit_benchmark)
        evolution = self.section("evolution", self.audit_evolution)
        collection = self.section("collection", lambda: self.audit_collection(evolution))
        scoring = self.section("scoring", self.audit_scoring)
        finalization = self.section("finalization", self.audit_final_freeze)
        analysis = self.section("analysis", self.audit_analysis)
        dependencies = self.section("dependencies", self.audit_dependencies)
        documentation = self.section("documentation", self.audit_documentation)
        privacy = self.section("privacy", self.audit_privacy)
        counts = Counter(check["status"] for check in self.checks)
        status = "failed" if counts["failed"] else "passed"
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "summary": {"passed": counts["passed"], "failed": counts["failed"], "warnings": counts["warning"]},
            "release_surface": release_surface,
            "freeze": freeze,
            "benchmark": benchmark,
            "evolution": evolution,
            "collection": collection,
            "scoring": scoring,
            "finalization": finalization,
            "analysis": analysis,
            "dependencies": dependencies,
            "documentation": documentation,
            "privacy": privacy,
            "release_exclusions": {
                "audit": exclusions,
                "policy": [
                    "events.jsonl, process.json, stderr.txt, and transport_result.json are local CLI transport/process diagnostics",
                    ".run.lock, __pycache__, and Python bytecode are ephemeral local state",
                    "runs/smoke and runs/preflight are non-experimental development activity",
                    "sanitized command.json, output_schema.json, last_message.txt, result.json, and attempts.jsonl are release evidence",
                ],
            },
            "checks": self.checks,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=EXPERIMENT_DIR)
    parser.add_argument("--output", type=Path, default=Path("results/release-audit.json"))
    args = parser.parse_args()
    root = args.experiment_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    audit = Audit(root, output)
    try:
        report = audit.run()
    except Exception as exc:  # Last-resort machine-readable failure receipt.
        audit.hard("audit.unhandled_exception", False, audit.safe_error(exc))
        counts = Counter(check["status"] for check in audit.checks)
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "failed",
            "summary": {"passed": counts["passed"], "failed": counts["failed"], "warnings": counts["warning"]},
            "checks": audit.checks,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    try:
        output_label = output.resolve().relative_to(root).as_posix()
    except ValueError:
        output_label = "<outside-experiment-root>"
    print(json.dumps({"checks": len(report["checks"]), "output": output_label, "status": report["status"], "summary": report["summary"]}, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
