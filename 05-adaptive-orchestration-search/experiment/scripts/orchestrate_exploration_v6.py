#!/usr/bin/env python3
"""Run Experiment 05 evolved single-case deep generators."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PROMPT_DIR = EXPERIMENT_DIR / "prompts" / "exploration-v6"
SOURCE = SCRIPT_DIR / "orchestrate.py"


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location(
        "experiment05_orchestrate_exploration_v6_impl", SOURCE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load orchestrator: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_IMPL = load_source()
_ORIGINAL_LOAD_CATALOG = _IMPL.load_catalog


def load_catalog(path: Path | None = None) -> dict[str, str]:
    return _ORIGINAL_LOAD_CATALOG(path or PROMPT_DIR / "LENSES.json")


_IMPL.PROMPT_DIR = PROMPT_DIR
_IMPL.load_catalog = load_catalog


def main(argv: Sequence[str] | None = None) -> int:
    return _IMPL.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
