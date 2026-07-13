#!/usr/bin/env python3
"""Resume Experiment 02 under the recorded packet-limit amendment.

This wrapper preserves the original frozen runner and changes only its runtime
packet acceptance ceiling from 60,000 to 65,000 characters. It verifies the
pre-amendment attempt-log prefix and all original frozen identities before it
allows the five unopened judge calls to run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import run_codex_cli as runner


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = EXPERIMENT_ROOT / "PROTOCOL_AMENDMENT_01.json"
AMENDED_PACKET_LIMIT = 65_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_prefix(path: Path, length: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        remaining = length
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("attempt log is shorter than the frozen prefix")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def load_amendment() -> dict[str, Any]:
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment.get("schema_version") != "protocol-amendment-v1":
        raise ValueError("unexpected amendment schema")
    if amendment.get("amendment_id") != "PA-01-packet-ceiling":
        raise ValueError("unexpected amendment identity")
    if amendment.get("correctness_unopened_at_decision") is not True:
        raise ValueError("amendment does not preserve the correctness firewall")
    decision = amendment.get("decision", {})
    if decision.get("original_packet_limit") != 60_000:
        raise ValueError("incorrect original packet limit")
    if decision.get("amended_packet_limit") != AMENDED_PACKET_LIMIT:
        raise ValueError("incorrect amended packet limit")
    if decision.get("compaction_algorithm_changed") is not False:
        raise ValueError("amendment changed the packet algorithm")
    return amendment


def verify_bindings(amendment: dict[str, Any]) -> None:
    bindings = amendment["bindings"]
    fixed_paths = {
        "freeze_manifest_sha256": EXPERIMENT_ROOT / "freeze_manifest.json",
        "run_manifest_sha256": EXPERIMENT_ROOT / "run_manifest.json",
        "frozen_runner_sha256": EXPERIMENT_ROOT / "scripts" / "run_codex_cli.py",
        "packet_builder_sha256": EXPERIMENT_ROOT / "scripts" / "build_packets.py",
        "recovery_runner_sha256": Path(__file__).resolve(),
    }
    for key, path in fixed_paths.items():
        if sha256_file(path) != bindings.get(key):
            raise ValueError(f"amendment binding mismatch: {key}")

    attempts = EXPERIMENT_ROOT / "raw" / "final" / "attempts.jsonl"
    prefix_bytes = int(bindings["pre_amendment_attempt_log_bytes"])
    if sha256_prefix(attempts, prefix_bytes) != bindings["pre_amendment_attempt_log_sha256"]:
        raise ValueError("attempt-log prefix changed after the amendment decision")


def verify_command(argv: list[str], amendment: dict[str, Any]) -> None:
    args = runner.build_parser().parse_args(argv)
    if args.command != "run":
        raise ValueError("amendment wrapper permits only the run command")
    expected_paths = {
        "experiment_root": EXPERIMENT_ROOT,
        "manifest": EXPERIMENT_ROOT / "run_manifest.json",
        "tasks": EXPERIMENT_ROOT / "benchmark" / "public" / "final_blocks.json",
        "run_dir": EXPERIMENT_ROOT / "raw" / "final",
        "freeze_manifest": EXPERIMENT_ROOT / "freeze_manifest.json",
    }
    for name, expected in expected_paths.items():
        actual = getattr(args, name)
        if actual is None or actual.resolve() != expected.resolve():
            raise ValueError(f"amendment command changed {name}")
    if args.concurrency != 20 or args.timeout != 300:
        raise ValueError("amendment command changed concurrency or timeout")
    if any((args.condition, args.architecture, args.block, args.call_id, args.max_calls)):
        raise ValueError("amendment command may not filter the frozen final manifest")
    binary_hash = sha256_file(args.codex_binary.resolve())
    if binary_hash != amendment["bindings"]["codex_binary_sha256"]:
        raise ValueError("Codex binary changed")


def write_receipt(amendment: dict[str, Any]) -> None:
    run_dir = EXPERIMENT_ROOT / "raw" / "final"
    closure = run_dir / "collection_closed.json"
    if not closure.is_file():
        raise ValueError("amended run returned without closing collection")
    receipt = {
        "schema_version": "protocol-amendment-receipt-v1",
        "amendment_id": amendment["amendment_id"],
        "completed_at": runner.utc_now(),
        "amendment_sha256": sha256_file(AMENDMENT_PATH),
        "recovery_runner_sha256": sha256_file(Path(__file__).resolve()),
        "collection_closed_sha256": sha256_file(closure),
        "final_attempt_log_sha256": sha256_file(run_dir / "attempts.jsonl"),
        "amended_packet_limit": AMENDED_PACKET_LIMIT,
        "recovered_call_ids": amendment["remaining_call_ids"],
    }
    runner.atomic_write_json(run_dir / "protocol_amendment_receipt.json", receipt)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    amendment = load_amendment()
    verify_bindings(amendment)
    verify_command(argv, amendment)
    closure = EXPERIMENT_ROOT / "raw" / "final" / "collection_closed.json"
    if closure.is_file():
        write_receipt(amendment)
        print(json.dumps({"status": "already_complete", "collection_closed": True}, indent=2))
        return 0
    runner.PACKET_LIMIT = AMENDED_PACKET_LIMIT
    result = runner.main(argv)
    if result == 0:
        write_receipt(amendment)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
