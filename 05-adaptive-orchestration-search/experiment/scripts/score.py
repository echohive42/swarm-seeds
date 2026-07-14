#!/usr/bin/env python3
"""Experiment 05 scoring adapter over the audited Experiment 04 scorer."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Sequence


SCHEMA_VERSION = "5.0"
_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "04-evolving-the-decider"
    / "experiment"
    / "scripts"
    / "score.py"
)


def _load_impl():
    spec = importlib.util.spec_from_file_location("experiment04_score_e05", _SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified scorer: {_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCHEMA_VERSION = SCHEMA_VERSION
    module._IMPL.SCHEMA_VERSION = SCHEMA_VERSION
    return module


_IMPL = _load_impl()
ScoreError = _IMPL.ScoreError


def self_test() -> None:
    _IMPL.self_test()
    assert _IMPL.SCHEMA_VERSION == SCHEMA_VERSION
    print("score.py Experiment 05 adapter self-test: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if "--self-test" in arguments:
        self_test()
        return 0
    return _IMPL.main(arguments)


def __getattr__(name: str):
    return getattr(_IMPL, name)


if __name__ == "__main__":
    raise SystemExit(main())

