#!/usr/bin/env python3
"""Render and execute fixed-budget Experiment 03 orchestration policies.

This controller deliberately contains no model client. It renders each stage into
a small job manifest and delegates isolated calls to run_jobs.py. Model outputs
are then normalized into one predictions.json file for score.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PROMPT_DIR = EXPERIMENT_DIR / "prompts"
SCHEMA_PATH = PROMPT_DIR / "answer_block.schema.json"

TOPOLOGIES = {
    "consensus_9p_1j": (("proposer", 9), ("judge", 1)),
    "falsification_7p_2c_1j": (("proposer", 7), ("critic", 2), ("judge", 1)),
    "specialization_7p_2v_1j": (("proposer", 7), ("verifier", 2), ("judge", 1)),
    "paired_revision_5p_2r_2v_1j": (
        ("proposer", 5),
        ("revision", 2),
        ("verifier", 2),
        ("judge", 1),
    ),
    "fixed_swarm_5p_2c_2v_1j": (
        ("proposer", 5),
        ("critic", 2),
        ("verifier", 2),
        ("judge", 1),
    ),
}

ROLE_INSTRUCTIONS = {
    "proposer": (
        "Solve every case independently. Infer one complete allowed mechanism, "
        "replay the full prefix, and calculate the next five terms."
    ),
    "critic": (
        "Falsify the anonymous candidates. Check full-prefix fit and arithmetic. "
        "Return the best supported answer, repairing it only when a complete rule justifies the change."
    ),
    "revision": (
        "Compare the anonymous candidates pairwise. Reframe disputed cases and repair the leading "
        "answer only when the revised mechanism reproduces every visible term."
    ),
    "verifier": (
        "Independently verify the strongest distinct candidates. Reconstruct and replay their rules, "
        "then return the answer with the best full-prefix mathematical support."
    ),
    "judge": (
        "Make the final decision for every case from the anonymous evidence. Do not average numbers "
        "or invent a compromise tuple. Return one exact candidate or a fully checked replacement."
    ),
}


class OrchestrationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_population(path: Path) -> list[dict[str, Any]]:
    document = load_json(path)
    if isinstance(document, list):
        genomes = document
    else:
        genomes = document.get("genomes", document.get("population"))
    if not isinstance(genomes, list) or not genomes:
        raise OrchestrationError(f"no genomes found in {path}")
    for genome in genomes:
        genes = genome.get("genes", genome)
        topology = genes.get("topology_id")
        if topology not in TOPOLOGIES:
            raise OrchestrationError(f"unknown topology {topology!r}")
        if sum(count for _, count in TOPOLOGIES[topology]) != 10:
            raise OrchestrationError(f"topology {topology} does not use 10 calls")
        lenses = genes.get("role_lenses")
        if not isinstance(lenses, list) or len(lenses) != 9:
            raise OrchestrationError(f"{genome.get('genome_id')} must define 9 worker lenses")
    return genomes


def load_blocks(paths: list[Path]) -> list[dict[str, Any]]:
    blocks = [load_json(path) for path in paths]
    for block in blocks:
        cases = block.get("cases")
        if not isinstance(cases, list) or len(cases) != 12:
            raise OrchestrationError("every task block must contain exactly 12 cases")
    return blocks


def stage_layout(genome: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    genes = genome.get("genes", genome)
    return TOPOLOGIES[genes["topology_id"]]


def worker_lens(genome: dict[str, Any], worker_index: int, catalog: dict[str, Any]) -> str:
    genes = genome.get("genes", genome)
    lens_id = genes["role_lenses"][worker_index]
    try:
        return catalog["worker"][lens_id]
    except KeyError as exc:
        raise OrchestrationError(f"unknown worker lens {lens_id!r}") from exc


def judge_policy(genome: dict[str, Any], catalog: dict[str, Any]) -> str:
    genes = genome.get("genes", genome)
    policy_id = genes["final_policy_id"]
    try:
        return catalog["judge"][policy_id]
    except KeyError as exc:
        raise OrchestrationError(f"unknown final policy {policy_id!r}") from exc


def result_document(run_dir: Path, job_id: str) -> dict[str, Any] | None:
    direct = run_dir / "runner" / "jobs" / job_id / "result.json"
    if direct.is_file():
        record = load_json(direct)
        for key in ("document", "output", "parsed_output"):
            if isinstance(record.get(key), dict):
                return record[key]
        response = record.get("response_text")
        if isinstance(response, str):
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                return None
    candidates = sorted((run_dir / "runner" / "jobs" / job_id).glob("attempt-*/last_message.txt"))
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def terminal_record(run_dir: Path, job_id: str) -> dict[str, Any]:
    path = run_dir / "runner" / "jobs" / job_id / "result.json"
    return load_json(path) if path.is_file() else {}


def terminal_telemetry(run_dir: Path, job_id: str) -> dict[str, Any]:
    ledger = run_dir / "runner" / "attempts.jsonl"
    if not ledger.is_file():
        return {}
    matches = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("job_id") == job_id:
            matches.append(event)
    valid = [event for event in matches if event.get("status") == "valid_output"]
    return valid[-1] if valid else (matches[-1] if matches else {})


def prior_outputs(
    run_dir: Path,
    job_ids: list[str],
    recipient_id: str,
    block: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    per_case: dict[str, list[dict[str, Any]]] = {case["case_id"]: [] for case in block["cases"]}
    for source_id in job_ids:
        document = result_document(run_dir, source_id)
        if document is None:
            continue
        for item in document["results"]:
            per_case[item["case_id"]].append(
                {
                    "answer": item["answer"],
                    "confidence": item["confidence"],
                    "rule_summary": item["rule_summary"],
                    "check_summary": item["check_summary"],
                    "source": source_id,
                }
            )
    anonymized: dict[str, list[dict[str, Any]]] = {}
    for case_id, records in per_case.items():
        ordered = sorted(
            records,
            key=lambda record: hashlib.sha256(
                f"{recipient_id}|{case_id}|{record['source']}".encode("utf-8")
            ).hexdigest(),
        )
        anonymized[case_id] = [
            {
                "candidate_id": f"C{index:02d}",
                "answer": record["answer"],
                "confidence": record["confidence"],
                "rule_summary": record["rule_summary"],
                "check_summary": record["check_summary"],
            }
            for index, record in enumerate(ordered, start=1)
        ]
    return anonymized


def render_prompt(
    *,
    common: str,
    role: str,
    lens: str,
    policy: str | None,
    block: dict[str, Any],
    packet: dict[str, list[dict[str, Any]]] | None,
) -> str:
    sections = [common.strip(), f"ROLE\n{ROLE_INSTRUCTIONS[role]}"]
    if lens:
        sections.append(f"LENS\n{lens}")
    if policy:
        sections.append(f"FINAL DECISION POLICY\n{policy}")
    sections.append("TASK BLOCK JSON\n" + json.dumps(block, separators=(",", ":"), ensure_ascii=False))
    if packet is not None:
        sections.append(
            "ANONYMOUS CANDIDATE EVIDENCE JSON\n"
            + json.dumps(packet, separators=(",", ":"), ensure_ascii=False)
        )
    sections.append("Return the required JSON object now.")
    return "\n\n".join(sections) + "\n"


def role_jobs(
    *,
    population: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    role: str,
    run_dir: Path,
    common: str,
    catalog: dict[str, Any],
    history: dict[tuple[str, str], list[str]],
    worker_offsets: dict[str, int],
    phase: str,
    method_labels: dict[str, str],
) -> list[dict[str, Any]]:
    jobs = []
    for genome in population:
        genome_id = genome["genome_id"]
        layout = dict(stage_layout(genome))
        count = layout.get(role, 0)
        if not count:
            continue
        for block in blocks:
            block_id = block["block_id"]
            key = (genome_id, block_id)
            for local_index in range(1, count + 1):
                if role == "judge":
                    job_id = f"{phase}-{genome_id}-{block_id}-judge"
                    lens = ""
                    policy = judge_policy(genome, catalog)
                else:
                    worker_index = worker_offsets[genome_id] + local_index - 1
                    job_id = f"{phase}-{genome_id}-{block_id}-{role}-{local_index:02d}"
                    lens = worker_lens(genome, worker_index, catalog)
                    policy = None
                packet = None
                if role != "proposer":
                    packet = prior_outputs(run_dir, history[key], job_id, block)
                prompt_path = run_dir / "prompts" / f"{job_id}.txt"
                write_text(
                    prompt_path,
                    render_prompt(
                        common=common,
                        role=role,
                        lens=lens,
                        policy=policy,
                        block=block,
                        packet=packet,
                    ),
                )
                jobs.append(
                    {
                        "job_id": job_id,
                        "phase": phase,
                        "method": method_labels[genome_id],
                        "genome_id": genome_id,
                        "block_id": block_id,
                        "role": role,
                        "call_index": local_index,
                        "prompt": prompt_path.read_text(encoding="utf-8"),
                        "output_schema": load_json(SCHEMA_PATH),
                        "expected_block_id": block_id,
                        "expected_case_ids": [case["case_id"] for case in block["cases"]],
                    }
                )
    return jobs


def invoke_runner(
    jobs: list[dict[str, Any]],
    run_dir: Path,
    codex_binary: Path,
    concurrency: int,
    timeout_seconds: int,
    stage_name: str,
) -> None:
    if not jobs:
        return
    manifest_path = run_dir / "manifests" / f"{stage_name}.json"
    write_json(manifest_path, {"schema_version": "jobs-v1", "jobs": jobs})
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
        raise OrchestrationError(f"runner failed for {stage_name} with exit {completed.returncode}")


def normalize_predictions(
    run_dir: Path,
    all_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    records = []
    for job in all_jobs:
        terminal = terminal_record(run_dir, job["job_id"])
        telemetry = terminal_telemetry(run_dir, job["job_id"])
        document = result_document(run_dir, job["job_id"])
        usage = telemetry.get("usage") or {}
        items = document["results"] if document is not None else [
            {
                "case_id": case_id,
                "answer": None,
                "confidence": 0.0,
            }
            for case_id in job["expected_case_ids"]
        ]
        for item in items:
            records.append(
                {
                    "phase": job["phase"],
                    "genome_id": job["genome_id"],
                    "method": job["method"],
                    "block_id": job["block_id"],
                    "case_id": item["case_id"],
                    "role": job["role"],
                    "stage": "judge" if job["role"] == "judge" else job["role"],
                    "call_index": job["call_index"],
                    "answer": item["answer"],
                    "confidence": item["confidence"],
                    "format_valid": document is not None and terminal.get("outcome") == "valid_output",
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "latency_ms": telemetry.get("duration_ms"),
                    "job_id": job["job_id"],
                }
            )
    document = {
        "schema_version": "predictions-v1",
        "records": records,
        "job_count": len(all_jobs),
        "records_sha256": sha256_json(records),
    }
    write_json(run_dir / "predictions.json", document)
    return document


def run_population(args: argparse.Namespace) -> None:
    population = load_population(args.population)
    blocks = load_blocks(args.blocks)
    common = (PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8")
    catalog = load_json(PROMPT_DIR / "LENSES.json")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    history: dict[tuple[str, str], list[str]] = {
        (genome["genome_id"], block["block_id"]): []
        for genome in population
        for block in blocks
    }
    worker_offsets = {genome["genome_id"]: 0 for genome in population}
    method_labels = {
        genome["genome_id"]: args.method_prefix + genome["genome_id"]
        for genome in population
    }
    all_jobs: list[dict[str, Any]] = []
    for stage_index, role in enumerate(("proposer", "critic", "revision", "verifier", "judge")):
        jobs = role_jobs(
            population=population,
            blocks=blocks,
            role=role,
            run_dir=args.run_dir,
            common=common,
            catalog=catalog,
            history=history,
            worker_offsets=worker_offsets,
            phase=args.phase,
            method_labels=method_labels,
        )
        all_jobs.extend(jobs)
        invoke_runner(
            all_jobs,
            args.run_dir,
            args.codex_binary,
            args.concurrency,
            args.timeout_seconds,
            f"stage-{stage_index:02d}-{role}",
        )
        for job in jobs:
            history[(job["genome_id"], job["block_id"])].append(job["job_id"])
        if role != "judge":
            for genome in population:
                worker_offsets[genome["genome_id"]] += dict(stage_layout(genome)).get(role, 0)
    normalize_predictions(args.run_dir, all_jobs)
    write_json(
        args.run_dir / "run_summary.json",
        {
            "schema_version": "orchestration-run-v1",
            "phase": args.phase,
            "population_path": str(args.population),
            "population_sha256": hashlib.sha256(args.population.read_bytes()).hexdigest(),
            "blocks": [block["block_id"] for block in blocks],
            "genomes": [genome["genome_id"] for genome in population],
            "planned_calls": len(all_jobs),
            "concurrency": args.concurrency,
        },
    )
    print(json.dumps({"status": "complete", "planned_calls": len(all_jobs)}, sort_keys=True))


def run_vote(args: argparse.Namespace) -> None:
    blocks = load_blocks(args.blocks)
    common = (PROMPT_DIR / "COMMON_PREFIX.txt").read_text(encoding="utf-8")
    catalog = load_json(PROMPT_DIR / "LENSES.json")
    lenses = [
        "generalist",
        "differences",
        "recurrences",
        "streams",
        "modular",
        "simplicity",
        "diversifier",
        "audit",
        "generalist",
        "audit",
    ]
    jobs = []
    for block in blocks:
        for index, lens_id in enumerate(lenses, start=1):
            job_id = f"{args.phase}-VOTE10-{block['block_id']}-proposer-{index:02d}"
            prompt_path = args.run_dir / "prompts" / f"{job_id}.txt"
            write_text(
                prompt_path,
                render_prompt(
                    common=common,
                    role="proposer",
                    lens=catalog["worker"][lens_id],
                    policy=None,
                    block=block,
                    packet=None,
                ),
            )
            jobs.append(
                {
                    "job_id": job_id,
                    "phase": args.phase,
                    "method": "Vote10",
                    "genome_id": "VOTE10",
                    "block_id": block["block_id"],
                    "role": "proposer",
                    "call_index": index,
                    "prompt": prompt_path.read_text(encoding="utf-8"),
                    "output_schema": load_json(SCHEMA_PATH),
                    "expected_block_id": block["block_id"],
                    "expected_case_ids": [case["case_id"] for case in block["cases"]],
                }
            )
    invoke_runner(
        jobs,
        args.run_dir,
        args.codex_binary,
        args.concurrency,
        args.timeout_seconds,
        "vote10",
    )
    normalize_predictions(args.run_dir, jobs)
    write_json(
        args.run_dir / "run_summary.json",
        {
            "schema_version": "orchestration-run-v1",
            "phase": args.phase,
            "blocks": [block["block_id"] for block in blocks],
            "genomes": ["VOTE10"],
            "planned_calls": len(jobs),
            "concurrency": args.concurrency,
        },
    )
    print(json.dumps({"status": "complete", "planned_calls": len(jobs)}, sort_keys=True))


def self_test() -> None:
    assert sum(count for _, count in TOPOLOGIES["paired_revision_5p_2r_2v_1j"]) == 10
    block = {
        "schema_version": "3.0",
        "experiment_id": "swarm-seeds-03",
        "block_id": "test-b01",
        "cases": [{"case_id": f"X{i:02d}", "prefix": [str(n) for n in range(12)]} for i in range(12)],
    }
    prompt = render_prompt(
        common="COMMON",
        role="proposer",
        lens="LENS",
        policy=None,
        block=block,
        packet=None,
    )
    assert "test-b01" in prompt and "Return the required JSON" in prompt
    print("orchestrate.py self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run")
    run.add_argument("--population", type=Path, required=True)
    run.add_argument("--blocks", type=Path, nargs="+", required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--phase", required=True)
    run.add_argument("--method-prefix", default="")
    run.add_argument("--codex-binary", type=Path, required=True)
    run.add_argument("--concurrency", type=int, default=50)
    run.add_argument("--timeout-seconds", type=int, default=300)
    vote = subparsers.add_parser("vote")
    vote.add_argument("--blocks", type=Path, nargs="+", required=True)
    vote.add_argument("--run-dir", type=Path, required=True)
    vote.add_argument("--phase", required=True)
    vote.add_argument("--codex-binary", type=Path, required=True)
    vote.add_argument("--concurrency", type=int, default=50)
    vote.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.command in {"run", "vote"}:
        if not 1 <= args.concurrency <= 50:
            parser.error("concurrency must be between 1 and 50")
        run_population(args) if args.command == "run" else run_vote(args)
        return
    parser.error("choose a command or --self-test")


if __name__ == "__main__":
    main()
