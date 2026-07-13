#!/usr/bin/env python3
"""Render, stage, normalize, and deterministically decide Experiment 04 runs."""

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


SCHEMA_VERSION = "4.0"
SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PROMPT_DIR = EXPERIMENT_DIR / "prompts"
SCHEMA_PATH = PROMPT_DIR / "answer_block.schema.json"
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"
PUBLIC_LABEL = "Light reasoning"
SERVICE_TIER = "standard"
MAX_CONCURRENCY = 60
INTEGER_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
TERMINAL_OUTCOMES = {"valid_output", "schema_invalid_exhausted", "protocol_violation"}

DECISION_SYSTEMS: dict[str, tuple[tuple[str, int], ...]] = {
    "vote_10p": (("proposer", 10),),
    "judge_9p1j": (("proposer", 9), ("judge", 1)),
    "gated_7p2c1j": (("proposer", 7), ("critic", 2), ("judge", 1)),
    "dual_8p2j": (("proposer", 8), ("judge", 2)),
    "verified_7p2v1j": (("proposer", 7), ("verifier", 2), ("judge", 1)),
    "deliberative_6p2c2j": (("proposer", 6), ("critic", 2), ("judge", 2)),
}

ROLE_INSTRUCTIONS = {
    "proposer": (
        "Solve every case independently. Infer one complete allowed mechanism, replay the full "
        "prefix, and calculate the next five terms."
    ),
    "critic": (
        "Independently try to falsify the anonymous proposals against the full prefix and arithmetic. "
        "Return the best-supported exact answer for every case, repairing a proposal only when a "
        "complete allowed mechanism justifies it."
    ),
    "verifier": (
        "Independently reconstruct and replay the strongest anonymous proposals. Return the exact "
        "answer with the best complete-prefix mathematical support for every case."
    ),
    "judge": (
        "Make an independent decision for every case from the anonymous evidence. Do not average "
        "numbers or invent a compromise tuple; return one exact candidate or a fully checked replacement."
    ),
}

BASELINE_LENSES = {
    "generalist": ("generalist",) * 10,
    "diversified": (
        "generalist", "differences", "recurrences", "streams", "modular",
        "simplicity", "diversifier", "audit", "generalist", "audit",
    ),
}
BASELINE_METHODS = {
    "generalist": "generalist_vote10",
    "diversified": "diversified_vote10",
}


class OrchestrationError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def stage_layout(genome_or_system: dict[str, Any] | str) -> tuple[tuple[str, int], ...]:
    if isinstance(genome_or_system, str):
        system = genome_or_system
    else:
        system = genome_or_system.get("genes", genome_or_system)["decision_system_id"]
    try:
        return DECISION_SYSTEMS[system]
    except KeyError as exc:
        raise OrchestrationError(f"unknown decision system {system!r}") from exc


def _population_entries(document: Any) -> list[Any]:
    if isinstance(document, list):
        return document
    for key in ("candidates", "slots", "genomes", "population"):
        if isinstance(document, dict) and isinstance(document.get(key), list):
            return document[key]
    raise OrchestrationError("population artifact contains no candidate list")


def load_population(path: Path) -> list[dict[str, Any]]:
    genomes: list[dict[str, Any]] = []
    for entry in _population_entries(load_json(path)):
        genome = entry.get("genome", entry) if isinstance(entry, dict) else entry
        if not isinstance(genome, dict) or not isinstance(genome.get("genes"), dict):
            raise OrchestrationError("every population entry must contain a genome")
        genes = genome["genes"]
        stage_layout(genome)
        lenses = genes.get("worker_lens_ids")
        if not isinstance(lenses, list) or len(lenses) != 10 or not all(isinstance(x, str) for x in lenses):
            raise OrchestrationError(f"{genome.get('genome_id')} must define 10 worker_lens_ids")
        if not isinstance(genes.get("judge_policy_id"), str):
            raise OrchestrationError(f"{genome.get('genome_id')} needs judge_policy_id")
        digest = sha256_json(genes)
        if genome.get("genome_sha256") not in (None, digest):
            raise OrchestrationError(f"genome hash mismatch for {genome.get('genome_id')}")
        normalized = dict(genome)
        normalized["genome_sha256"] = digest
        normalized.setdefault("genome_id", "G-" + digest[:12].upper())
        normalized["baseline"] = False
        genomes.append(normalized)
    if not genomes or len({g["genome_id"] for g in genomes}) != len(genomes):
        raise OrchestrationError("population must contain unique genomes")
    return genomes


def load_blocks(paths: Sequence[Path]) -> list[dict[str, Any]]:
    blocks = [load_json(path) for path in paths]
    seen: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("block_id"), str):
            raise OrchestrationError("every block needs block_id")
        cases = block.get("cases")
        if not isinstance(cases, list) or len(cases) != 12:
            raise OrchestrationError("every task block must contain exactly 12 cases")
        case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
        if len(case_ids) != 12 or len(set(case_ids)) != 12 or any(not isinstance(x, str) for x in case_ids):
            raise OrchestrationError(f"{block['block_id']} must contain 12 unique case IDs")
        if seen.intersection(case_ids):
            raise OrchestrationError("case IDs must be unique across supplied blocks")
        seen.update(case_ids)
    return blocks


def render_prompt(
    *, common: str, role: str, lens: str, policy: str | None,
    block: dict[str, Any], packet: dict[str, Any] | None,
) -> str:
    sections = [common.strip(), f"ROLE\n{ROLE_INSTRUCTIONS[role]}", f"WORKER LENS\n{lens}"]
    if policy is not None:
        sections.append(f"JUDGE POLICY\n{policy}")
    sections.append("TASK BLOCK JSON\n" + canonical_bytes(block).decode("utf-8"))
    if packet is not None:
        sections.append("ANONYMOUS CANDIDATE EVIDENCE JSON\n" + canonical_bytes(packet).decode("utf-8"))
    sections.append("Return the required JSON object now.")
    return "\n\n".join(sections) + "\n"


def _result_document(run_dir: Path, job_id: str) -> dict[str, Any] | None:
    path = run_dir / "runner" / "jobs" / job_id / "result.json"
    if not path.is_file():
        return None
    result = load_json(path)
    return result.get("document") if result.get("outcome") == "valid_output" else None


def evidence_packet(
    run_dir: Path, source_jobs: Sequence[dict[str, Any]], recipient_id: str,
    block: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    packet: dict[str, list[dict[str, Any]]] = {case["case_id"]: [] for case in block["cases"]}
    for source in source_jobs:
        document = _result_document(run_dir, source["job_id"])
        if not isinstance(document, dict) or not isinstance(document.get("results"), list):
            continue
        for item in document["results"]:
            if isinstance(item, dict) and item.get("case_id") in packet:
                packet[item["case_id"]].append({
                    "source_key": source["job_id"],
                    "source_role": source["role"],
                    "answer": item.get("answer"),
                    "confidence": item.get("confidence"),
                    "rule_summary": item.get("rule_summary"),
                    "check_summary": item.get("check_summary"),
                })
    output: dict[str, list[dict[str, Any]]] = {}
    for case_id, items in packet.items():
        items.sort(key=lambda item: hashlib.sha256(
            f"{recipient_id}|{case_id}|{item['source_key']}".encode("utf-8")
        ).hexdigest())
        output[case_id] = [
            {"candidate_id": f"E{index:02d}", **{k: v for k, v in item.items() if k != "source_key"}}
            for index, item in enumerate(items, 1)
        ]
    return output


def _safe_job_id(parts: Iterable[Any]) -> str:
    raw = "-".join(str(part) for part in parts)
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", raw).strip("-.") or "job"
    if len(safe) <= 100:
        return safe
    return safe[:83] + "-" + hashlib.sha256(safe.encode()).hexdigest()[:16]


def build_stage_jobs(
    *, population: Sequence[dict[str, Any]], blocks: Sequence[dict[str, Any]],
    stage_index: int, run_dir: Path, phase: str, common: str,
    catalog: dict[str, Any], schema: dict[str, Any],
    history: dict[tuple[str, str], list[dict[str, Any]]],
    method_labels: dict[str, str],
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for genome in population:
        genome_id = genome["genome_id"]
        genes = genome["genes"]
        layout = stage_layout(genome)
        if stage_index >= len(layout):
            continue
        role, count = layout[stage_index]
        offset = sum(stage_count for _, stage_count in layout[:stage_index])
        for block in blocks:
            key = (genome_id, block["block_id"])
            sources = history[key]
            for local_index in range(1, count + 1):
                call_index = offset + local_index
                job_id = _safe_job_id((phase, genome_id, block["block_id"], role, local_index))
                lens_id = genes["worker_lens_ids"][call_index - 1]
                try:
                    lens = catalog["worker"][lens_id]
                    policy = catalog["judge"][genes["judge_policy_id"]] if role == "judge" else None
                except KeyError as exc:
                    raise OrchestrationError(f"unknown frozen prompt symbol {exc.args[0]!r}") from exc
                packet = None if role == "proposer" else evidence_packet(
                    run_dir, sources, job_id, block
                )
                prompt = render_prompt(
                    common=common, role=role, lens=lens, policy=policy,
                    block=block, packet=packet,
                )
                prompt_path = run_dir / "prompts" / f"{job_id}.txt"
                write_text(prompt_path, prompt)
                jobs.append({
                    "job_id": job_id,
                    "phase": phase,
                    "method": method_labels[genome_id],
                    "genome_id": genome_id,
                    "genome_sha256": genome["genome_sha256"],
                    "baseline": genome.get("baseline", False),
                    "decision_system_id": genes["decision_system_id"],
                    "block_id": block["block_id"],
                    "role": role,
                    "stage_index": stage_index,
                    "call_index": call_index,
                    "role_index": local_index,
                    "slot": {"proposer": "P", "critic": "C", "verifier": "V", "judge": "J"}[role] + f"{local_index:02d}",
                    "worker_lens_id": lens_id,
                    "judge_policy_id": genes["judge_policy_id"] if role == "judge" else None,
                    "prompt": prompt,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "output_schema": schema,
                    "dependency_ids": [source["job_id"] for source in sources],
                    "expected_block_id": block["block_id"],
                    "expected_case_ids": [case["case_id"] for case in block["cases"]],
                })
    return jobs


def invoke_runner(
    jobs: Sequence[dict[str, Any]], run_dir: Path, codex_binary: Path,
    concurrency: int, timeout_seconds: int, stage_index: int,
) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-04-job-manifest",
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
        sys.executable, str(SCRIPT_DIR / "run_jobs.py"), "run",
        "--manifest", str(manifest_path), "--run-dir", str(run_dir / "runner"),
        "--codex-binary", str(codex_binary), "--concurrency", str(concurrency),
        "--timeout-seconds", str(timeout_seconds),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise OrchestrationError(f"runner failed for stage {stage_index} with exit {completed.returncode}")


def canonical_answer(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) != 5:
        return None
    if any(not isinstance(item, str) or INTEGER_RE.fullmatch(item) is None or item == "-0" for item in value):
        return None
    return tuple(value)


def deterministic_plurality(records: Sequence[dict[str, Any]]) -> tuple[str, ...] | None:
    votes: list[tuple[tuple[str, ...], float]] = []
    for record in records:
        if record.get("format_valid") is False:
            continue
        answer = canonical_answer(record.get("answer"))
        if answer is not None:
            confidence = record.get("confidence", 0.0)
            confidence = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(float(confidence)) else 0.0
            votes.append((answer, confidence))
    if not votes:
        return None
    counts = Counter(answer for answer, _ in votes)
    sums: dict[tuple[str, ...], float] = defaultdict(float)
    for answer, confidence in votes:
        sums[answer] += confidence
    return min(counts, key=lambda answer: (-counts[answer], -(sums[answer] / counts[answer]), answer))


def aggregate_decision(system: str, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if system not in DECISION_SYSTEMS:
        raise OrchestrationError(f"unknown decision system {system!r}")
    proposals = [row for row in records if row.get("role") == "proposer"]
    plurality = deterministic_plurality(proposals)

    def answers(role: str) -> list[tuple[str, ...] | None]:
        rows = sorted(
            (row for row in records if row.get("role") == role),
            key=lambda row: (row.get("call_index", 0), row.get("job_id", "")),
        )
        return [canonical_answer(row.get("answer")) if row.get("format_valid") is not False else None for row in rows]

    critics, verifiers, judges = answers("critic"), answers("verifier"), answers("judge")
    final, gate_open, rule = plurality, False, "proposal_plurality"
    if system == "judge_9p1j":
        final = judges[0] if len(judges) == 1 else None
        gate_open, rule = None, "judge_answer"
    elif system == "gated_7p2c1j":
        gate_open = len(critics) == 2 and len(judges) == 1 and None not in critics + judges and len(set(critics + judges)) == 1
        final, rule = ((judges[0], "critics_and_judge_agree") if gate_open else (plurality, "gate_closed_plurality"))
    elif system == "dual_8p2j":
        gate_open = len(judges) == 2 and None not in judges and judges[0] == judges[1]
        final, rule = ((judges[0], "judges_agree") if gate_open else (plurality, "judges_disagree_plurality"))
    elif system == "verified_7p2v1j":
        gate_open = len(verifiers) == 2 and len(judges) == 1 and None not in verifiers + judges and len(set(verifiers + judges)) == 1
        final, rule = ((judges[0], "verifiers_and_judge_agree") if gate_open else (plurality, "gate_closed_plurality"))
    elif system == "deliberative_6p2c2j":
        judge_agreement = len(judges) == 2 and None not in judges and judges[0] == judges[1]
        gate_open = judge_agreement and any(critic is not None and critic == judges[0] for critic in critics)
        final, rule = ((judges[0], "judges_and_critic_agree") if gate_open else (plurality, "gate_closed_plurality"))
    return {
        "answer": list(final) if final is not None else None,
        "proposal_plurality": list(plurality) if plurality is not None else None,
        "gate_open": gate_open,
        "aggregate_rule": rule,
        "override": final != plurality,
    }


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


def normalize_predictions(run_dir: Path, jobs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    telemetry = _ledger_index(run_dir)
    model_records: list[dict[str, Any]] = []
    for job in jobs:
        result_path = run_dir / "runner" / "jobs" / job["job_id"] / "result.json"
        terminal = load_json(result_path) if result_path.is_file() else {}
        document = terminal.get("document") if terminal.get("outcome") == "valid_output" else None
        items = {item.get("case_id"): item for item in document.get("results", [])} if isinstance(document, dict) else {}
        event = telemetry.get(job["job_id"], {})
        usage = event.get("usage") or {}
        terminal_outcome = terminal.get("outcome", "missing")
        terminal_closed = terminal_outcome in TERMINAL_OUTCOMES
        for case_id in job["expected_case_ids"]:
            item = items.get(case_id, {})
            valid = isinstance(document, dict) and canonical_answer(item.get("answer")) is not None
            model_records.append({
                "phase": job["phase"], "method": job["method"],
                "candidate_id": job["genome_id"],
                "genome_id": None if job.get("baseline") else job["genome_id"],
                "genome_sha256": job["genome_sha256"],
                "decision_system_id": job["decision_system_id"],
                "block_id": job["block_id"], "case_id": case_id,
                "role": job["role"], "stage": job["role"],
                "stage_index": job["stage_index"], "call_index": job["call_index"],
                "slot": job["slot"], "answer": item.get("answer") if valid else None,
                "confidence": item.get("confidence", 0.0) if valid else 0.0,
                "rule_summary": item.get("rule_summary") if valid else None,
                "check_summary": item.get("check_summary") if valid else None,
                "format_valid": valid,
                "status": "completed" if terminal_closed else "nonterminal",
                "calls": 1 if terminal_closed else 0,
                "is_final_output": False, "job_id": job["job_id"],
                "terminal_outcome": terminal_outcome,
                "attempt_count": terminal.get("attempt_count", 0),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "latency_ms": event.get("duration_ms"),
                "prompt_sha256": job["prompt_sha256"],
                "response_sha256": terminal.get("response_sha256"),
            })

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in model_records:
        grouped[(row["candidate_id"], row["block_id"])].append(row)
    aggregate_records: list[dict[str, Any]] = []
    for (candidate_id, block_id), rows in grouped.items():
        first = rows[0]
        case_ids = next(job["expected_case_ids"] for job in jobs if job["genome_id"] == candidate_id and job["block_id"] == block_id)
        for case_id in case_ids:
            case_rows = [row for row in rows if row["case_id"] == case_id]
            decision = aggregate_decision(first["decision_system_id"], case_rows)
            aggregate_records.append({
                "phase": first["phase"], "method": first["method"],
                "candidate_id": candidate_id, "genome_id": first["genome_id"],
                "genome_sha256": first["genome_sha256"],
                "decision_system_id": first["decision_system_id"],
                "block_id": block_id, "case_id": case_id,
                "role": "final", "stage": "aggregate", "stage_index": 99,
                "call_index": 0, "slot": "FINAL", "answer": decision["answer"],
                "confidence": 0.0, "format_valid": decision["answer"] is not None,
                "status": "completed", "calls": 0, "is_final_output": True,
                "job_id": _safe_job_id((first["phase"], candidate_id, block_id, case_id, "aggregate")),
                "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
                **decision,
            })
    records = model_records + aggregate_records
    decision_projection = [
        {key: row.get(key) for key in (
            "phase", "method", "candidate_id", "block_id", "case_id", "role",
            "call_index", "answer", "format_valid", "aggregate_rule", "gate_open",
        )}
        for row in records
    ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-04-predictions",
        "job_count": len(jobs),
        "paid_call_count": len(jobs),
        "aggregate_record_count": len(aggregate_records),
        "records": records,
        "records_sha256": sha256_json(records),
        "decision_records_sha256": sha256_json(decision_projection),
    }
    write_json(run_dir / "predictions.json", document)
    return document


def run_candidates(
    *, population: Sequence[dict[str, Any]], blocks: Sequence[dict[str, Any]],
    run_dir: Path, phase: str, method_labels: dict[str, str],
    codex_binary: Path, concurrency: int, timeout_seconds: int,
) -> dict[str, Any]:
    common = (PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8")
    catalog = load_json(PROMPT_DIR / "LENSES.json")
    schema = load_json(SCHEMA_PATH)
    history = {(genome["genome_id"], block["block_id"]): [] for genome in population for block in blocks}
    all_jobs: list[dict[str, Any]] = []
    for stage_index in range(max(len(stage_layout(genome)) for genome in population)):
        stage_jobs = build_stage_jobs(
            population=population, blocks=blocks, stage_index=stage_index,
            run_dir=run_dir, phase=phase, common=common, catalog=catalog,
            schema=schema, history=history, method_labels=method_labels,
        )
        all_jobs.extend(stage_jobs)
        invoke_runner(all_jobs, run_dir, codex_binary, concurrency, timeout_seconds, stage_index)
        for job in stage_jobs:
            history[(job["genome_id"], job["block_id"])].append(job)
    expected = len(population) * len(blocks) * 10
    if len(all_jobs) != expected:
        raise OrchestrationError(f"planned {len(all_jobs)} calls, expected {expected}")
    predictions = normalize_predictions(run_dir, all_jobs)
    write_json(run_dir / "run_summary.json", {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "experiment-04-run-summary",
        "phase": phase, "blocks": [block["block_id"] for block in blocks],
        "genomes": [genome["genome_id"] for genome in population],
        "planned_calls": len(all_jobs), "concurrency": concurrency,
        "model": MODEL, "reasoning_effort": REASONING_EFFORT,
        "public_condition_label": PUBLIC_LABEL,
        "service_tier": SERVICE_TIER,
        "common_prefix_sha256": hashlib.sha256(common.encode()).hexdigest(),
        "answer_schema_sha256": sha256_file(SCHEMA_PATH),
        "prediction_records_sha256": predictions["records_sha256"],
    })
    return predictions


def baseline_genome(mode: str) -> dict[str, Any]:
    lenses = list(BASELINE_LENSES[mode])
    genes = {
        "decision_system_id": "vote_10p",
        "worker_lens_ids": lenses,
        "judge_policy_id": "plurality_preserving",
    }
    return {
        "genome_id": mode.upper() + "-VOTE10",
        "genome_sha256": sha256_json(genes),
        "genes": genes,
        "lineage": {"round": None, "operation": "frozen_baseline"},
        "baseline": True,
    }


def _common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--blocks", type=Path, nargs="+", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    parser.add_argument("--timeout-seconds", type=int, default=300)


def self_test() -> None:
    assert all(sum(count for _, count in layout) == 10 for layout in DECISION_SYSTEMS.values())
    assert dict(DECISION_SYSTEMS["dual_8p2j"])["judge"] == 2
    a, b = ["1", "2", "3", "4", "5"], ["9", "8", "7", "6", "5"]

    def row(role: str, answer: list[str] | None, call: int, confidence: float = 0.5) -> dict[str, Any]:
        return {"role": role, "answer": answer, "call_index": call, "confidence": confidence, "format_valid": answer is not None, "job_id": str(call)}

    proposals = [row("proposer", a, 1), row("proposer", a, 2), row("proposer", b, 3)]
    assert aggregate_decision("vote_10p", proposals)["answer"] == a
    assert aggregate_decision("judge_9p1j", proposals + [row("judge", b, 10)])["answer"] == b
    open_gated = proposals + [row("critic", b, 8), row("critic", b, 9), row("judge", b, 10)]
    assert aggregate_decision("gated_7p2c1j", open_gated)["answer"] == b
    assert aggregate_decision("gated_7p2c1j", open_gated[:-2] + [row("critic", a, 9), row("judge", b, 10)])["answer"] == a
    assert aggregate_decision("dual_8p2j", proposals + [row("judge", b, 9), row("judge", b, 10)])["answer"] == b
    assert aggregate_decision("dual_8p2j", proposals + [row("judge", a, 9), row("judge", b, 10)])["answer"] == a
    verified = proposals + [row("verifier", b, 8), row("verifier", b, 9), row("judge", b, 10)]
    assert aggregate_decision("verified_7p2v1j", verified)["answer"] == b
    deliberative = proposals + [row("critic", a, 7), row("critic", b, 8), row("judge", b, 9), row("judge", b, 10)]
    assert aggregate_decision("deliberative_6p2c2j", deliberative)["answer"] == b
    assert aggregate_decision("deliberative_6p2c2j", proposals + [row("critic", a, 7), row("critic", a, 8), row("judge", b, 9), row("judge", b, 10)])["answer"] == a
    assert aggregate_decision("dual_8p2j", proposals + [row("judge", None, 9), row("judge", b, 10)])["answer"] == a
    tied = [row("proposer", a, 1, .5), row("proposer", b, 2, .6)]
    assert deterministic_plurality(tied) == tuple(b)
    tied[1]["confidence"] = .5
    assert deterministic_plurality(tied) == min(tuple(a), tuple(b))
    schema = load_json(SCHEMA_PATH)
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert len(BASELINE_LENSES["generalist"]) == len(BASELINE_LENSES["diversified"]) == 10
    block = {
        "block_id": "test-b01",
        "cases": [{"case_id": f"T{index:02d}", "prefix": [str(index)] * 12} for index in range(12)],
    }
    genome = baseline_genome("generalist")
    with tempfile.TemporaryDirectory(prefix="experiment-04-orchestrate-") as directory:
        run_dir = Path(directory)
        jobs = build_stage_jobs(
            population=[genome], blocks=[block], stage_index=0, run_dir=run_dir,
            phase="test", common=(PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8"),
            catalog=load_json(PROMPT_DIR / "LENSES.json"), schema=schema,
            history={(genome["genome_id"], block["block_id"]): []},
            method_labels={genome["genome_id"]: "generalist_vote10"},
        )
        assert len(jobs) == 10 and all(job["dependency_ids"] == [] for job in jobs)
        result_document = {
            "schema_version": SCHEMA_VERSION, "block_id": block["block_id"],
            "results": [
                {"case_id": case["case_id"], "answer": a, "confidence": 0.5,
                 "rule_summary": "r", "check_summary": "c"}
                for case in block["cases"]
            ],
        }
        for job in jobs:
            write_json(run_dir / "runner" / "jobs" / job["job_id"] / "result.json", {
                "job_id": job["job_id"], "outcome": "valid_output", "attempt_count": 1,
                "response_sha256": "0" * 64, "document": result_document,
            })
        first = normalize_predictions(run_dir, jobs)
        second = normalize_predictions(run_dir, jobs)
        assert first == second and first["paid_call_count"] == 10
        assert first["aggregate_record_count"] == 12 and len(first["records"]) == 132
        assert all(row["calls"] == 0 for row in first["records"][-12:])
    print("orchestrate.py self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run")
    run.add_argument("--population", type=Path, required=True)
    run.add_argument("--method-prefix", default="")
    _common_run_args(run)
    vote = sub.add_parser("vote")
    vote.add_argument("--mode", choices=sorted(BASELINE_LENSES), required=True)
    vote.add_argument("--method")
    _common_run_args(vote)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.command == "aggregate":
        manifests = sorted((args.run_dir / "manifests").glob("stage-*.json"))
        if not manifests:
            raise OrchestrationError("no stage manifest found")
        predictions = normalize_predictions(args.run_dir, load_json(manifests[-1])["jobs"])
        print(json.dumps({"status": "complete", "records_sha256": predictions["records_sha256"]}, sort_keys=True))
        return 0
    if args.command not in {"run", "vote"}:
        parser.error("choose run, vote, aggregate, or --self-test")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"concurrency must be from 1 through {MAX_CONCURRENCY}")
    blocks = load_blocks([path.resolve() for path in args.blocks])
    run_dir = args.run_dir.resolve()
    if args.command == "run":
        population = load_population(args.population.resolve())
        methods = {genome["genome_id"]: args.method_prefix + genome["genome_id"] for genome in population}
    else:
        population = [baseline_genome(args.mode)]
        methods = {population[0]["genome_id"]: args.method or BASELINE_METHODS[args.mode]}
    predictions = run_candidates(
        population=population, blocks=blocks, run_dir=run_dir, phase=args.phase,
        method_labels=methods, codex_binary=args.codex_binary.resolve(),
        concurrency=args.concurrency, timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({"status": "complete", "planned_calls": predictions["paid_call_count"], "records_sha256": predictions["records_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, OrchestrationError) as exc:
        print(f"orchestrate.py: error: {exc}", file=sys.stderr)
        raise SystemExit(2)
