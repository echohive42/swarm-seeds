#!/usr/bin/env python3
"""Run Experiment 05 with the six-case exploratory prompt population."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
PROMPT_DIR = EXPERIMENT_DIR / "prompts" / "exploration-v3"
SOURCE = SCRIPT_DIR / "orchestrate.py"


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("experiment05_orchestrate_exploration_v3_impl", SOURCE)
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
_IMPL.ROLE_INSTRUCTIONS = {
    "proposer": "Solve every supplied case independently. Infer a compact deterministic rule, test it on the visible prefix, and calculate the next five terms.",
    "critic": "Try to falsify anonymous candidates against the full prefix. Return the best-supported answer, repairing it only with a reproducible rule.",
    "verifier": "Independently reconstruct the strongest candidates and test their predictions on visible held-out terms before returning one exact answer.",
    "judge": "Make an independent decision from anonymous evidence. Never average tuples or choose a compromise. Return the most predictive exact answer.",
    "auditor": "Audit indexing, signs, arithmetic, rule consistency, and suffix prediction. Return the corrected exact answer supported by a reproducible rule.",
    "challenger": "Seek a materially different compact explanation, test it across the prefix, and return whichever exact answer survives the stronger challenge.",
    "juror": "Decide independently among anonymous candidates using reproducibility, suffix prediction, exact arithmetic, and simplicity rather than popularity.",
    "integrator": "Integrate anonymous evidence without averaging answers. Return the one exact answer that best survives reconstruction, falsification, and prediction checks."
}


def main(argv: Sequence[str] | None = None) -> int:
    return _IMPL.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
