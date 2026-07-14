#!/usr/bin/env python3
"""Experiment 05 adapter for the audited isolated Codex CLI runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Iterable


MAX_CONCURRENCY = 60
SERVICE_TIER = "standard"
_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "03-evolving-light-swarms"
    / "experiment"
    / "scripts"
    / "run_jobs.py"
)


def _load_impl():
    spec = importlib.util.spec_from_file_location("experiment03_run_jobs_e05", _SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified runner: {_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()
_ORIGINAL_LOAD_MANIFEST = _IMPL.load_manifest
_ORIGINAL_REQUEST_HASH = _IMPL.request_hash
_ORIGINAL_MAX = _IMPL.MAX_CONCURRENCY
_ORIGINAL_LEDGER = _IMPL.LEDGER_VERSION


def load_manifest(path: Path):
    manifest, jobs = _ORIGINAL_LOAD_MANIFEST(path)
    if manifest.get("service_tier") != SERVICE_TIER:
        raise _IMPL.RunnerError("Experiment 05 manifests must register Standard service")
    return manifest, jobs


def request_hash(job: dict[str, Any], binary_hash: str, timeout: int) -> str:
    identity = {
        "base_request_sha256": _ORIGINAL_REQUEST_HASH(job, binary_hash, timeout),
        "service_tier": SERVICE_TIER,
    }
    return _IMPL.sha256_bytes(_IMPL.canonical_bytes(identity))


def _install() -> None:
    _IMPL.MAX_CONCURRENCY = MAX_CONCURRENCY
    _IMPL.LEDGER_VERSION = "experiment-05-attempts-v1"
    _IMPL.load_manifest = load_manifest
    _IMPL.request_hash = request_hash


_install()
RunnerError = _IMPL.RunnerError
MODEL = _IMPL.MODEL
REASONING_EFFORT = _IMPL.REASONING_EFFORT
PUBLIC_LABEL = _IMPL.PUBLIC_LABEL


def self_test() -> None:
    _IMPL.load_manifest = _ORIGINAL_LOAD_MANIFEST
    _IMPL.request_hash = _ORIGINAL_REQUEST_HASH
    _IMPL.MAX_CONCURRENCY = _ORIGINAL_MAX
    _IMPL.LEDGER_VERSION = _ORIGINAL_LEDGER
    try:
        _IMPL.self_test()
    finally:
        _install()
    sample = {"prompt": "x", "output_schema": {}, "model": MODEL}
    assert request_hash(sample, "0" * 64, 900) != _ORIGINAL_REQUEST_HASH(
        sample, "0" * 64, 900
    )
    print("run_jobs.py Experiment 05 adapter self-test: PASS")


def main(argv: Iterable[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if "--self-test" in arguments:
        self_test()
        return 0
    _install()
    return _IMPL.main(arguments)


def __getattr__(name: str):
    return getattr(_IMPL, name)


if __name__ == "__main__":
    raise SystemExit(main())

