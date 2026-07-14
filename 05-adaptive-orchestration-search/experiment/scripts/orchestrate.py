#!/usr/bin/env python3
"""Execute declarative Experiment 05 orchestration strategies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "5.0"
SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PROMPT_DIR = EXPERIMENT_DIR / "prompts"
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"
PUBLIC_LABEL = "Light reasoning"
SERVICE_TIER = "standard"
MAX_CONCURRENCY = 60
MAX_CALLS_PER_BLOCK = 15
INTEGER_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
TERMINAL_OUTCOMES = {
    "valid_output",
    "schema_invalid_exhausted",
    "protocol_violation",
    "infrastructure_exhausted",
}
ALLOWED_ROLES = {
    "proposer",
    "critic",
    "verifier",
    "judge",
    "auditor",
    "challenger",
    "juror",
    "integrator",
}
ALLOWED_SCOPES = {"all", "disputed", "low_margin", "no_consensus"}
ALLOWED_SELECTORS = {"base_plurality", "agreement_gate", "weighted_plurality"}
ROLE_CODES = {
    "proposer": "P",
    "critic": "C",
    "verifier": "V",
    "judge": "J",
    "auditor": "A",
    "challenger": "H",
    "juror": "R",
    "integrator": "I",
}
ROLE_INSTRUCTIONS = {
    "proposer": (
        "Solve every supplied case independently. Infer one complete allowed mechanism, "
        "replay the full prefix, and calculate the next five terms."
    ),
    "critic": (
        "Try to falsify the anonymous candidates against the full prefix and arithmetic. "
        "Return the best-supported exact answer, repairing a candidate only with a complete mechanism."
    ),
    "verifier": (
        "Independently reconstruct the strongest candidates and replay them across the full prefix. "
        "Return the exact answer with the strongest complete mathematical support."
    ),
    "judge": (
        "Make an independent decision from the anonymous evidence. Never average tuples or choose "
        "a compromise. Return one exact candidate or a fully checked replacement."
    ),
    "auditor": (
        "Audit indexing, signs, arithmetic, rule consistency, and full-prefix replay. Return the "
        "corrected exact answer supported by a reproducible allowed mechanism."
    ),
    "challenger": (
        "Actively seek a materially different allowed explanation, test it against the whole prefix, "
        "and return whichever exact answer survives the strongest challenge."
    ),
    "juror": (
        "Decide independently among the anonymous candidates using complete-prefix support, exact "
        "arithmetic, and reproducibility rather than popularity or rhetoric."
    ),
    "integrator": (
        "Integrate the anonymous evidence without averaging answers. Return the one exact answer "
        "that best survives reconstruction, falsification, and full-prefix replay."
    ),
}


class OrchestrationError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _as_string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise OrchestrationError(f"{label} must be a string array")
    if not allow_empty and not value:
        raise OrchestrationError(f"{label} may not be empty")
    if len(set(value)) != len(value):
        raise OrchestrationError(f"{label} must not contain duplicates")
    return value


def load_catalog(path: Path = PROMPT_DIR / "LENSES.json") -> dict[str, str]:
    document = load_json(path)
    lenses = document.get("lenses") if isinstance(document, dict) else None
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or not isinstance(lenses, dict)
        or not lenses
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in lenses.items())
    ):
        raise OrchestrationError("invalid Experiment 05 lens catalog")
    return lenses


def validate_selector(selector: Any, strategy_id: str) -> dict[str, Any]:
    if not isinstance(selector, dict) or selector.get("mode") not in ALLOWED_SELECTORS:
        raise OrchestrationError(f"{strategy_id} has an invalid selector")
    mode = selector["mode"]
    base_roles = _as_string_list(
        selector.get("base_roles", ["proposer"]),
        f"{strategy_id}.selector.base_roles",
        allow_empty=False,
    )
    if any(role not in ALLOWED_ROLES for role in base_roles):
        raise OrchestrationError(f"{strategy_id} selector has an unknown base role")
    if mode == "agreement_gate":
        decision_roles = _as_string_list(
            selector.get("decision_roles"),
            f"{strategy_id}.selector.decision_roles",
            allow_empty=False,
        )
        support_roles = _as_string_list(
            selector.get("support_roles", []),
            f"{strategy_id}.selector.support_roles",
        )
        if any(role not in ALLOWED_ROLES for role in decision_roles + support_roles):
            raise OrchestrationError(f"{strategy_id} selector has an unknown role")
        for key in ("min_agree", "min_support"):
            value = selector.get(key, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise OrchestrationError(f"{strategy_id}.selector.{key} must be a nonnegative integer")
    if mode == "weighted_plurality":
        weights = selector.get("role_weights")
        if not isinstance(weights, dict) or not weights:
            raise OrchestrationError(f"{strategy_id} weighted selector needs role_weights")
        for role, weight in weights.items():
            if role not in ALLOWED_ROLES or not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(float(weight)) or float(weight) <= 0:
                raise OrchestrationError(f"{strategy_id} has an invalid role weight")
    return selector


def load_strategies(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = load_json(path)
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise OrchestrationError("strategy batch must use schema version 5.0")
    raw = document.get("strategies")
    if not isinstance(raw, list) or not raw:
        raise OrchestrationError("strategy batch contains no strategies")
    lenses = load_catalog()
    strategies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for strategy in raw:
        if not isinstance(strategy, dict):
            raise OrchestrationError("every strategy must be an object")
        strategy_id = strategy.get("strategy_id")
        if not isinstance(strategy_id, str) or not strategy_id or strategy_id in seen:
            raise OrchestrationError("every strategy needs a unique strategy_id")
        seen.add(strategy_id)
        stages = strategy.get("stages")
        if not isinstance(stages, list) or not stages:
            raise OrchestrationError(f"{strategy_id} contains no stages")
        stage_ids: list[str] = []
        total_calls = 0
        seen_proposer = False
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                raise OrchestrationError(f"{strategy_id} stage {index} is invalid")
            stage_id = stage.get("stage_id")
            role = stage.get("role")
            count = stage.get("count")
            scope = stage.get("scope")
            if not isinstance(stage_id, str) or not stage_id or stage_id in stage_ids:
                raise OrchestrationError(f"{strategy_id} has an invalid or duplicate stage_id")
            if role not in ALLOWED_ROLES or scope not in ALLOWED_SCOPES:
                raise OrchestrationError(f"{strategy_id}.{stage_id} has an invalid role or scope")
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_CALLS_PER_BLOCK:
                raise OrchestrationError(f"{strategy_id}.{stage_id} has an invalid count")
            reads = _as_string_list(stage.get("reads", []), f"{strategy_id}.{stage_id}.reads")
            if any(source not in stage_ids for source in reads):
                raise OrchestrationError(f"{strategy_id}.{stage_id} reads a non-prior stage")
            scope_roles = _as_string_list(
                stage.get("scope_roles", ["proposer"]),
                f"{strategy_id}.{stage_id}.scope_roles",
                allow_empty=False,
            )
            if any(item not in ALLOWED_ROLES for item in scope_roles):
                raise OrchestrationError(f"{strategy_id}.{stage_id} has an unknown scope role")
            lens_ids = stage.get("lens_ids")
            if not isinstance(lens_ids, list) or len(lens_ids) != count or any(item not in lenses for item in lens_ids):
                raise OrchestrationError(
                    f"{strategy_id}.{stage_id} must define one valid lens_id per call"
                )
            if not isinstance(stage.get("instruction"), str) or not stage["instruction"].strip():
                raise OrchestrationError(f"{strategy_id}.{stage_id} needs an instruction")
            if role == "proposer":
                seen_proposer = True
            stage_ids.append(stage_id)
            total_calls += count
        if not seen_proposer or total_calls > MAX_CALLS_PER_BLOCK:
            raise OrchestrationError(
                f"{strategy_id} must include a proposer and use at most {MAX_CALLS_PER_BLOCK} calls per block"
            )
        selector = validate_selector(strategy.get("selector"), strategy_id)
        normalized = json.loads(json.dumps(strategy))
        normalized["selector"] = selector
        normalized["max_calls_per_block"] = total_calls
        normalized["strategy_sha256"] = sha256_json(strategy)
        strategies.append(normalized)
    return document, strategies


def load_blocks(paths: Sequence[Path]) -> list[dict[str, Any]]:
    blocks = [load_json(path) for path in paths]
    seen: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("block_id"), str):
            raise OrchestrationError("every block needs block_id")
        cases = block.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 12:
            raise OrchestrationError("every task block must contain from 1 through 12 cases")
        case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
        if (
            len(case_ids) != len(cases)
            or len(set(case_ids)) != len(cases)
            or any(not isinstance(item, str) for item in case_ids)
        ):
            raise OrchestrationError(f"{block['block_id']} has invalid case IDs")
        if seen.intersection(case_ids):
            raise OrchestrationError("case IDs must be unique across supplied blocks")
        seen.update(case_ids)
    return blocks


def output_schema(case_count: int) -> dict[str, Any]:
    if not 1 <= case_count <= 12:
        raise OrchestrationError("output schema case count must be from 1 through 12")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Swarm Seeds 05 answer block",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "block_id", "results"],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "block_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "results": {
                "type": "array",
                "minItems": case_count,
                "maxItems": case_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "case_id",
                        "answer",
                        "confidence",
                        "rule_summary",
                        "check_summary",
                    ],
                    "properties": {
                        "case_id": {"type": "string", "minLength": 1, "maxLength": 80},
                        "answer": {
                            "type": "array",
                            "minItems": 5,
                            "maxItems": 5,
                            "items": {
                                "type": "string",
                                "pattern": "^(0|-?[1-9][0-9]*)$",
                            },
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rule_summary": {"type": "string", "maxLength": 180},
                        "check_summary": {"type": "string", "maxLength": 140},
                    },
                },
            },
        },
    }


def canonical_answer(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) != 5:
        return None
    if any(
        not isinstance(item, str)
        or INTEGER_RE.fullmatch(item) is None
        or item == "-0"
        for item in value
    ):
        return None
    return tuple(value)


def _confidence(record: dict[str, Any]) -> float:
    value = record.get("confidence", 0.0)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return min(1.0, max(0.0, float(value)))
    return 0.0


def deterministic_plurality(
    records: Sequence[dict[str, Any]], role_weights: dict[str, float] | None = None
) -> tuple[str, ...] | None:
    scores: dict[tuple[str, ...], float] = defaultdict(float)
    counts: Counter[tuple[str, ...]] = Counter()
    confidence_sums: dict[tuple[str, ...], float] = defaultdict(float)
    for record in records:
        if record.get("format_valid") is False:
            continue
        answer = canonical_answer(record.get("answer"))
        if answer is None:
            continue
        role = record.get("role")
        weight = float((role_weights or {}).get(role, 1.0))
        scores[answer] += weight
        counts[answer] += 1
        confidence_sums[answer] += _confidence(record)
    if not scores:
        return None
    return min(
        scores,
        key=lambda answer: (
            -scores[answer],
            -counts[answer],
            -(confidence_sums[answer] / counts[answer]),
            answer,
        ),
    )


def answer_support(records: Sequence[dict[str, Any]], answer: tuple[str, ...] | None) -> int:
    if answer is None:
        return 0
    return sum(
        1
        for row in records
        if row.get("format_valid") is not False
        and canonical_answer(row.get("answer")) == answer
    )


def aggregate_decision(selector: dict[str, Any], records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    base_roles = set(selector.get("base_roles", ["proposer"]))
    base_rows = [row for row in records if row.get("role") in base_roles]
    base = deterministic_plurality(base_rows)
    mode = selector["mode"]
    final = base
    rule = "base_plurality"
    gate_open: bool | None = False
    decision_answer: tuple[str, ...] | None = None
    decision_support = 0
    supporting_support = 0
    if mode == "weighted_plurality":
        weights = {key: float(value) for key, value in selector["role_weights"].items()}
        eligible = [row for row in records if row.get("role") in weights]
        final = deterministic_plurality(eligible, weights) or base
        rule = "weighted_role_plurality" if final is not None else "no_valid_answer"
        gate_open = None
    elif mode == "agreement_gate":
        decision_roles = set(selector["decision_roles"])
        support_roles = set(selector.get("support_roles", []))
        decision_rows = [row for row in records if row.get("role") in decision_roles]
        support_rows = [row for row in records if row.get("role") in support_roles]
        decision_answer = deterministic_plurality(decision_rows)
        decision_support = answer_support(decision_rows, decision_answer)
        supporting_support = answer_support(support_rows, decision_answer)
        gate_open = (
            decision_answer is not None
            and decision_support >= int(selector.get("min_agree", 0))
            and supporting_support >= int(selector.get("min_support", 0))
        )
        if gate_open:
            final = decision_answer
            rule = "agreement_gate_open"
        else:
            final = base
            rule = "agreement_gate_closed"
    return {
        "answer": list(final) if final is not None else None,
        "proposal_plurality": list(base) if base is not None else None,
        "decision_answer": list(decision_answer) if decision_answer is not None else None,
        "decision_support": decision_support,
        "supporting_support": supporting_support,
        "gate_open": gate_open,
        "aggregate_rule": rule,
        "override": final != base,
    }


def _safe_job_id(parts: Iterable[Any]) -> str:
    raw = "-".join(str(part) for part in parts)
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", raw).strip("-.") or "job"
    if len(safe) <= 100:
        return safe
    return safe[:83] + "-" + hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]


def _result_document(run_dir: Path, job_id: str) -> dict[str, Any] | None:
    path = run_dir / "runner" / "jobs" / job_id / "result.json"
    if not path.is_file():
        return None
    result = load_json(path)
    document = result.get("document")
    return document if result.get("outcome") == "valid_output" and isinstance(document, dict) else None


def rows_from_jobs(run_dir: Path, jobs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        document = _result_document(run_dir, job["job_id"])
        items = document.get("results", []) if isinstance(document, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            answer = canonical_answer(item.get("answer"))
            rows.append(
                {
                    "case_id": item.get("case_id"),
                    "answer": list(answer) if answer is not None else None,
                    "confidence": item.get("confidence", 0.0),
                    "rule_summary": item.get("rule_summary"),
                    "check_summary": item.get("check_summary"),
                    "format_valid": answer is not None,
                    "role": job["role"],
                    "stage_id": job["stage_id"],
                    "job_id": job["job_id"],
                }
            )
    return rows


def select_target_case_ids(
    stage: dict[str, Any], block: dict[str, Any], prior_rows: Sequence[dict[str, Any]]
) -> list[str]:
    scope = stage["scope"]
    all_ids = [case["case_id"] for case in block["cases"]]
    if scope == "all":
        return all_ids
    roles = set(stage.get("scope_roles", ["proposer"]))
    threshold = float(stage.get("scope_threshold", 0.60))
    margin = int(stage.get("scope_margin", 2))
    targets: list[str] = []
    for case_id in all_ids:
        answers = [
            canonical_answer(row.get("answer"))
            for row in prior_rows
            if row.get("case_id") == case_id
            and row.get("role") in roles
            and row.get("format_valid") is not False
        ]
        answers = [answer for answer in answers if answer is not None]
        counts = Counter(answers)
        if not counts:
            targets.append(case_id)
            continue
        ordered = sorted(counts.values(), reverse=True)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else 0
        if scope == "disputed" and len(counts) > 1:
            targets.append(case_id)
        elif scope == "low_margin" and (len(counts) > 1 and top - second <= margin):
            targets.append(case_id)
        elif scope == "no_consensus" and top / len(answers) < threshold:
            targets.append(case_id)
    return targets


def evidence_packet(
    *, run_dir: Path, source_jobs: Sequence[dict[str, Any]], recipient_id: str,
    case_ids: Sequence[str], max_items: int = 15,
) -> dict[str, list[dict[str, Any]]]:
    packet: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    for source in source_jobs:
        document = _result_document(run_dir, source["job_id"])
        if not isinstance(document, dict):
            continue
        for item in document.get("results", []):
            if isinstance(item, dict) and item.get("case_id") in packet:
                packet[item["case_id"]].append(
                    {
                        "source_key": source["job_id"],
                        "source_role": source["role"],
                        "answer": item.get("answer"),
                        "confidence": item.get("confidence"),
                        "rule_summary": item.get("rule_summary"),
                        "check_summary": item.get("check_summary"),
                    }
                )
    output: dict[str, list[dict[str, Any]]] = {}
    for case_id, items in packet.items():
        items.sort(
            key=lambda item: hashlib.sha256(
                f"{recipient_id}|{case_id}|{item['source_key']}".encode("utf-8")
            ).hexdigest()
        )
        output[case_id] = [
            {
                "candidate_id": f"E{index:02d}",
                **{key: value for key, value in item.items() if key != "source_key"},
            }
            for index, item in enumerate(items[:max_items], 1)
        ]
    return output


def render_prompt(
    *, common: str, stage: dict[str, Any], lens: str, block: dict[str, Any],
    packet: dict[str, list[dict[str, Any]]] | None,
) -> str:
    role = stage["role"]
    sections = [
        common.strip(),
        f"ROLE\n{ROLE_INSTRUCTIONS[role]}",
        f"SPECIAL ASSIGNMENT\n{stage['instruction'].strip()}",
        f"WORKER LENS\n{lens}",
        "TASK BLOCK JSON\n" + canonical_bytes(block).decode("utf-8"),
    ]
    if packet is not None:
        sections.append(
            "ANONYMOUS CANDIDATE EVIDENCE JSON\n"
            + canonical_bytes(packet).decode("utf-8")
        )
    sections.append("Return the required JSON object now.")
    return "\n\n".join(sections) + "\n"


def build_stage_jobs(
    *, strategies: Sequence[dict[str, Any]], blocks: Sequence[dict[str, Any]],
    stage_index: int, run_dir: Path, phase: str, common: str,
    catalog: dict[str, str], history: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jobs: list[dict[str, Any]] = []
    routing: list[dict[str, Any]] = []
    for strategy in strategies:
        strategy_id = strategy["strategy_id"]
        stages = strategy["stages"]
        if stage_index >= len(stages):
            continue
        stage = stages[stage_index]
        offset = sum(item["count"] for item in stages[:stage_index])
        for block in blocks:
            key = (strategy_id, block["block_id"])
            sources = history[key]
            prior_rows = rows_from_jobs(run_dir, sources)
            target_ids = select_target_case_ids(stage, block, prior_rows)
            routing.append(
                {
                    "strategy_id": strategy_id,
                    "block_id": block["block_id"],
                    "stage_id": stage["stage_id"],
                    "scope": stage["scope"],
                    "target_case_ids": target_ids,
                    "skipped": not target_ids,
                }
            )
            if not target_ids:
                continue
            target_set = set(target_ids)
            target_block = {
                **{key_: value for key_, value in block.items() if key_ != "cases"},
                "cases": [case for case in block["cases"] if case["case_id"] in target_set],
            }
            read_stage_ids = set(stage.get("reads", []))
            read_sources = [source for source in sources if source["stage_id"] in read_stage_ids]
            for local_index in range(1, stage["count"] + 1):
                call_index = offset + local_index
                job_id = _safe_job_id(
                    (phase, strategy_id, block["block_id"], stage["stage_id"], local_index)
                )
                packet = None
                if read_sources:
                    packet = evidence_packet(
                        run_dir=run_dir,
                        source_jobs=read_sources,
                        recipient_id=job_id,
                        case_ids=target_ids,
                        max_items=int(stage.get("max_evidence_per_case", 15)),
                    )
                lens_id = stage["lens_ids"][local_index - 1]
                prompt = render_prompt(
                    common=common,
                    stage=stage,
                    lens=catalog[lens_id],
                    block=target_block,
                    packet=packet,
                )
                prompt_path = run_dir / "prompts" / f"{job_id}.txt"
                write_text(prompt_path, prompt)
                jobs.append(
                    {
                        "job_id": job_id,
                        "phase": phase,
                        "method": strategy["name"],
                        "strategy_id": strategy_id,
                        "strategy_sha256": strategy["strategy_sha256"],
                        "category": strategy["category"],
                        "block_id": block["block_id"],
                        "role": stage["role"],
                        "stage": stage["stage_id"],
                        "stage_id": stage["stage_id"],
                        "stage_index": stage_index,
                        "call_index": call_index,
                        "role_index": local_index,
                        "slot": ROLE_CODES[stage["role"]] + f"{local_index:02d}",
                        "lens_id": lens_id,
                        "scope": stage["scope"],
                        "prompt": prompt,
                        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                        "output_schema": output_schema(len(target_ids)),
                        "dependency_ids": [source["job_id"] for source in read_sources],
                        "expected_block_id": block["block_id"],
                        "expected_case_ids": target_ids,
                    }
                )
    return jobs, routing


def invoke_runner(
    jobs: Sequence[dict[str, Any]], run_dir: Path, codex_binary: Path,
    concurrency: int, timeout_seconds: int, stage_index: int,
) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-05-job-manifest",
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "public_condition_label": PUBLIC_LABEL,
        "service_tier": SERVICE_TIER,
        "stage_index": stage_index,
        "jobs": list(jobs),
    }
    manifest_path = run_dir / "manifests" / f"stage-{stage_index:02d}.json"
    write_json(manifest_path, manifest)
    command = [
        sys.executable,
        str(SCRIPT_DIR / "run_jobs.py"),
        "run",
        "--manifest",
        str(manifest_path),
        "--run-dir",
        str(run_dir / "runner"),
        "--codex-binary",
        str(codex_binary),
        "--concurrency",
        str(concurrency),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise OrchestrationError(
            f"runner failed for stage {stage_index} with exit {completed.returncode}"
        )


def _ledger_index(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "runner" / "attempts.jsonl"
    index: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if event.get("event_type") == "attempt":
                    index[event["job_id"]] = event
    return index


def normalize_predictions(
    run_dir: Path, jobs: Sequence[dict[str, Any]], strategies: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    telemetry = _ledger_index(run_dir)
    model_records: list[dict[str, Any]] = []
    for job in jobs:
        result_path = run_dir / "runner" / "jobs" / job["job_id"] / "result.json"
        terminal = load_json(result_path) if result_path.is_file() else {}
        document = terminal.get("document") if terminal.get("outcome") == "valid_output" else None
        items = {
            item.get("case_id"): item
            for item in document.get("results", [])
            if isinstance(item, dict)
        } if isinstance(document, dict) else {}
        event = telemetry.get(job["job_id"], {})
        usage = event.get("usage") or {}
        terminal_outcome = terminal.get("outcome", "missing")
        terminal_closed = terminal_outcome in TERMINAL_OUTCOMES
        for case_id in job["expected_case_ids"]:
            item = items.get(case_id, {})
            answer = canonical_answer(item.get("answer"))
            valid = isinstance(document, dict) and answer is not None
            model_records.append(
                {
                    "phase": job["phase"],
                    "method": job["method"],
                    "architecture_id": job["strategy_id"],
                    "candidate_id": job["strategy_id"],
                    "genome_id": job["strategy_id"],
                    "genome_sha256": job["strategy_sha256"],
                    "strategy_sha256": job["strategy_sha256"],
                    "category": job["category"],
                    "decision_system_id": "declarative_selector",
                    "block_id": job["block_id"],
                    "case_id": case_id,
                    "role": job["role"],
                    "stage": job["stage_id"],
                    "stage_index": job["stage_index"],
                    "call_index": job["call_index"],
                    "slot": job["slot"],
                    "lens_id": job["lens_id"],
                    "scope": job["scope"],
                    "answer": list(answer) if valid else None,
                    "confidence": item.get("confidence", 0.0) if valid else 0.0,
                    "rule_summary": item.get("rule_summary") if valid else None,
                    "check_summary": item.get("check_summary") if valid else None,
                    "format_valid": valid,
                    "status": "completed" if terminal_closed else "nonterminal",
                    "calls": 1 if terminal_closed else 0,
                    "is_final_output": False,
                    "job_id": job["job_id"],
                    "terminal_outcome": terminal_outcome,
                    "attempt_count": terminal.get("attempt_count", 0),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "latency_ms": event.get("duration_ms"),
                    "prompt_sha256": job["prompt_sha256"],
                    "response_sha256": terminal.get("response_sha256"),
                }
            )

    strategy_index = {item["strategy_id"]: item for item in strategies}
    block_index = {item["block_id"]: item for item in blocks}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in model_records:
        grouped[(row["candidate_id"], row["block_id"])].append(row)
    aggregate_records: list[dict[str, Any]] = []
    for strategy in strategies:
        strategy_id = strategy["strategy_id"]
        for block in blocks:
            block_id = block["block_id"]
            rows = grouped.get((strategy_id, block_id), [])
            for case in block_index[block_id]["cases"]:
                case_id = case["case_id"]
                case_rows = [row for row in rows if row["case_id"] == case_id]
                decision = aggregate_decision(strategy["selector"], case_rows)
                aggregate_records.append(
                    {
                        "phase": rows[0]["phase"] if rows else "unknown",
                        "method": strategy["name"],
                        "architecture_id": strategy_id,
                        "candidate_id": strategy_id,
                        "genome_id": strategy_id,
                        "genome_sha256": strategy["strategy_sha256"],
                        "strategy_sha256": strategy["strategy_sha256"],
                        "category": strategy["category"],
                        "decision_system_id": strategy["selector"]["mode"],
                        "block_id": block_id,
                        "case_id": case_id,
                        "role": "final",
                        "stage": "aggregate",
                        "stage_index": 99,
                        "call_index": 0,
                        "slot": "FINAL",
                        "answer": decision["answer"],
                        "confidence": 0.0,
                        "format_valid": decision["answer"] is not None,
                        "status": "completed",
                        "calls": 0,
                        "is_final_output": True,
                        "job_id": _safe_job_id(
                            ("aggregate", strategy_id, block_id, case_id)
                        ),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "latency_ms": 0,
                        **decision,
                    }
                )
    records = model_records + aggregate_records
    decision_projection = [
        {
            key: row.get(key)
            for key in (
                "phase",
                "method",
                "candidate_id",
                "block_id",
                "case_id",
                "role",
                "call_index",
                "answer",
                "format_valid",
                "aggregate_rule",
                "gate_open",
            )
        }
        for row in records
    ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-05-predictions",
        "job_count": len(jobs),
        "paid_call_count": len(jobs),
        "aggregate_record_count": len(aggregate_records),
        "records": records,
        "records_sha256": sha256_json(records),
        "decision_records_sha256": sha256_json(decision_projection),
    }
    write_json(run_dir / "predictions.json", document)
    return document


def run_strategies(
    *, strategies: Sequence[dict[str, Any]], blocks: Sequence[dict[str, Any]],
    run_dir: Path, phase: str, codex_binary: Path, concurrency: int,
    timeout_seconds: int, strategy_batch_path: Path,
) -> dict[str, Any]:
    common = (PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8")
    catalog = load_catalog()
    history = {
        (strategy["strategy_id"], block["block_id"]): []
        for strategy in strategies
        for block in blocks
    }
    all_jobs: list[dict[str, Any]] = []
    all_routing: list[dict[str, Any]] = []
    for stage_index in range(max(len(strategy["stages"]) for strategy in strategies)):
        stage_jobs, routing = build_stage_jobs(
            strategies=strategies,
            blocks=blocks,
            stage_index=stage_index,
            run_dir=run_dir,
            phase=phase,
            common=common,
            catalog=catalog,
            history=history,
        )
        all_routing.extend(routing)
        all_jobs.extend(stage_jobs)
        if stage_jobs:
            invoke_runner(
                all_jobs,
                run_dir,
                codex_binary,
                concurrency,
                timeout_seconds,
                stage_index,
            )
            for job in stage_jobs:
                history[(job["strategy_id"], job["block_id"])].append(job)
        write_json(run_dir / "routing" / f"stage-{stage_index:02d}.json", routing)
    maximum = sum(
        strategy["max_calls_per_block"] * len(blocks) for strategy in strategies
    )
    if len(all_jobs) > maximum:
        raise OrchestrationError("actual logical calls exceeded the frozen maximum")
    predictions = normalize_predictions(run_dir, all_jobs, strategies, blocks)
    per_strategy_calls = Counter(job["strategy_id"] for job in all_jobs)
    write_json(
        run_dir / "run_summary.json",
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "experiment-05-run-summary",
            "phase": phase,
            "blocks": [block["block_id"] for block in blocks],
            "strategies": [strategy["strategy_id"] for strategy in strategies],
            "planned_max_calls": maximum,
            "actual_logical_calls": len(all_jobs),
            "per_strategy_calls": dict(sorted(per_strategy_calls.items())),
            "routing_decisions": all_routing,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "public_condition_label": PUBLIC_LABEL,
            "service_tier": SERVICE_TIER,
            "common_prefix_sha256": hashlib.sha256(common.encode()).hexdigest(),
            "lens_catalog_sha256": sha256_file(PROMPT_DIR / "LENSES.json"),
            "strategy_batch_sha256": sha256_file(strategy_batch_path),
            "prediction_records_sha256": predictions["records_sha256"],
        },
    )
    return predictions


def self_test() -> None:
    answer_a = ["1", "2", "3", "4", "5"]
    answer_b = ["9", "8", "7", "6", "5"]

    def row(role: str, answer: list[str] | None, confidence: float = 0.5) -> dict[str, Any]:
        return {
            "role": role,
            "answer": answer,
            "confidence": confidence,
            "format_valid": answer is not None,
        }

    proposals = [row("proposer", answer_a), row("proposer", answer_a), row("proposer", answer_b)]
    assert deterministic_plurality(proposals) == tuple(answer_a)
    gate = {
        "mode": "agreement_gate",
        "base_roles": ["proposer"],
        "decision_roles": ["judge"],
        "min_agree": 2,
        "support_roles": ["verifier"],
        "min_support": 1,
    }
    open_rows = proposals + [row("judge", answer_b), row("judge", answer_b), row("verifier", answer_b)]
    assert aggregate_decision(gate, open_rows)["answer"] == answer_b
    assert aggregate_decision(gate, open_rows[:-1])["answer"] == answer_a
    weighted = {
        "mode": "weighted_plurality",
        "base_roles": ["proposer"],
        "role_weights": {"proposer": 1.0, "verifier": 3.0},
    }
    assert aggregate_decision(weighted, proposals + [row("verifier", answer_b)])["answer"] == answer_b
    block = {
        "block_id": "test-b01",
        "cases": [
            {"case_id": f"T{index:02d}", "prefix": [str(index)] * 12}
            for index in range(1, 4)
        ],
    }
    rows = [
        {"case_id": "T01", "role": "proposer", "answer": answer_a, "format_valid": True},
        {"case_id": "T01", "role": "proposer", "answer": answer_b, "format_valid": True},
        {"case_id": "T02", "role": "proposer", "answer": answer_a, "format_valid": True},
        {"case_id": "T02", "role": "proposer", "answer": answer_a, "format_valid": True},
    ]
    stage = {"scope": "disputed", "scope_roles": ["proposer"]}
    assert select_target_case_ids(stage, block, rows) == ["T01", "T03"]
    schema = output_schema(3)
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert schema["properties"]["results"]["minItems"] == 3
    with tempfile.TemporaryDirectory(prefix="experiment-05-orchestrate-") as directory:
        strategy_path = Path(directory) / "strategy.json"
        sample = {
            "schema_version": SCHEMA_VERSION,
            "strategies": [
                {
                    "strategy_id": "T-C01",
                    "name": "test",
                    "category": "control",
                    "description": "test",
                    "stages": [
                        {
                            "stage_id": "solve",
                            "role": "proposer",
                            "count": 1,
                            "scope": "all",
                            "reads": [],
                            "lens_ids": ["generalist"],
                            "instruction": "solve",
                        }
                    ],
                    "selector": {"mode": "base_plurality", "base_roles": ["proposer"]},
                }
            ],
        }
        write_json(strategy_path, sample)
        _, strategies = load_strategies(strategy_path)
        assert strategies[0]["max_calls_per_block"] == 1
    print("orchestrate.py self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run")
    run.add_argument("--strategies", type=Path, required=True)
    run.add_argument("--blocks", type=Path, nargs="+", required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--phase", required=True)
    run.add_argument("--codex-binary", type=Path, required=True)
    run.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    run.add_argument("--timeout-seconds", type=int, default=900)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--strategies", type=Path, required=True)
    aggregate.add_argument("--blocks", type=Path, nargs="+", required=True)
    aggregate.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.command not in {"run", "aggregate"}:
        parser.error("choose run, aggregate, or --self-test")
    strategy_path = args.strategies.resolve()
    _, strategies = load_strategies(strategy_path)
    blocks = load_blocks([path.resolve() for path in args.blocks])
    run_dir = args.run_dir.resolve()
    if args.command == "aggregate":
        manifests = sorted((run_dir / "manifests").glob("stage-*.json"))
        if not manifests:
            raise OrchestrationError("no stage manifest found")
        jobs = load_json(manifests[-1])["jobs"]
        predictions = normalize_predictions(run_dir, jobs, strategies, blocks)
    else:
        if not 1 <= args.concurrency <= MAX_CONCURRENCY:
            parser.error(f"concurrency must be from 1 through {MAX_CONCURRENCY}")
        predictions = run_strategies(
            strategies=strategies,
            blocks=blocks,
            run_dir=run_dir,
            phase=args.phase,
            codex_binary=args.codex_binary.resolve(),
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            strategy_batch_path=strategy_path,
        )
    print(
        json.dumps(
            {
                "status": "complete",
                "logical_calls": predictions["paid_call_count"],
                "records_sha256": predictions["records_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, OrchestrationError) as exc:
        print(f"orchestrate.py: error: {exc}", file=sys.stderr)
        raise SystemExit(2)
