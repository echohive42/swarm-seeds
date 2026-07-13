#!/usr/bin/env python3
"""Build and validate the frozen Experiment 02 call schedule.

This module deliberately contains no provider client.  It describes the 400
planned call *slots*; infrastructure retry attempts live in ``attempts.jsonl``
and never create replacement slots.
"""

from __future__ import annotations

import argparse
import heapq
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "2.0"
EXPERIMENT_ID = "swarm-seeds-02"
MODEL = "gpt-5.6-luna"
BLOCK_IDS = tuple(f"B{i:02d}" for i in range(1, 5))
BLOCK_SIZE = 12
DEFAULT_SEED = "swarm-seeds-02-final-v1"
CONDITIONS = (("light", "Light reasoning", "low"), ("medium", "Medium reasoning", "medium"))

ROLE_PLAN = {
    "independent": (("solver", 20, "INDEPENDENT_SOLVER.txt", "solver", 0),),
    "swarm10": (
        ("proposer", 5, "SWARM10_PROPOSER.txt", "solver", 0),
        ("critic", 2, "SWARM10_CRITIC.txt", "critic", 1),
        ("verifier", 2, "SWARM10_VERIFIER.txt", "verifier", 2),
        ("judge", 1, "SWARM10_JUDGE.txt", "judge", 3),
    ),
    "tournament20": (
        ("explorer", 8, "TOURNAMENT20_EXPLORER.txt", "solver", 0),
        ("breaker", 4, "TOURNAMENT20_BREAKER.txt", "breaker", 1),
        ("verifier", 4, "TOURNAMENT20_VERIFIER.txt", "verifier", 2),
        ("synthesizer", 2, "TOURNAMENT20_SYNTHESIZER.txt", "synthesizer", 3),
        ("red_team", 1, "TOURNAMENT20_RED_TEAM.txt", "red_team", 4),
        ("judge", 1, "TOURNAMENT20_FINAL_JUDGE.txt", "judge", 5),
    ),
}

_GOLD_KEYS = {
    "answer_key", "answers", "correct_answer", "correct_answers", "correctness",
    "expected_answer", "expected_answers", "expected_continuation", "gold", "gold_answer",
    "gold_answers", "label", "reference_answer", "reference_answers", "score", "scores",
    "solution", "solutions", "target", "targets", "true_answer", "true_answers",
}


class ManifestError(ValueError):
    """Raised when a schedule or one of its frozen inputs is invalid."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def assert_no_correctness_data(value: Any, location: str = "case manifest") -> None:
    """Reject answer-key material from data that will be visible to collection."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if normalized in _GOLD_KEYS or normalized.startswith("gold_"):
                raise ManifestError(f"correctness field {key!r} is forbidden in {location}")
            assert_no_correctness_data(child, location)
    elif isinstance(value, list):
        for child in value:
            assert_no_correctness_data(child, location)


def _case_id(case: Any) -> str:
    if isinstance(case, str):
        value = case
    elif isinstance(case, dict):
        value = case.get("case_id", case.get("id"))
    else:
        value = None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("every final case must have a non-empty case_id (or id)")
    return value.strip()


def parse_case_blocks(data: Any, split: str = "final") -> dict[str, list[dict[str, Any]]]:
    """Accept common manifest shapes and return four ordered blocks of case objects."""
    assert_no_correctness_data(data)
    source: Any = data
    if isinstance(data, dict) and "block_id" in data and "cases" in data:
        source = [{"block_id": data["block_id"], "cases": data["cases"]}]
    elif isinstance(data, dict):
        for key in ("final_blocks", "blocks", "final", "cases"):
            if key in data:
                source = data[key]
                break

    blocks: dict[str, list[Any]] = {}
    if isinstance(source, dict):
        for block_id, cases in source.items():
            if block_id in BLOCK_IDS:
                if isinstance(cases, dict) and "cases" in cases:
                    cases = cases["cases"]
                if not isinstance(cases, list):
                    raise ManifestError(f"{block_id} must contain a list of cases")
                blocks[block_id] = cases
    elif isinstance(source, list) and all(
        isinstance(item, dict) and ("cases" in item or "case_ids" in item) for item in source
    ):
        for position, item in enumerate(source):
            block_id = item.get("block_id", BLOCK_IDS[position] if split == "final" else f"{split}-b01")
            blocks[block_id] = item.get("cases", item.get("case_ids"))
    elif isinstance(source, list):
        if any(isinstance(item, dict) and "block_id" in item for item in source):
            for item in source:
                if not isinstance(item, dict) or item.get("block_id") not in BLOCK_IDS:
                    raise ManifestError("case-level block_id values must be B01 through B04")
                blocks.setdefault(item["block_id"], []).append(item)
        else:
            expected_cases = 48 if split == "final" else 12
            if len(source) != expected_cases:
                raise ManifestError(f"the {split} manifest must contain exactly {expected_cases} cases")
            if split == "final":
                blocks = {block_id: source[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
                          for i, block_id in enumerate(BLOCK_IDS)}
            else:
                blocks = {f"{split}-b01": source}
    else:
        raise ManifestError("unsupported case manifest shape")

    expected_blocks = set(BLOCK_IDS) if split == "final" else {f"{split}-b01"}
    if set(blocks) != expected_blocks:
        raise ManifestError(f"{split} cases must define exactly {sorted(expected_blocks)}")
    normalized: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for block_id in sorted(expected_blocks):
        cases = blocks[block_id]
        if len(cases) != BLOCK_SIZE:
            raise ManifestError(f"{block_id} must contain exactly 12 cases")
        normalized[block_id] = []
        for raw_case in cases:
            case_id = _case_id(raw_case)
            if case_id in seen:
                raise ManifestError(f"duplicate case_id: {case_id}")
            seen.add(case_id)
            if isinstance(raw_case, dict):
                prefix = raw_case.get("prefix", raw_case.get("terms"))
                case = {"case_id": case_id}
                if prefix is not None:
                    case["prefix"] = prefix
            else:
                case = {"case_id": case_id}
            normalized[block_id].append(case)
    return normalized


def _identity(prompt_dir: Path, template_name: str) -> dict[str, Any]:
    names = ("COMMON_PREFIX.txt", template_name, "ROLE_CATALOG.json", "SCHEMAS.json")
    components = []
    for name in names:
        path = prompt_dir / name
        if not path.is_file():
            raise ManifestError(f"missing frozen prompt component: {path}")
        components.append({"path": f"prompts/{name}", "sha256": sha256_file(path)})
    digest = sha256_bytes(canonical_bytes(components))
    return {"template": f"prompts/{template_name}", "components": components,
            "identity_sha256": digest}


def _slot_prefix(role: str) -> str:
    return {"solver": "S", "proposer": "P", "critic": "C", "verifier": "V",
            "judge": "J", "explorer": "E", "breaker": "B", "synthesizer": "SY",
            "red_team": "RT"}[role]


def _group_key(call: dict[str, Any]) -> tuple[str, str, str]:
    return (call["block_id"], call["condition_label"], call["architecture"])


def schedule_calls(calls: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    """Create a deterministic fair topological schedule across all call groups.

    Each block, reasoning condition, and architecture group receives at most one
    call per round. A group's next stage becomes eligible as soon as all of its
    recorded dependencies finish, even while other groups remain in an earlier
    stage. This avoids globally draining one execution wave at a time.
    """

    by_id: dict[str, dict[str, Any]] = {}
    remaining: dict[str, set[str]] = {}
    dependents: dict[str, list[str]] = {}
    groups: set[tuple[str, str, str]] = set()
    for call in calls:
        call_id = call["call_id"]
        if call_id in by_id:
            raise ManifestError(f"duplicate call_id before scheduling: {call_id}")
        by_id[call_id] = call
        remaining[call_id] = set(call.get("dependency_call_ids", []))
        groups.add(_group_key(call))
    for call_id, dependencies in remaining.items():
        for dependency in dependencies:
            if dependency not in by_id:
                raise ManifestError(f"unknown dependency {dependency!r} for {call_id}")
            if _group_key(by_id[dependency]) != _group_key(by_id[call_id]):
                raise ManifestError(f"cross-group dependency {dependency!r} for {call_id}")
            dependents.setdefault(dependency, []).append(call_id)

    ready: dict[tuple[str, str, str], list[tuple[str, str]]] = {group: [] for group in groups}
    for call_id, dependencies in remaining.items():
        if not dependencies:
            key = sha256_bytes(f"{seed}\0call\0{call_id}".encode("utf-8"))
            heapq.heappush(ready[_group_key(by_id[call_id])], (key, call_id))
    group_order = sorted(
        groups,
        key=lambda group: sha256_bytes(
            f"{seed}\0group\0{group[0]}\0{group[1]}\0{group[2]}".encode("utf-8")
        ),
    )

    output: list[dict[str, Any]] = []
    scheduled: set[str] = set()
    while len(output) < len(calls):
        progressed = False
        for group in group_order:
            queue = ready[group]
            if not queue:
                continue
            _, call_id = heapq.heappop(queue)
            if call_id in scheduled:
                raise ManifestError(f"call scheduled twice: {call_id}")
            scheduled.add(call_id)
            output.append(by_id[call_id])
            progressed = True
            for child_id in sorted(dependents.get(call_id, [])):
                remaining[child_id].discard(call_id)
                if not remaining[child_id]:
                    key = sha256_bytes(f"{seed}\0call\0{child_id}".encode("utf-8"))
                    heapq.heappush(ready[_group_key(by_id[child_id])], (key, child_id))
        if not progressed:
            unresolved = sorted(set(by_id) - scheduled)
            raise ManifestError(f"dependency cycle or stalled schedule: {unresolved[:5]}")
    return output


def plan_execution_batches(calls: list[dict[str, Any]], concurrency: int) -> list[dict[str, Any]]:
    """Freeze the dependency-aware process batches for final collection."""
    if concurrency not in {10, 20}:
        raise ManifestError("selected final concurrency must be 10 or 20")
    by_id = {call["call_id"]: call for call in calls}
    completed: set[str] = set()
    remaining = set(by_id)
    batches: list[dict[str, Any]] = []
    while remaining:
        ready = sorted(
            (
                by_id[call_id]
                for call_id in remaining
                if set(by_id[call_id].get("dependency_call_ids", [])) <= completed
            ),
            key=lambda call: call["schedule_index"],
        )
        if not ready:
            raise ManifestError("cannot build execution batches from a cyclic dependency graph")
        selected = ready[:concurrency]
        batch_id = len(batches) + 1
        for call in selected:
            call["execution_batch"] = batch_id
            completed.add(call["call_id"])
            remaining.remove(call["call_id"])
        batches.append({"batch_id": batch_id, "call_ids": [call["call_id"] for call in selected]})
    return batches


def build_manifest(case_data: Any, prompt_dir: Path, seed: str = DEFAULT_SEED,
                   split: str = "final",
                   case_source_sha256: str | None = None,
                   runtime_config: dict[str, Any] | None = None,
                   runtime_config_sha256: str | None = None) -> dict[str, Any]:
    if split not in {"development", "calibration", "final"}:
        raise ManifestError(f"unsupported split: {split}")
    blocks = parse_case_blocks(case_data, split)
    identities: dict[str, dict[str, Any]] = {}
    for architecture, roles in ROLE_PLAN.items():
        for role, _, template, schema_name, _ in roles:
            identity_id = f"{architecture}.{role}"
            item = _identity(prompt_dir, template)
            item["output_schema"] = schema_name
            identities[identity_id] = item

    calls: list[dict[str, Any]] = []
    by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    block_ids = list(blocks)
    for block_id in block_ids:
        case_ids = [case["case_id"] for case in blocks[block_id]]
        for condition_label, public_label, effort in CONDITIONS:
            architectures = list(ROLE_PLAN)
            if split == "calibration":
                architectures = ["independent"]
            elif split == "development":
                architectures = ["independent"] if condition_label == "light" else ["independent", "tournament20"]
            for architecture in architectures:
                roles = ROLE_PLAN[architecture]
                group_key = (block_id, condition_label, architecture)
                group: list[dict[str, Any]] = []
                prior: list[dict[str, Any]] = []
                for role, count, _, schema_name, wave in roles:
                    current: list[dict[str, Any]] = []
                    effective_count = count
                    if split == "development" and architecture == "independent":
                        effective_count = 1
                    for index in range(1, effective_count + 1):
                        slot_id = f"{_slot_prefix(role)}{index:02d}"
                        call_id = f"{split}-{block_id.lower()}-{condition_label}-{architecture}-{slot_id.lower()}"
                        identity_id = f"{architecture}.{role}"
                        call = {
                            "call_id": call_id,
                            "block_id": block_id,
                            "case_ids": case_ids,
                            "condition_label": condition_label,
                            "public_reasoning_label": public_label,
                            "reasoning_effort": effort,
                            "model": MODEL,
                            "architecture": architecture,
                            "role": role,
                            "role_index": index,
                            "slot_id": slot_id,
                            "dependency_call_ids": [item["call_id"] for item in prior],
                            "execution_wave": wave,
                            "prompt_identity_id": identity_id,
                            "prompt_identity_sha256": identities[identity_id]["identity_sha256"],
                            "output_schema": schema_name,
                            "expected_case_responses": BLOCK_SIZE,
                        }
                        current.append(call)
                        group.append(call)
                    prior.extend(current)
                by_group[group_key] = group
                calls.extend(group)

    calls = schedule_calls(calls, seed)
    for index, call in enumerate(calls, 1):
        call["schedule_index"] = index
        call["schedule_key_sha256"] = sha256_bytes(f"{seed}\0{call['call_id']}".encode("utf-8"))

    expected_calls = {"development": 22, "calibration": 40, "final": 400}[split]
    expected_responses = expected_calls * BLOCK_SIZE
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "split": split,
        "model": MODEL,
        "schedule_seed": seed,
        "condition_mapping": {label: {"public_label": public, "reasoning_effort": effort}
                              for label, public, effort in CONDITIONS},
        "case_source_sha256": case_source_sha256 or sha256_bytes(canonical_bytes(case_data)),
        "blocks": [{"block_id": block_id,
                    "case_ids": [case["case_id"] for case in blocks[block_id]]}
                   for block_id in block_ids],
        "prompt_identities": identities,
        "planned_call_count": expected_calls,
        "planned_case_response_count": expected_responses,
        "max_infrastructure_retries": 2,
        "calls": calls,
    }
    if runtime_config is not None:
        if split != "final":
            raise ManifestError("runtime binding is allowed only on the final run manifest")
        selected = runtime_config.get("selected_final_concurrency")
        timeout = runtime_config.get("timeout_seconds")
        if selected not in {10, 20} or timeout != 300:
            raise ManifestError("runtime config must select concurrency 10 or 20 and timeout 300")
        if runtime_config.get("requested_model") != MODEL:
            raise ManifestError("runtime config requested model does not match the manifest")
        required_strings = (
            "codex_cli_version", "codex_binary_sha256", "runner_sha256",
            "calibration_report_sha256",
        )
        if any(not isinstance(runtime_config.get(key), str) or not runtime_config[key]
               for key in required_strings):
            raise ManifestError("runtime config is missing a required frozen identity")
        if not isinstance(runtime_config_sha256, str) or len(runtime_config_sha256) != 64:
            raise ManifestError("runtime config file SHA-256 is required")
        manifest.update({
            "selected_concurrency": selected,
            "timeout_seconds": timeout,
            "codex_cli_version": runtime_config["codex_cli_version"],
            "codex_binary_sha256": runtime_config["codex_binary_sha256"],
            "runner_sha256": runtime_config["runner_sha256"],
            "calibration_report_sha256": runtime_config["calibration_report_sha256"],
            "runtime_config_sha256": runtime_config_sha256,
            "disabled_features": list(runtime_config.get("disabled_features", [])),
        })
        manifest["execution_batches"] = plan_execution_batches(calls, selected)
    manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ManifestError("run manifest must be a JSON object")
    copy = dict(manifest)
    recorded_hash = copy.pop("manifest_sha256", None)
    if recorded_hash != sha256_bytes(canonical_bytes(copy)):
        raise ManifestError("manifest_sha256 does not match manifest contents")
    calls = manifest.get("calls")
    split = manifest.get("split")
    expected_calls = {"development": 22, "calibration": 40, "final": 400}.get(split)
    if expected_calls is None or not isinstance(calls, list) or len(calls) != expected_calls:
        raise ManifestError(f"run manifest has the wrong planned call count for {split}")
    if manifest.get("planned_call_count") != expected_calls or manifest.get("planned_case_response_count") != expected_calls * 12:
        raise ManifestError("frozen call/response totals do not match split plan")
    identities = manifest.get("prompt_identities", {})
    seen: set[str] = set()
    position: dict[str, int] = {}
    counts: dict[tuple[str, str, str, str], int] = {}
    for expected_index, call in enumerate(calls, 1):
        call_id = call.get("call_id")
        if not isinstance(call_id, str) or call_id in seen:
            raise ManifestError(f"missing or duplicate call_id: {call_id!r}")
        seen.add(call_id)
        position[call_id] = expected_index
        if call.get("schedule_index") != expected_index:
            raise ManifestError(f"non-contiguous schedule_index for {call_id}")
        if len(call.get("case_ids", [])) != BLOCK_SIZE:
            raise ManifestError(f"invalid block/case assignment for {call_id}")
        label, effort = call.get("condition_label"), call.get("reasoning_effort")
        if (label, effort) not in {("light", "low"), ("medium", "medium")}:
            raise ManifestError(f"invalid public/private condition mapping for {call_id}")
        if call.get("model") != MODEL:
            raise ManifestError(f"unexpected model for {call_id}")
        identity = identities.get(call.get("prompt_identity_id"))
        if not identity or identity.get("identity_sha256") != call.get("prompt_identity_sha256"):
            raise ManifestError(f"unfrozen prompt identity for {call_id}")
        key = (call["block_id"], label, call.get("architecture"), call.get("role"))
        counts[key] = counts.get(key, 0) + 1
    for call in calls:
        for dependency in call.get("dependency_call_ids", []):
            if dependency not in position or position[dependency] >= position[call["call_id"]]:
                raise ManifestError(f"dependency order violation for {call['call_id']}")
    for call in calls:
        same_group = [
            candidate for candidate in calls
            if _group_key(candidate) == _group_key(call)
            and candidate.get("execution_wave", 0) < call.get("execution_wave", 0)
        ]
        expected_dependencies = {candidate["call_id"] for candidate in same_group}
        if set(call.get("dependency_call_ids", [])) != expected_dependencies:
            raise ManifestError(f"exact dependency graph mismatch for {call['call_id']}")
    block_ids = [block["block_id"] for block in manifest.get("blocks", [])]
    for block in block_ids:
        for label, _, _ in CONDITIONS:
            expected = {
                ("independent", "solver"): 20,
                ("swarm10", "proposer"): 5, ("swarm10", "critic"): 2,
                ("swarm10", "verifier"): 2, ("swarm10", "judge"): 1,
                ("tournament20", "explorer"): 8, ("tournament20", "breaker"): 4,
                ("tournament20", "verifier"): 4, ("tournament20", "synthesizer"): 2,
                ("tournament20", "red_team"): 1, ("tournament20", "judge"): 1,
            }
            if split == "calibration":
                expected = {("independent", "solver"): 20}
            elif split == "development":
                expected = {("independent", "solver"): 1}
                if label == "medium":
                    expected.update({key: value for key, value in {
                        ("tournament20", "explorer"): 8, ("tournament20", "breaker"): 4,
                        ("tournament20", "verifier"): 4, ("tournament20", "synthesizer"): 2,
                        ("tournament20", "red_team"): 1, ("tournament20", "judge"): 1}.items()})
            for (architecture, role), count in expected.items():
                if counts.get((block, label, architecture, role)) != count:
                    raise ManifestError(f"wrong {architecture}/{role} count for {block}/{label}")
    if sum(len(call["case_ids"]) for call in calls) != expected_calls * 12:
        raise ManifestError("calls do not produce the frozen split response total")
    selected_concurrency = manifest.get("selected_concurrency")
    batches = manifest.get("execution_batches")
    if selected_concurrency is not None or batches is not None:
        if split != "final" or selected_concurrency not in {10, 20} or manifest.get("timeout_seconds") != 300:
            raise ManifestError("invalid final runtime binding")
        if not isinstance(batches, list) or not batches:
            raise ManifestError("runtime-bound final manifest requires execution batches")
        batch_by_call: dict[str, int] = {}
        for expected_batch, batch in enumerate(batches, 1):
            if batch.get("batch_id") != expected_batch:
                raise ManifestError("execution batch IDs must be contiguous")
            call_ids = batch.get("call_ids")
            if not isinstance(call_ids, list) or not 1 <= len(call_ids) <= selected_concurrency:
                raise ManifestError("invalid execution batch width")
            for call_id in call_ids:
                if call_id in batch_by_call or call_id not in position:
                    raise ManifestError("execution batches contain a duplicate or unknown call")
                batch_by_call[call_id] = expected_batch
        if set(batch_by_call) != seen:
            raise ManifestError("execution batches do not cover every final call exactly once")
        for call in calls:
            if call.get("execution_batch") != batch_by_call[call["call_id"]]:
                raise ManifestError(f"call execution_batch mismatch for {call['call_id']}")
            if any(batch_by_call[dependency] >= batch_by_call[call["call_id"]]
                   for dependency in call.get("dependency_call_ids", [])):
                raise ManifestError(f"dependency batch order violation for {call['call_id']}")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_case_file(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    if path.suffix.lower() == ".jsonl":
        data = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    else:
        data = json.loads(raw)
    return data, raw


def _self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prompts = root / "prompts"
        prompts.mkdir()
        names = {"COMMON_PREFIX.txt", "ROLE_CATALOG.json", "SCHEMAS.json"}
        for roles in ROLE_PLAN.values():
            names.update(role[2] for role in roles)
        for name in names:
            (prompts / name).write_text(f"frozen {name}\n", encoding="utf-8")
        cases = [{"case_id": f"RW-{index:03d}", "prefix": ["1", "2"]} for index in range(1, 49)]
        first = build_manifest(cases, prompts, "test-seed")
        second = build_manifest(cases, prompts, "test-seed")
        assert canonical_bytes(first) == canonical_bytes(second)
        assert len(first["calls"]) == 400
        assert sum(call["expected_case_responses"] for call in first["calls"]) == 4800
        assert {call["reasoning_effort"] for call in first["calls"] if call["condition_label"] == "light"} == {"low"}
        positions = {call["call_id"]: index for index, call in enumerate(first["calls"])}
        assert all(
            positions[dependency] < positions[call["call_id"]]
            for call in first["calls"]
            for dependency in call["dependency_call_ids"]
        )
        first_round = first["calls"][:24]
        assert {call["block_id"] for call in first_round} == set(BLOCK_IDS)
        assert {call["condition_label"] for call in first_round} == {"light", "medium"}
        assert {call["architecture"] for call in first_round} == set(ROLE_PLAN)
        last_wave_zero = max(index for index, call in enumerate(first["calls"]) if call["execution_wave"] == 0)
        first_later_wave = min(index for index, call in enumerate(first["calls"]) if call["execution_wave"] > 0)
        assert first_later_wave < last_wave_zero
        validate_manifest(first)
        tampered = json.loads(json.dumps(first))
        target = next(call for call in tampered["calls"] if call["dependency_call_ids"])
        target["dependency_call_ids"] = []
        tampered.pop("manifest_sha256")
        tampered["manifest_sha256"] = sha256_bytes(canonical_bytes(tampered))
        try:
            validate_manifest(tampered)
        except ManifestError:
            pass
        else:
            raise AssertionError("manifest validation accepted a deleted dependency graph")
        twelve = cases[:12]
        assert len(build_manifest(twelve, prompts, split="development")["calls"]) == 22
        assert len(build_manifest(twelve, prompts, split="calibration")["calls"]) == 40
        terms = [{"case_id": f"X{i:02d}", "terms": ["1", "2"], "family": "not-forwarded"}
                 for i in range(1, 13)]
        parsed = parse_case_blocks(terms, "development")
        assert parsed["development-b01"][0] == {"case_id": "X01", "prefix": ["1", "2"]}
        bad = list(cases)
        bad[0] = {"case_id": "RW-001", "gold_answer": ["3"]}
        try:
            build_manifest(bad, prompts)
        except ManifestError:
            pass
        else:
            raise AssertionError("correctness firewall accepted a gold answer")
    print("run_manifest.py self-test: PASS")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate Experiment 02's deterministic 400-call schedule.")
    parser.add_argument("--self-test", action="store_true", help="run standard-library unit smoke tests and exit")
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser("build", help="build a new run manifest from 48 frozen final cases")
    build.add_argument("--cases", type=Path, required=True, help="JSON case/block manifest (must not contain answers)")
    build.add_argument("--split", choices=("development", "calibration", "final"), default="final",
                       help="select the preregistered 22-, 40-, or 400-call plan")
    build.add_argument("--prompt-dir", type=Path, required=True, help="directory containing frozen prompt components")
    build.add_argument("--output", type=Path, required=True, help="new run_manifest.json path")
    build.add_argument("--seed", default=DEFAULT_SEED, help="recorded deterministic schedule seed")
    build.add_argument("--runtime-config", type=Path,
                       help="final-only JSON binding calibrated concurrency, CLI, and runner identities")
    build.add_argument("--overwrite", action="store_true", help="replace an existing output intentionally")
    check = sub.add_parser("validate", help="validate counts, hashes, identities, and dependency order")
    check.add_argument("manifest", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.command == "build":
            if args.output.exists() and not args.overwrite:
                raise ManifestError(f"refusing to overwrite {args.output}; pass --overwrite intentionally")
            data, raw = load_case_file(args.cases)
            runtime_config = json.loads(args.runtime_config.read_text(encoding="utf-8")) \
                if args.runtime_config else None
            runtime_sha = sha256_file(args.runtime_config) if args.runtime_config else None
            manifest = build_manifest(
                data, args.prompt_dir, args.seed, args.split, sha256_bytes(raw),
                runtime_config, runtime_sha,
            )
            atomic_write_json(args.output, manifest)
            print(f"wrote {len(manifest['calls'])} calls / {manifest['planned_case_response_count']} case responses to {args.output}")
            return 0
        if args.command == "validate":
            validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
            print(f"valid: {args.manifest}")
            return 0
        parser.print_help()
        return 2
    except (ManifestError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
