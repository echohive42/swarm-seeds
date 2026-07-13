#!/usr/bin/env python3
"""Build anonymous, deterministic packets for Swarm Seeds experiment 02.

The script uses only Python standard-library modules. Raw bundle format:

{
  "packet_version": "2.0",
  "block_id": "final-b01",
  "case_ids": ["F001", "... exactly 12 IDs ..."],
  "workers": [
    {
      "slot_id": "P1",
      "transport_status": "ok",
      "raw_text": "{... one solver, proposer, or explorer response ...}"
    }
  ]
}

Private fields may exist on worker records, but only the frozen anonymous fields
are copied downstream.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Iterable

from validate_outputs import (
    DECIMAL_RE,
    EXPECTED_CASE_COUNT,
    SCHEMA_VERSION,
    StrictJSONError,
    classify_attempt,
    parse_json_strict,
    validate_result_item,
)


DEFAULT_CONTEXT_LIMIT = 60_000
OUTPUT_SCHEMA_STAGES = ("solver", "critic", "breaker", "verifier", "synthesizer", "red_team", "judge")
PROSE_LIMITS = {
    "rule_summary": 180,
    "check_summary": 180,
    "representative_rule": 180,
    "representative_check": 120,
    "issue": 140,
    "reason": 140,
    "summary": 180,
    "decision_basis": 180,
}
LIST_LIMITS = {
    "supported_candidates": 2,
    "rejections": 3,
    "ranked_candidates": 3,
    "attacks": 2,
}
NEVER_DROP_FIELDS = {
    "schema_version",
    "packet_version",
    "block_id",
    "case_id",
    "candidate_id",
    "member_candidate_ids",
    "invalid_candidate_ids",
    "cluster_id",
    "answer",
    "alternative_answer",
    "recommended_answer",
    "champion",
    "runner_up",
    "support_count",
    "invalid_count",
    "confidence",
    "mean_confidence",
    "score",
    "verdict",
    "prefix_fit",
    "issue_code",
    "status",
}


def _stable_digest(*parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _rng(seed: str, *context: str) -> random.Random:
    value = int(_stable_digest(seed, *context), 16)
    return random.Random(value)


def deterministic_shuffle(values: Iterable[Any], seed: str, *context: str) -> list[Any]:
    output = list(values)
    _rng(seed, *context).shuffle(output)
    return output


def _opaque_id(prefix: str, seed: str, *parts: str) -> str:
    return prefix + _stable_digest(seed, *parts)[:10].upper()


def _validate_bundle(bundle: Any, expected_workers: int | None = None) -> tuple[str, list[str], list[dict[str, Any]]]:
    if not isinstance(bundle, dict):
        raise ValueError("raw bundle must be an object")
    block_id = bundle.get("block_id")
    case_ids = bundle.get("case_ids")
    workers = bundle.get("workers")
    if not isinstance(block_id, str) or not block_id:
        raise ValueError("raw bundle block_id must be a non-empty string")
    if not isinstance(case_ids, list) or len(case_ids) != EXPECTED_CASE_COUNT:
        raise ValueError(f"raw bundle case_ids must contain exactly {EXPECTED_CASE_COUNT} IDs")
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ValueError("every case ID must be a non-empty string")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("raw bundle case_ids must be unique")
    if not isinstance(workers, list) or not workers:
        raise ValueError("raw bundle workers must be a non-empty array")
    if expected_workers is not None and len(workers) != expected_workers:
        raise ValueError(f"expected {expected_workers} workers, got {len(workers)}")
    slots: set[str] = set()
    for worker in workers:
        if not isinstance(worker, dict):
            raise ValueError("each worker must be an object")
        slot_id = worker.get("slot_id")
        if not isinstance(slot_id, str) or not slot_id:
            raise ValueError("each worker requires a private non-empty slot_id")
        if slot_id in slots:
            raise ValueError(f"duplicate private slot_id: {slot_id}")
        slots.add(slot_id)
    return block_id, list(case_ids), list(workers)


def _salvage_stage_items(
    worker: dict[str, Any],
    block_id: str,
    case_ids: list[str],
    schema_name: str,
) -> dict[str, dict[str, Any] | None]:
    """Retain schema-valid cases from a partially invalid model response."""

    attempt = {
        "transport_status": worker.get("transport_status", worker.get("status", "ok")),
        "schema": schema_name,
        "raw_text": worker.get("raw_text", worker.get("response_text")),
        "expected_case_ids": case_ids,
        "expected_block_id": block_id,
    }
    classification = classify_attempt(attempt)
    document = None
    validation = classification.get("validation")
    if isinstance(validation, dict):
        document = validation.get("document")
    if classification["classification"] == "infrastructure_failure":
        return {case_id: None for case_id in case_ids}
    if not isinstance(document, dict) or document.get("block_id") != block_id:
        return {case_id: None for case_id in case_ids}
    results = document.get("results")
    if not isinstance(results, list):
        return {case_id: None for case_id in case_ids}

    grouped: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    for item in results:
        if isinstance(item, dict) and item.get("case_id") in grouped:
            grouped[item["case_id"]].append(item)
    output: dict[str, dict[str, Any] | None] = {}
    for case_id in case_ids:
        items = grouped[case_id]
        if len(items) != 1 or validate_result_item(items[0], schema_name, f"$.results[{case_id!r}]"):
            output[case_id] = None
        else:
            output[case_id] = items[0]
    return output


def _salvage_solver_items(
    worker: dict[str, Any],
    block_id: str,
    case_ids: list[str],
) -> dict[str, dict[str, Any] | None]:
    return _salvage_stage_items(worker, block_id, case_ids, "solver")


def anonymize_bundle(bundle: Any, seed: str, expected_workers: int | None = None) -> dict[str, Any]:
    """Construct shuffled anonymous candidate packets from private raw outputs."""

    block_id, case_ids, workers = _validate_bundle(bundle, expected_workers)
    cases: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    seen_ids: set[str] = set()
    for worker in workers:
        slot_id = worker["slot_id"]
        salvaged = _salvage_solver_items(worker, block_id, case_ids)
        for case_id in case_ids:
            candidate_id = _opaque_id("K", seed, block_id, case_id, slot_id)
            if candidate_id in seen_ids:
                raise RuntimeError("opaque candidate ID collision")
            seen_ids.add(candidate_id)
            item = salvaged[case_id]
            if item is None:
                candidate = {"candidate_id": candidate_id, "status": "invalid"}
            else:
                candidate = {
                    "candidate_id": candidate_id,
                    "answer": list(item["answer"]),
                    "confidence": float(item["confidence"]),
                    "rule_summary": item["rule_summary"],
                    "check_summary": item["check_summary"],
                    "status": "valid",
                }
            cases[case_id].append(candidate)
    return {
        "packet_version": SCHEMA_VERSION,
        "block_id": block_id,
        "cases": [
            {
                "case_id": case_id,
                "candidates": deterministic_shuffle(
                    sorted(cases[case_id], key=lambda candidate: candidate["candidate_id"]),
                    seed,
                    "candidate-order",
                    block_id,
                    case_id,
                ),
            }
            for case_id in case_ids
        ],
    }


def anonymize_report_bundle(
    bundle: Any,
    seed: str,
    schema_name: str,
    expected_workers: int | None = None,
) -> dict[str, Any]:
    """Strip worker identity from downstream critic, breaker, or judge reports."""

    if schema_name not in {"critic", "breaker", "verifier", "synthesizer", "red_team", "judge"}:
        raise ValueError("report schema must be critic, breaker, verifier, synthesizer, red_team, or judge")
    block_id, case_ids, workers = _validate_bundle(bundle, expected_workers)
    neutral_synthesizer_ids: dict[str, str] = {}
    if schema_name == "synthesizer":
        if len(workers) != 2:
            raise ValueError("synthesizer report bundle must contain exactly two workers")
        neutral_order = deterministic_shuffle(
            sorted(workers, key=lambda worker: worker["slot_id"]),
            seed,
            "synthesizer-neutral-map",
            block_id,
        )
        neutral_synthesizer_ids = {
            worker["slot_id"]: f"SY{index}"
            for index, worker in enumerate(neutral_order, 1)
        }
    cases: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    seen_ids: set[tuple[str, str]] = set()
    for worker in workers:
        slot_id = worker["slot_id"]
        salvaged = _salvage_stage_items(worker, block_id, case_ids, schema_name)
        for case_id in case_ids:
            report_id = (
                neutral_synthesizer_ids[slot_id]
                if schema_name == "synthesizer"
                else _opaque_id("R", seed, schema_name, block_id, case_id, slot_id)
            )
            identity = (case_id, report_id)
            if identity in seen_ids:
                raise RuntimeError("opaque report ID collision")
            seen_ids.add(identity)
            item = salvaged[case_id]
            if item is None:
                report = {"report_id": report_id, "status": "invalid"}
            else:
                report = {"report_id": report_id, "status": "valid"}
                for key, value in item.items():
                    if key != "case_id":
                        report[key] = copy.deepcopy(value)
            cases[case_id].append(report)
    return {
        "packet_version": SCHEMA_VERSION,
        "block_id": block_id,
        "cases": [
            {
                "case_id": case_id,
                "reports": deterministic_shuffle(
                    sorted(cases[case_id], key=lambda report: report["report_id"]),
                    seed,
                    "report-order",
                    schema_name,
                    block_id,
                    case_id,
                ),
            }
            for case_id in case_ids
        ],
    }


def cluster_anonymous_packet(packet: Any, seed: str) -> dict[str, Any]:
    """Cluster candidates only when all five decimal strings match exactly."""

    if not isinstance(packet, dict) or packet.get("packet_version") != SCHEMA_VERSION:
        raise ValueError("anonymous packet must have packet_version 2.0")
    block_id = packet.get("block_id")
    cases = packet.get("cases")
    if not isinstance(block_id, str) or not isinstance(cases, list):
        raise ValueError("anonymous packet requires block_id and cases")
    output_cases: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not isinstance(case.get("candidates"), list):
            raise ValueError("malformed anonymous case packet")
        case_id = case["case_id"]
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        invalid_count = 0
        invalid_candidate_ids: list[str] = []
        for candidate in case["candidates"]:
            if not isinstance(candidate, dict) or candidate.get("status") != "valid":
                invalid_count += 1
                if isinstance(candidate, dict) and isinstance(candidate.get("candidate_id"), str):
                    invalid_candidate_ids.append(candidate["candidate_id"])
                continue
            answer = candidate.get("answer")
            if (
                not isinstance(answer, list)
                or len(answer) != 5
                or any(not isinstance(term, str) or DECIMAL_RE.fullmatch(term) is None for term in answer)
            ):
                invalid_count += 1
                if isinstance(candidate.get("candidate_id"), str):
                    invalid_candidate_ids.append(candidate["candidate_id"])
                continue
            groups.setdefault(tuple(answer), []).append(candidate)
        clusters: list[dict[str, Any]] = []
        for answer_tuple, members in groups.items():
            representative = sorted(members, key=lambda item: (-float(item["confidence"]), item["candidate_id"]))[0]
            cluster_id = _opaque_id("A", seed, block_id, case_id, json.dumps(answer_tuple, separators=(",", ":")))
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "member_candidate_ids": sorted(member["candidate_id"] for member in members),
                    "answer": list(answer_tuple),
                    "support_count": len(members),
                    "mean_confidence": round(sum(float(item["confidence"]) for item in members) / len(members), 6),
                    "representative_rule": representative["rule_summary"],
                    "representative_check": representative["check_summary"],
                }
            )
        output_cases.append(
            {
                "case_id": case_id,
                "clusters": deterministic_shuffle(
                    sorted(clusters, key=lambda cluster: cluster["cluster_id"]),
                    seed,
                    "cluster-order",
                    block_id,
                    case_id,
                ),
                "invalid_count": invalid_count,
                "invalid_candidate_ids": sorted(invalid_candidate_ids),
            }
        )
    return {"packet_version": SCHEMA_VERSION, "block_id": block_id, "cases": output_cases}


def _minified_length(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _apply_base_caps(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key in PROSE_LIMITS and isinstance(child, str):
                value[key] = child[: PROSE_LIMITS[key]]
            elif key in LIST_LIMITS and isinstance(child, list):
                del child[LIST_LIMITS[key] :]
            _apply_base_caps(value[key])
    elif isinstance(value, list):
        for child in value:
            _apply_base_caps(child)


def _cap_all_prose(value: Any, maximum: int) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in PROSE_LIMITS and isinstance(child, str):
                value[key] = child[:maximum]
            else:
                _cap_all_prose(child, maximum)
    elif isinstance(value, list):
        for child in value:
            _cap_all_prose(child, maximum)


def preflight_and_compact(packet: Any, limit: int = DEFAULT_CONTEXT_LIMIT) -> tuple[Any, dict[str, Any]]:
    """Deterministically compact prose while preserving all decision fields."""

    if limit <= 0:
        raise ValueError("context limit must be positive")
    compacted = copy.deepcopy(packet)
    before = _minified_length(compacted)
    _apply_base_caps(compacted)
    applied_caps: list[int] = []
    if _minified_length(compacted) > limit:
        for maximum in (120, 80, 40, 0):
            _cap_all_prose(compacted, maximum)
            applied_caps.append(maximum)
            if _minified_length(compacted) <= limit:
                break
    after = _minified_length(compacted)
    if after > limit:
        raise ValueError(
            f"packet remains {after} characters after safe compaction, above {limit}; "
            "refusing to drop IDs, answers, confidence, scores, or verdicts"
        )
    return compacted, {
        "limit_characters": limit,
        "before_characters": before,
        "after_characters": after,
        "compacted": before != after,
        "progressive_prose_caps": applied_caps,
        "preserved_field_classes": sorted(NEVER_DROP_FIELDS),
    }


def shuffle_packet_lists(packet: Any, seed: str, keys: set[str]) -> Any:
    """Shuffle selected packet arrays with stable path-derived seeds."""

    output = copy.deepcopy(packet)

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys and isinstance(child, list):
                    value[key] = deterministic_shuffle(child, seed, "generic-shuffle", *path, key)
                    child = value[key]
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(output, ("$",))
    return output


def extract_stage_schema(catalog: Any, stage: str) -> dict[str, Any]:
    """Extract one Codex CLI compatible root schema from SCHEMAS.json."""

    if stage not in OUTPUT_SCHEMA_STAGES:
        raise ValueError(f"unknown output stage {stage!r}; expected one of {OUTPUT_SCHEMA_STAGES}")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("$defs"), dict) or not isinstance(catalog.get("schemas"), dict):
        raise ValueError("schema catalog requires $defs and schemas objects")
    aliases = {"breaker": "critic"}
    source_name = aliases.get(stage, stage)
    source = catalog["schemas"].get(source_name)
    if not isinstance(source, dict):
        raise ValueError(f"schema catalog has no concrete schema for {source_name}")
    root: dict[str, Any] = {
        "$schema": catalog.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$id": f"https://github.com/echohive42/swarm-seeds/02-hard-sequence-scaling/{stage}-output-v2.json",
        "title": f"Swarm Seeds 02 {stage} output",
        "$defs": copy.deepcopy(catalog["$defs"]),
    }
    root.update(copy.deepcopy(source))
    if "type" not in root or "properties" not in root:
        raise ValueError(f"extracted {stage} schema is not a concrete root object schema")
    return root


def _read_json(path: Path) -> Any:
    value, _ = parse_json_strict(path.read_text(encoding="utf-8"))
    return value


def _write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _valid_solver_output(case_ids: list[str], block_id: str, answer_offset: int = 0) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "block_id": block_id,
        "results": [
            {
                "case_id": case_id,
                "answer": [str(answer_offset + index + step) for step in range(5)],
                "confidence": 0.5 + answer_offset / 100,
                "rule_summary": "Add one for each requested term.",
                "check_summary": "Full prefix checked.",
            }
            for index, case_id in enumerate(case_ids)
        ],
    }


def _valid_critic_output(case_ids: list[str], block_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "block_id": block_id,
        "results": [
            {
                "case_id": case_id,
                "supported_candidates": ["A1"],
                "rejections": [],
                "alternative_answer": None,
                "confidence": 0.6,
                "summary": "One candidate survives the exact check.",
            }
            for case_id in case_ids
        ],
    }


def _valid_synthesizer_output(case_ids: list[str], block_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "block_id": block_id,
        "results": [
            {
                "case_id": case_id,
                "champion": {"candidate_id": "A1", "answer": ["1", "2", "3", "4", "5"]},
                "runner_up": {"candidate_id": "A2", "answer": ["2", "3", "4", "5", "6"]},
                "confidence": 0.7,
                "decision_basis": "The champion has the strongest exact prefix fit.",
            }
            for case_id in case_ids
        ],
    }


def _self_test() -> dict[str, Any]:
    case_ids = [f"F{i:03d}" for i in range(1, 13)]
    block_id = "final-b01"
    first = _valid_solver_output(case_ids, block_id, 0)
    second = _valid_solver_output(case_ids, block_id, 0)
    third = _valid_solver_output(case_ids, block_id, 20)
    partial = _valid_solver_output(case_ids, block_id, 0)
    partial["results"][0]["answer"] = ["1"]
    bundle = {
        "packet_version": SCHEMA_VERSION,
        "block_id": block_id,
        "case_ids": case_ids,
        "workers": [
            {"slot_id": "P1", "attempt_id": "private-a", "model": "private", "transport_status": "ok", "raw_text": json.dumps(first)},
            {"slot_id": "P2", "attempt_id": "private-b", "model": "private", "transport_status": "ok", "raw_text": json.dumps(second)},
            {"slot_id": "P3", "attempt_id": "private-c", "model": "private", "transport_status": "ok", "raw_text": json.dumps(third)},
            {"slot_id": "P4", "attempt_id": "private-d", "model": "private", "transport_status": "ok", "raw_text": json.dumps(partial)},
        ],
    }
    anonymous = anonymize_bundle(bundle, "frozen-seed", expected_workers=4)
    assert anonymous == anonymize_bundle(bundle, "frozen-seed", expected_workers=4)
    serialized = json.dumps(anonymous)
    for private_value in ("slot_id", "attempt_id", "private-a", "private-b", '"P1"', '"P2"', '"P3"', '"P4"'):
        assert private_value not in serialized
    assert len(anonymous["cases"]) == 12
    assert len(anonymous["cases"][0]["candidates"]) == 4
    assert sum(candidate["status"] == "invalid" for candidate in anonymous["cases"][0]["candidates"]) == 1
    assert sum(candidate["status"] == "invalid" for candidate in anonymous["cases"][1]["candidates"]) == 0

    clusters = cluster_anonymous_packet(anonymous, "frozen-seed")
    first_supports = sorted(cluster["support_count"] for cluster in clusters["cases"][0]["clusters"])
    assert first_supports == [1, 2]
    assert clusters["cases"][0]["invalid_count"] == 1
    assert len(clusters["cases"][0]["invalid_candidate_ids"]) == 1
    assert all(
        cluster["support_count"] == len(cluster["member_candidate_ids"])
        for case in clusters["cases"]
        for cluster in case["clusters"]
    )
    assert {
        candidate["candidate_id"]
        for candidate in anonymous["cases"][0]["candidates"]
    } == {
        candidate_id
        for cluster in clusters["cases"][0]["clusters"]
        for candidate_id in cluster["member_candidate_ids"]
    } | set(clusters["cases"][0]["invalid_candidate_ids"])
    assert all(len(cluster["answer"]) == 5 for case in clusters["cases"] for cluster in case["clusters"])

    critic_text = json.dumps(_valid_critic_output(case_ids, block_id))
    report_bundle = {
        "block_id": block_id,
        "case_ids": case_ids,
        "workers": [
            {"slot_id": "C1", "private_note": "must not leak", "transport_status": "ok", "raw_text": critic_text},
            {"slot_id": "C2", "private_note": "must not leak", "transport_status": "ok", "raw_text": critic_text},
        ],
    }
    reports = anonymize_report_bundle(report_bundle, "report-seed", "critic", expected_workers=2)
    report_text = json.dumps(reports)
    assert '"C1"' not in report_text and '"C2"' not in report_text and "private_note" not in report_text
    assert all(len(case["reports"]) == 2 for case in reports["cases"])

    synthesizer_text = json.dumps(_valid_synthesizer_output(case_ids, block_id))
    synthesizer_bundle = {
        "block_id": block_id,
        "case_ids": case_ids,
        "workers": [
            {"slot_id": "PRIVATE-SIMPLE", "role_lens": "hidden", "transport_status": "ok", "raw_text": synthesizer_text},
            {"slot_id": "PRIVATE-ROBUST", "role_lens": "hidden", "transport_status": "ok", "raw_text": synthesizer_text},
        ],
    }
    synthesizer_reports = anonymize_report_bundle(
        synthesizer_bundle,
        "synthesizer-seed",
        "synthesizer",
        expected_workers=2,
    )
    assert synthesizer_reports == anonymize_report_bundle(
        synthesizer_bundle,
        "synthesizer-seed",
        "synthesizer",
        expected_workers=2,
    )
    reversed_synthesizer_bundle = copy.deepcopy(synthesizer_bundle)
    reversed_synthesizer_bundle["workers"].reverse()
    assert synthesizer_reports == anonymize_report_bundle(
        reversed_synthesizer_bundle,
        "synthesizer-seed",
        "synthesizer",
        expected_workers=2,
    )
    synth_serialized = json.dumps(synthesizer_reports)
    assert "PRIVATE-SIMPLE" not in synth_serialized and "PRIVATE-ROBUST" not in synth_serialized
    assert "role_lens" not in synth_serialized
    assert all({report["report_id"] for report in case["reports"]} == {"SY1", "SY2"} for case in synthesizer_reports["cases"])

    bloated = copy.deepcopy(clusters)
    for case in bloated["cases"]:
        for cluster in case["clusters"]:
            cluster["representative_rule"] = "x" * 10_000
            cluster["representative_check"] = "y" * 10_000
    compacted, report = preflight_and_compact(bloated, DEFAULT_CONTEXT_LIMIT)
    assert _minified_length(compacted) <= DEFAULT_CONTEXT_LIMIT
    assert report["compacted"]

    reshuffled = shuffle_packet_lists(anonymous, "shuffle-seed", {"candidates"})
    assert reshuffled == shuffle_packet_lists(anonymous, "shuffle-seed", {"candidates"})
    catalog_path = Path(__file__).resolve().parents[1] / "prompts" / "SCHEMAS.json"
    catalog = _read_json(catalog_path)
    extracted = [extract_stage_schema(catalog, stage) for stage in OUTPUT_SCHEMA_STAGES]
    assert all(schema.get("type") == "object" and "schemas" not in schema for schema in extracted)
    assert extract_stage_schema(catalog, "breaker")["properties"] == extract_stage_schema(catalog, "critic")["properties"]
    roles = _read_json(catalog_path.with_name("ROLE_CATALOG.json"))
    assert [len(roles["swarm10"][key]) for key in ("proposers", "critics", "verifiers", "judge")] == [5, 2, 2, 1]
    assert [len(roles["tournament20"][key]) for key in ("explorers", "breakers", "verifiers", "synthesizers", "red_team", "final_judge")] == [8, 4, 4, 2, 1, 1]
    return {
        "ok": True,
        "tests": 30,
        "candidate_count": 4,
        "cluster_supports_case_1": first_supports,
        "context_characters_after_compaction": report["after_characters"],
        "answer_terms": 5,
        "answer_encoding": "canonical_decimal_strings",
        "extractable_output_schemas": list(OUTPUT_SCHEMA_STAGES),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--self-test"]:
        print(json.dumps(_self_test(), indent=2, sort_keys=True))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    anonymize_parser = subparsers.add_parser("anonymize", help="strip private metadata and assign opaque IDs")
    anonymize_parser.add_argument("input", type=Path)
    anonymize_parser.add_argument("output", type=Path)
    anonymize_parser.add_argument("--seed", required=True)
    anonymize_parser.add_argument("--expected-workers", type=int)

    reports_parser = subparsers.add_parser("anonymize-reports", help="strip identities from downstream stage reports")
    reports_parser.add_argument("schema", choices=("critic", "breaker", "verifier", "synthesizer", "red_team", "judge"))
    reports_parser.add_argument("input", type=Path)
    reports_parser.add_argument("output", type=Path)
    reports_parser.add_argument("--seed", required=True)
    reports_parser.add_argument("--expected-workers", type=int)

    cluster_parser = subparsers.add_parser("cluster", help="cluster exact five-string answers")
    cluster_parser.add_argument("input", type=Path)
    cluster_parser.add_argument("output", type=Path)
    cluster_parser.add_argument("--seed", required=True)

    shuffle_parser = subparsers.add_parser("shuffle", help="deterministically shuffle selected packet arrays")
    shuffle_parser.add_argument("input", type=Path)
    shuffle_parser.add_argument("output", type=Path)
    shuffle_parser.add_argument("--seed", required=True)
    shuffle_parser.add_argument("--keys", default="candidates,clusters,reports")

    preflight_parser = subparsers.add_parser("preflight", help="enforce the context-size ceiling")
    preflight_parser.add_argument("input", type=Path)
    preflight_parser.add_argument("output", type=Path)
    preflight_parser.add_argument("--limit", type=int, default=DEFAULT_CONTEXT_LIMIT)

    schema_parser = subparsers.add_parser("extract-schema", help="write one root output schema for Codex CLI")
    schema_parser.add_argument("catalog", type=Path)
    schema_parser.add_argument("stage", choices=OUTPUT_SCHEMA_STAGES)
    schema_parser.add_argument("output", type=Path)

    subparsers.add_parser("self-test", help="run deterministic built-in tests")
    args = parser.parse_args(argv)

    if args.command == "self-test":
        print(json.dumps(_self_test(), indent=2, sort_keys=True))
        return 0
    if args.command == "anonymize":
        packet = anonymize_bundle(_read_json(args.input), args.seed, args.expected_workers)
        _write_json(args.output, packet)
        return 0
    if args.command == "anonymize-reports":
        packet = anonymize_report_bundle(_read_json(args.input), args.seed, args.schema, args.expected_workers)
        _write_json(args.output, packet)
        return 0
    if args.command == "cluster":
        packet = cluster_anonymous_packet(_read_json(args.input), args.seed)
        _write_json(args.output, packet)
        return 0
    if args.command == "shuffle":
        keys = {key.strip() for key in args.keys.split(",") if key.strip()}
        _write_json(args.output, shuffle_packet_lists(_read_json(args.input), args.seed, keys))
        return 0
    if args.command == "preflight":
        packet, report = preflight_and_compact(_read_json(args.input), args.limit)
        _write_json(args.output, packet, compact=True)
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 0
    if args.command == "extract-schema":
        _write_json(args.output, extract_stage_schema(_read_json(args.catalog), args.stage))
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, StrictJSONError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2)
