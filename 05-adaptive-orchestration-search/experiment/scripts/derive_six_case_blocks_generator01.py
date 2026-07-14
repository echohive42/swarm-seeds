#!/usr/bin/env python3
"""Derive four untouched six-case blocks for generator exploration 01."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE = SCRIPT_DIR / "derive_six_case_blocks.py"


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("experiment05_derive_generator01_impl", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load block derivation script: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_IMPL = load_source()
_IMPL.SOURCE_NAMES = ("research_B11.json", "research_B12.json")
_IMPL.OUTPUT_DIR = _IMPL.PUBLIC_DIR / "derived-six-generator-01"


if __name__ == "__main__":
    raise SystemExit(_IMPL.main())
