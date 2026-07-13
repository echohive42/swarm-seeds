#!/usr/bin/env python3
"""Experiment 04 adapter for the audited Experiment 03 isolated-call runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Iterable


MAX_CONCURRENCY = 60
_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "03-evolving-light-swarms"
    / "experiment"
    / "scripts"
    / "run_jobs.py"
)


def _load_impl():
    spec = importlib.util.spec_from_file_location("experiment03_run_jobs", _SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified runner: {_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()
_ORIGINAL_MAX = _IMPL.MAX_CONCURRENCY
_ORIGINAL_LEDGER = _IMPL.LEDGER_VERSION
_IMPL.MAX_CONCURRENCY = MAX_CONCURRENCY
_IMPL.LEDGER_VERSION = "experiment-04-attempts-v1"

RunnerError = _IMPL.RunnerError
MODEL = _IMPL.MODEL
REASONING_EFFORT = _IMPL.REASONING_EFFORT
PUBLIC_LABEL = _IMPL.PUBLIC_LABEL


def self_test() -> None:
    """Exercise the inherited retry runner, then verify the E04-only cap."""
    _IMPL.MAX_CONCURRENCY = _ORIGINAL_MAX
    _IMPL.LEDGER_VERSION = _ORIGINAL_LEDGER
    try:
        _IMPL.self_test()
    finally:
        _IMPL.MAX_CONCURRENCY = MAX_CONCURRENCY
        _IMPL.LEDGER_VERSION = "experiment-04-attempts-v1"
    assert _IMPL.parser().parse_args([
        "run", "--manifest", "m", "--run-dir", "r", "--codex-binary", "c"
    ]).concurrency == 60
    print("run_jobs.py Experiment 04 adapter self-test: PASS")


def main(argv: Iterable[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if "--self-test" in arguments:
        self_test()
        return 0
    _IMPL.MAX_CONCURRENCY = MAX_CONCURRENCY
    _IMPL.LEDGER_VERSION = "experiment-04-attempts-v1"
    return _IMPL.main(arguments)


def __getattr__(name: str):
    return getattr(_IMPL, name)


if __name__ == "__main__":
    raise SystemExit(main())
