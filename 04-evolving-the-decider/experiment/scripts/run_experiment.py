#!/usr/bin/env python3
"""Run or resume all registered Experiment 04 phases, with no early stopping."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BENCHMARK = ROOT / "benchmark"
PUBLIC = BENCHMARK / "public"
HIDDEN = BENCHMARK / "hidden"
GENOMES = ROOT / "genomes"
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
PYTHON = sys.executable


def execute(arguments: list[str]) -> None:
    display = " ".join(arguments[:3])
    print(f"\n[experiment-04] {display}", flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True)


def py(script: str, *arguments: str) -> None:
    execute([PYTHON, "-B", str(SCRIPTS / script), *arguments])


def score(answers: Path, predictions: Path, output: Path, *comparisons: str) -> None:
    py(
        "score.py",
        "--answers", str(answers),
        "--predictions", str(predictions),
        "--out-dir", str(output),
        *comparisons,
    )


def orchestrate_population(
    population: Path, blocks: list[Path], run_dir: Path, phase: str,
    binary: Path, concurrency: int, timeout: int,
) -> None:
    py(
        "orchestrate.py", "run",
        "--population", str(population),
        "--blocks", *(str(path) for path in blocks),
        "--run-dir", str(run_dir),
        "--phase", phase,
        "--codex-binary", str(binary),
        "--concurrency", str(concurrency),
        "--timeout-seconds", str(timeout),
    )


def orchestrate_vote(
    mode: str, method: str, blocks: list[Path], run_dir: Path, phase: str,
    binary: Path, concurrency: int, timeout: int,
) -> None:
    py(
        "orchestrate.py", "vote",
        "--mode", mode,
        "--method", method,
        "--blocks", *(str(path) for path in blocks),
        "--run-dir", str(run_dir),
        "--phase", phase,
        "--codex-binary", str(binary),
        "--concurrency", str(concurrency),
        "--timeout-seconds", str(timeout),
    )


def assert_prediction_budget(path: Path, paid_calls: int, aggregates: int) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("paid_call_count") != paid_calls:
        raise RuntimeError(f"{path} has {document.get('paid_call_count')} paid calls, expected {paid_calls}")
    if document.get("aggregate_record_count") != aggregates:
        raise RuntimeError(f"{path} has the wrong aggregate-record count")
    if document.get("job_count") != paid_calls:
        raise RuntimeError(f"{path} has the wrong planned-job count")
    paid_rows = [row for row in document.get("records", []) if row.get("call_index", 0) > 0]
    jobs: dict[str, tuple[str, str, int]] = {}
    for row in paid_rows:
        job_id = str(row.get("job_id"))
        state = (str(row.get("status")), str(row.get("terminal_outcome")), int(row.get("attempt_count", 0)))
        if job_id in jobs and jobs[job_id] != state:
            raise RuntimeError(f"{path} has inconsistent terminal evidence for {job_id}")
        jobs[job_id] = state
    if len(jobs) != paid_calls:
        raise RuntimeError(f"{path} contains terminal evidence for {len(jobs)} of {paid_calls} calls")
    allowed = {"valid_output", "schema_invalid_exhausted", "protocol_violation"}
    open_jobs = [job_id for job_id, (status, outcome, attempts) in jobs.items() if status != "completed" or outcome not in allowed or attempts < 1]
    if open_jobs:
        raise RuntimeError(f"answer embargo remains closed; {len(open_jobs)} calls are nonterminal")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 60:
        parser.error("--concurrency must be from 1 through 60")
    binary = args.codex_binary.resolve()
    if not binary.is_file() or binary.is_symlink():
        parser.error("--codex-binary must be the exact executable, not a symlink")

    py("freeze.py", "verify")
    parents = GENOMES / "round-00-parents.json"
    best_founder = GENOMES / "best-founder-freeze.json"

    for round_number in range(1, 9):
        label = f"round-{round_number:02d}"
        candidates = GENOMES / f"{label}-candidates.json"
        survivors = GENOMES / f"{label}-survivors.json"
        py(
            "evolve.py", "make-round",
            "--round", str(round_number),
            "--parents", str(parents),
            "--output", str(candidates),
            "--overwrite",
        )
        blocks = [
            PUBLIC / f"search_B{index:02d}.json"
            for index in (round_number * 2 - 1, round_number * 2)
        ]
        run_dir = RUNS / "search" / label
        result_dir = RESULTS / "search" / label
        orchestrate_population(
            candidates, blocks, run_dir, f"search-{label}",
            binary, args.concurrency, args.timeout_seconds,
        )
        predictions = run_dir / "predictions.json"
        assert_prediction_budget(predictions, 240, 288)
        answers = HIDDEN / f"search_R{round_number:02d}_answers.jsonl"
        score(answers, predictions, result_dir, "--bootstrap-replicates", "1000")
        selection = [
            "evolve.py", "select-round",
            "--round", str(round_number),
            "--candidates", str(candidates),
            "--summary", str(result_dir / "summary.json"),
            "--case-matrix", str(result_dir / "case_matrix.csv"),
            "--answers", str(answers),
            "--predictions", str(predictions),
            "--output", str(survivors),
            "--overwrite",
        ]
        if round_number == 1:
            selection.extend(("--best-founder-output", str(best_founder)))
        py(*selection)
        parents = survivors
        print(f"[experiment-04] completed generation {round_number}/8", flush=True)

    validation_run = RUNS / "validation"
    validation_results = RESULTS / "validation"
    validation_blocks = [PUBLIC / f"validation_B{index:02d}.json" for index in range(1, 7)]
    orchestrate_population(
        parents, validation_blocks, validation_run, "validation",
        binary, args.concurrency, args.timeout_seconds,
    )
    validation_predictions = validation_run / "predictions.json"
    assert_prediction_budget(validation_predictions, 360, 432)
    validation_answers = HIDDEN / "validation_answers.jsonl"
    score(
        validation_answers, validation_predictions, validation_results,
        "--bootstrap-replicates", "5000",
    )
    champion_freeze = GENOMES / "champion-freeze.json"
    py(
        "evolve.py", "select-validation",
        "--population", str(parents),
        "--summary", str(validation_results / "summary.json"),
        "--case-matrix", str(validation_results / "case_matrix.csv"),
        "--answers", str(validation_answers),
        "--predictions", str(validation_predictions),
        "--best-founder", str(best_founder),
        "--output", str(champion_freeze),
        "--overwrite",
    )

    champion_packet = GENOMES / "final-champion.json"
    founder_packet = GENOMES / "final-founder.json"
    py(
        "prepare_finalists.py",
        "--freeze", str(champion_freeze),
        "--champion-output", str(champion_packet),
        "--founder-output", str(founder_packet),
    )
    final_blocks = [PUBLIC / f"final_B{index:02d}.json" for index in range(1, 9)]
    final_specs = (
        ("evolved_champion", champion_packet, None),
        ("best_initial_founder", founder_packet, None),
        ("generalist_vote10", None, "generalist"),
        ("diversified_vote10", None, "diversified"),
    )
    final_prediction_paths: dict[str, Path] = {}
    for label, population, vote_mode in final_specs:
        run_dir = RUNS / "final" / label
        phase = f"final-{label}"
        if population is not None:
            orchestrate_population(
                population, final_blocks, run_dir, phase,
                binary, args.concurrency, args.timeout_seconds,
            )
        else:
            orchestrate_vote(
                vote_mode or "", label, final_blocks, run_dir, phase,
                binary, args.concurrency, args.timeout_seconds,
            )
        prediction_path = run_dir / "predictions.json"
        assert_prediction_budget(prediction_path, 80, 96)
        final_prediction_paths[label] = prediction_path

    merged = RUNS / "final" / "predictions.json"
    merge_arguments: list[str] = []
    for label in (
        "evolved_champion", "best_initial_founder",
        "generalist_vote10", "diversified_vote10",
    ):
        merge_arguments.extend(("--input", f"{label}={final_prediction_paths[label]}"))
    py("merge_predictions.py", *merge_arguments, "--output", str(merged))
    final_results = RESULTS / "final"
    score(
        HIDDEN / "final_answers.jsonl", merged, final_results,
        "--final-genome", "evolved_champion",
        "--baseline", "diversified_vote10",
        "--baseline", "best_initial_founder",
        "--baseline", "generalist_vote10",
        "--bootstrap-replicates", "50000",
    )
    print("\n[experiment-04] all eight generations, validation, and hidden final are complete", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"run_experiment.py: error: {exc}", file=sys.stderr)
        raise SystemExit(2)
