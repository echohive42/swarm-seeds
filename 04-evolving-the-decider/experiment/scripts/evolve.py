#!/usr/bin/env python3
"""Deterministic, model-free evolution controller for Experiment 04."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


EXPERIMENT_ID = "swarm-seeds-04"
PUBLIC_LABEL = "Light reasoning"
PROVIDER_EFFORT = "low"
EVOLUTION_SEED = "swarm-seeds-04-evolution-v1"
ROUNDS = 8
SLOT_IDS = tuple(f"S{i:02d}" for i in range(1, 7))
DECISION_SYSTEM_IDS = (
    "vote_10p",
    "judge_9p1j",
    "gated_7p2c1j",
    "dual_8p2j",
    "verified_7p2v1j",
    "deliberative_6p2c2j",
)
WORKER_LENS_IDS = (
    "generalist",
    "differences",
    "recurrences",
    "streams",
    "modular",
    "simplicity",
    "diversifier",
    "audit",
)
JUDGE_POLICY_IDS = (
    "plurality_preserving",
    "evidence_weighted",
    "minority_aware",
    "robustness_first",
)
SCHEDULE = {
    "mutation_slots": "round r mutates S[((r-1)+i) mod 6]+1 for i=0..3",
    "crossover_slots": "the other two slots",
    "crossover_mates": "cyclic offsets ((r-1+k) mod 5)+1 for k=0..4; first unique child",
    "choice_function": "SHA-256(seed,NUL,label) modulo frozen canonical option order",
    "replacement": "each child challenges its designated parent; exact fitness ties keep parent",
}
FITNESS_RULE = (
    "more exact next-five cases",
    "more exact cases on the weakest block",
    "fewer harmful overrides of a correct proposer plurality",
    "more individually correct terms",
    "more format-valid cases",
)
CATALOG_SCHEMA = "experiment-04-genome-catalog-v1"
PARENTS_SCHEMA = "experiment-04-parent-population-v1"
CANDIDATES_SCHEMA = "experiment-04-round-candidates-v1"
BEST_FOUNDER_SCHEMA = "experiment-04-best-founder-freeze-v1"
CHAMPION_SCHEMA = "experiment-04-champion-freeze-v1"

SCRIPT_PATH = Path(__file__).resolve()
EXPERIMENT_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_CATALOG = EXPERIMENT_ROOT / "genomes" / "GENOME_CATALOG.json"
DEFAULT_BENCHMARK_MANIFEST = EXPERIMENT_ROOT / "benchmark" / "manifest.json"
BENCHMARK_MANIFEST_SHA256 = "20fa3633add9e79d07bfd6ca14c152ac6b3e1a120f0fe235d4b41aa62760c652"


class EvolutionError(ValueError):
    """Raised when an input violates the frozen protocol."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvolutionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise EvolutionError(f"non-finite JSON number: {token}")


def parse_json_strict(text: str) -> Any:
    try:
        return json.loads(
            text.strip().lstrip("\ufeff"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EvolutionError(f"invalid JSON: {exc}") from exc


def load_json(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
    return parse_json_strict(raw.decode("utf-8")), sha256_bytes(raw)


def _keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise EvolutionError(f"{label} must be an object")
    if set(value) != expected:
        raise EvolutionError(
            f"{label} keys differ; missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}"
        )


def _sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvolutionError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvolutionError(f"{label} must be an integer >= {minimum}")
    return value


def seal_artifact(body: dict[str, Any]) -> dict[str, Any]:
    if "artifact_sha256" in body:
        raise EvolutionError("cannot seal an artifact twice")
    result = copy.deepcopy(body)
    result["artifact_sha256"] = sha256_bytes(canonical_bytes(body))
    return result


def verify_artifact(value: Any, schema: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise EvolutionError(f"expected a {schema} artifact")
    recorded = _sha(value.get("artifact_sha256"), f"{schema} artifact_sha256")
    body = dict(value)
    body.pop("artifact_sha256")
    if sha256_bytes(canonical_bytes(body)) != recorded:
        raise EvolutionError(f"{schema} artifact hash mismatch")
    return value


def atomic_write_json(path: Path, value: Any, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise EvolutionError(f"refusing to overwrite {path}; pass --overwrite intentionally")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _common(catalog_hash: str) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "public_condition_label": PUBLIC_LABEL,
        "provider_reasoning_effort": PROVIDER_EFFORT,
        "evolution_seed": EVOLUTION_SEED,
        "catalog_file_sha256": catalog_hash,
        "round_count": ROUNDS,
        "parent_slot_count": len(SLOT_IDS),
    }


def load_catalog(path: Path = DEFAULT_CATALOG) -> tuple[dict[str, Any], str]:
    catalog, file_hash = load_json(path)
    required = {
        "schema_version", "experiment_id", "public_condition_label", "provider_reasoning_effort",
        "evolution_seed", "rounds", "parent_slots", "candidates_per_round", "calls_per_block",
        "search_blocks_per_round", "search_cases_per_candidate", "search_calls_per_candidate",
        "validation_cases_per_candidate", "validation_calls_per_candidate", "decision_system_ids",
        "worker_lens_ids", "judge_policy_ids", "schedule", "founders",
    }
    _keys(catalog, required, "catalog")
    fixed = (
        catalog["schema_version"] == CATALOG_SCHEMA
        and catalog["experiment_id"] == EXPERIMENT_ID
        and catalog["public_condition_label"] == PUBLIC_LABEL
        and catalog["provider_reasoning_effort"] == PROVIDER_EFFORT
        and catalog["evolution_seed"] == EVOLUTION_SEED
        and catalog["rounds"] == ROUNDS
        and catalog["parent_slots"] == 6
        and catalog["candidates_per_round"] == 12
        and catalog["calls_per_block"] == 10
        and catalog["search_blocks_per_round"] == 2
        and catalog["search_cases_per_candidate"] == 24
        and catalog["search_calls_per_candidate"] == 20
        and catalog["validation_cases_per_candidate"] == 72
        and catalog["validation_calls_per_candidate"] == 60
    )
    if not fixed:
        raise EvolutionError("catalog changes a frozen Experiment 04 constant")
    if tuple(catalog["decision_system_ids"]) != DECISION_SYSTEM_IDS:
        raise EvolutionError("catalog decision-system order differs from the protocol")
    if tuple(catalog["worker_lens_ids"]) != WORKER_LENS_IDS:
        raise EvolutionError("catalog worker-lens order differs from Experiment 03")
    if tuple(catalog["judge_policy_ids"]) != JUDGE_POLICY_IDS or catalog["schedule"] != SCHEDULE:
        raise EvolutionError("catalog policy IDs or deterministic schedule differ")
    founders = catalog["founders"]
    if not isinstance(founders, list) or len(founders) != 6:
        raise EvolutionError("catalog must contain six founders")
    seen: set[str] = set()
    for index, founder in enumerate(founders):
        _keys(founder, {"founder_id", "slot_id", "genes"}, "founder")
        if founder["founder_id"] != f"F{index + 1:02d}" or founder["slot_id"] != SLOT_IDS[index]:
            raise EvolutionError("founder IDs and slots must be F01/S01 through F06/S06")
        genes = validate_genes(founder["genes"])
        digest = genome_hash(genes)
        if digest in seen:
            raise EvolutionError("founder genomes must be unique")
        seen.add(digest)
    if {item["genes"]["decision_system_id"] for item in founders} != set(DECISION_SYSTEM_IDS):
        raise EvolutionError("founders must cover all six decision systems")
    return catalog, file_hash


def load_answer_bindings(path: Path = DEFAULT_BENCHMARK_MANIFEST) -> dict[str, str]:
    manifest, manifest_hash = load_json(path)
    if manifest_hash != BENCHMARK_MANIFEST_SHA256:
        raise EvolutionError("benchmark manifest differs from the pre-call frozen SHA-256")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("experiment_id") != EXPERIMENT_ID
        or manifest.get("benchmark_id") != "ruleweave-5-decider-v1"
        or manifest.get("splits") != {"search": 192, "validation": 72, "final": 96}
    ):
        raise EvolutionError("invalid frozen Experiment 04 benchmark manifest")
    checksums = manifest.get("checksums")
    expected_files = [f"hidden/search_R{round_number:02d}_answers.jsonl" for round_number in range(1, 9)]
    expected_files.append("hidden/validation_answers.jsonl")
    if not isinstance(checksums, dict):
        raise EvolutionError("benchmark manifest lacks checksums")
    bindings: dict[str, str] = {}
    for relative in expected_files:
        declared = _sha(checksums.get(relative), f"benchmark checksum {relative}")
        bindings[relative] = declared
    return bindings


def validate_genes(value: Any) -> dict[str, Any]:
    _keys(value, {"decision_system_id", "worker_lens_ids", "judge_policy_id"}, "genes")
    if value["decision_system_id"] not in DECISION_SYSTEM_IDS:
        raise EvolutionError("unknown decision_system_id")
    lenses = value["worker_lens_ids"]
    if not isinstance(lenses, list) or len(lenses) != 10 or any(lens not in WORKER_LENS_IDS for lens in lenses):
        raise EvolutionError("worker_lens_ids must contain exactly ten frozen Experiment 03 lens IDs")
    if value["judge_policy_id"] not in JUDGE_POLICY_IDS:
        raise EvolutionError("unknown judge_policy_id")
    return copy.deepcopy(value)


def genome_hash(genes: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(validate_genes(genes)))


def genome_id(digest: str) -> str:
    return "G-" + digest[:12].upper()


def make_genome(genes: dict[str, Any], lineage: dict[str, Any]) -> dict[str, Any]:
    genes = validate_genes(genes)
    digest = genome_hash(genes)
    result = {"genome_id": genome_id(digest), "genome_sha256": digest, "genes": genes, "lineage": lineage}
    validate_genome(result)
    return result


def validate_genome(value: Any) -> dict[str, Any]:
    _keys(value, {"genome_id", "genome_sha256", "genes", "lineage"}, "genome")
    genes = validate_genes(value["genes"])
    digest = genome_hash(genes)
    if value["genome_sha256"] != digest or value["genome_id"] != genome_id(digest):
        raise EvolutionError("genome ID/hash does not match canonical genes")
    lineage = value["lineage"]
    _keys(
        lineage,
        {"round", "operation", "parents", "designated_parent_slot", "founder_id", "mutation", "crossover_sources"},
        "genome lineage",
    )
    round_number = _integer(lineage["round"], "lineage round")
    if round_number > ROUNDS or lineage["designated_parent_slot"] not in SLOT_IDS:
        raise EvolutionError("invalid lineage round or designated slot")
    parents = lineage["parents"]
    if not isinstance(parents, list) or any(not isinstance(item, str) for item in parents) or len(set(parents)) != len(parents):
        raise EvolutionError("lineage parents must be unique genome IDs")
    operation = lineage["operation"]
    if operation == "founder":
        if round_number != 0 or parents or not isinstance(lineage["founder_id"], str):
            raise EvolutionError("malformed founder lineage")
        if lineage["mutation"] is not None or lineage["crossover_sources"] is not None:
            raise EvolutionError("founder cannot record reproduction")
    elif operation == "one_gene_mutation":
        if round_number < 1 or len(parents) != 1 or lineage["founder_id"] is not None:
            raise EvolutionError("malformed mutation lineage")
        _keys(lineage["mutation"], {"locus", "from", "to", "attempt"}, "mutation")
        mutation = lineage["mutation"]
        if mutation["locus"] not in GENE_LOCI:
            raise EvolutionError("mutation names an unknown frozen gene locus")
        if mutation["from"] not in _locus_options(mutation["locus"]) or mutation["to"] not in _locus_options(mutation["locus"]):
            raise EvolutionError("mutation endpoints are outside the frozen grammar")
        if mutation["from"] == mutation["to"]:
            raise EvolutionError("one-gene mutation must change a gene")
        _integer(mutation["attempt"], "mutation attempt")
        if lineage["crossover_sources"] is not None:
            raise EvolutionError("mutation cannot record crossover sources")
    elif operation == "crossover":
        if round_number < 1 or len(parents) != 2 or lineage["founder_id"] is not None or lineage["mutation"] is not None:
            raise EvolutionError("malformed crossover lineage")
        sources = lineage["crossover_sources"]
        _keys(
            sources,
            {"decision_system_id", "worker_lens_ids", "judge_policy_id", "mate_slot", "mask", "attempt"},
            "crossover sources",
        )
        if sources["decision_system_id"] not in parents or sources["judge_policy_id"] not in parents:
            raise EvolutionError("crossover scalar source is not a parent")
        if not isinstance(sources["worker_lens_ids"], list) or len(sources["worker_lens_ids"]) != 10:
            raise EvolutionError("crossover requires ten lens sources")
        if any(source not in parents for source in sources["worker_lens_ids"]):
            raise EvolutionError("crossover lens source is not a parent")
        if sources["mate_slot"] not in SLOT_IDS:
            raise EvolutionError("invalid crossover mate slot")
        mask = _integer(sources["mask"], "crossover mask", 1)
        if mask >= (1 << 12) - 1:
            raise EvolutionError("crossover mask must use both parents")
        _integer(sources["attempt"], "crossover attempt")
    else:
        raise EvolutionError("unknown lineage operation")
    return value


GENE_LOCI = ("decision_system_id", *(f"worker_lens_ids.{i}" for i in range(10)), "judge_policy_id")


def _locus_value(genes: dict[str, Any], locus: str) -> str:
    if locus in {"decision_system_id", "judge_policy_id"}:
        return genes[locus]
    if locus.startswith("worker_lens_ids."):
        index = int(locus.rsplit(".", 1)[1])
        if 0 <= index < 10:
            return genes["worker_lens_ids"][index]
    raise EvolutionError(f"unknown locus {locus}")


def _set_locus(genes: dict[str, Any], locus: str, new_value: str) -> None:
    if locus in {"decision_system_id", "judge_policy_id"}:
        genes[locus] = new_value
    else:
        genes["worker_lens_ids"][int(locus.rsplit(".", 1)[1])] = new_value


def _locus_options(locus: str) -> tuple[str, ...]:
    if locus == "decision_system_id":
        return DECISION_SYSTEM_IDS
    if locus == "judge_policy_id":
        return JUDGE_POLICY_IDS
    return WORKER_LENS_IDS


def _deterministic_order(values: Iterable[Any], label: str) -> list[Any]:
    pool = list(values)
    ordered: list[Any] = []
    counter = 0
    while pool:
        digest = sha256_bytes(f"{EVOLUTION_SEED}\0{label}\0{counter}".encode("utf-8"))
        ordered.append(pool.pop(int(digest, 16) % len(pool)))
        counter += 1
    return ordered


def _mutation_slots(round_number: int) -> tuple[str, ...]:
    return tuple(SLOT_IDS[(round_number - 1 + offset) % 6] for offset in range(4))


def _search_blocks(round_number: int) -> list[str]:
    first = 2 * round_number - 1
    return [f"search-b{first:02d}", f"search-b{first + 1:02d}"]


def _validation_blocks() -> list[str]:
    return [f"validation-b{i:02d}" for i in range(1, 7)]


def _founder_genome(founder: dict[str, Any]) -> dict[str, Any]:
    lineage = {
        "round": 0,
        "operation": "founder",
        "parents": [],
        "designated_parent_slot": founder["slot_id"],
        "founder_id": founder["founder_id"],
        "mutation": None,
        "crossover_sources": None,
    }
    return make_genome(founder["genes"], lineage)


def init_population(catalog: dict[str, Any], catalog_hash: str) -> dict[str, Any]:
    slots = [
        {"slot_id": founder["slot_id"], "genome": _founder_genome(founder)}
        for founder in catalog["founders"]
    ]
    body = {
        "schema_version": PARENTS_SCHEMA,
        **_common(catalog_hash),
        "round_completed": 0,
        "source_candidates_artifact_sha256": None,
        "source_candidates_file_sha256": None,
        "source_summary_file_sha256": None,
        "source_case_matrix_file_sha256": None,
        "source_answers_file_sha256": None,
        "source_predictions_file_sha256": None,
        "best_founder_freeze_artifact_sha256": None,
        "history_genome_sha256s": sorted(item["genome"]["genome_sha256"] for item in slots),
        "slots": slots,
        "comparison_receipts": [],
    }
    return seal_artifact(body)


def _check_common(value: dict[str, Any], catalog_hash: str) -> None:
    for key, expected in _common(catalog_hash).items():
        if value.get(key) != expected:
            raise EvolutionError(f"artifact changes frozen field {key}")


def validate_parent_population(value: Any, catalog: dict[str, Any], catalog_hash: str) -> dict[str, Any]:
    population = verify_artifact(value, PARENTS_SCHEMA)
    _check_common(population, catalog_hash)
    round_number = _integer(population.get("round_completed"), "round_completed")
    if round_number > ROUNDS:
        raise EvolutionError("parent population exceeds eight rounds")
    slots = population.get("slots")
    if not isinstance(slots, list) or len(slots) != 6:
        raise EvolutionError("parent population must contain six slots")
    current_hashes: set[str] = set()
    for index, item in enumerate(slots):
        _keys(item, {"slot_id", "genome"}, "parent slot")
        if item["slot_id"] != SLOT_IDS[index]:
            raise EvolutionError("parent slots must be ordered S01 through S06")
        genome = validate_genome(item["genome"])
        if genome["lineage"]["round"] > round_number:
            raise EvolutionError("a parent genome cannot originate after the completed round")
        current_hashes.add(genome["genome_sha256"])
    if len(current_hashes) != 6:
        raise EvolutionError("current parent genomes must be unique")
    history = population.get("history_genome_sha256s")
    if not isinstance(history, list) or history != sorted(set(history)) or len(history) != 6 + 6 * round_number:
        raise EvolutionError("parent history must contain every unique founder and child hash")
    if not current_hashes <= set(history):
        raise EvolutionError("current parents are absent from genome history")
    receipts = population.get("comparison_receipts")
    if not isinstance(receipts, list) or len(receipts) != (0 if round_number == 0 else 6):
        raise EvolutionError("parent population has the wrong comparison receipt count")
    for index, receipt in enumerate(receipts):
        _keys(
            receipt,
            {
                "slot_id", "parent_genome_id", "child_genome_id", "parent_fitness", "child_fitness",
                "decision", "survivor_genome_id",
            },
            "comparison receipt",
        )
        if receipt["slot_id"] != SLOT_IDS[index] or receipt["decision"] not in {
            "replace_parent", "keep_parent_exact_tie", "keep_better_parent",
        }:
            raise EvolutionError("comparison receipt slot or decision is invalid")
        _validate_fitness(receipt["parent_fitness"], 24, 20)
        _validate_fitness(receipt["child_fitness"], 24, 20)
        parent_key = tuple(receipt["parent_fitness"]["fitness_key"])
        child_key = tuple(receipt["child_fitness"]["fitness_key"])
        expected_decision = (
            "replace_parent" if child_key > parent_key
            else "keep_parent_exact_tie" if child_key == parent_key
            else "keep_better_parent"
        )
        expected_survivor = receipt["child_genome_id"] if child_key > parent_key else receipt["parent_genome_id"]
        if receipt["decision"] != expected_decision or receipt["survivor_genome_id"] != expected_survivor:
            raise EvolutionError("comparison receipt violates paired strict replacement")
        if slots[index]["genome"]["genome_id"] != expected_survivor:
            raise EvolutionError("slot survivor differs from its comparison receipt")
    if round_number == 0:
        expected = init_population(catalog, catalog_hash)
        if canonical_bytes(population) != canonical_bytes(expected):
            raise EvolutionError("round-00 population differs from the frozen founders")
    else:
        for key in (
            "source_candidates_artifact_sha256", "source_candidates_file_sha256", "source_summary_file_sha256",
            "source_case_matrix_file_sha256", "source_answers_file_sha256", "source_predictions_file_sha256",
            "best_founder_freeze_artifact_sha256",
        ):
            _sha(population.get(key), key)
    return population


def mutate_genome(parent: dict[str, Any], slot_id: str, round_number: int, used: set[str]) -> dict[str, Any]:
    possibilities: list[tuple[str, str]] = []
    for locus in GENE_LOCI:
        old = _locus_value(parent["genes"], locus)
        possibilities.extend((locus, value) for value in _locus_options(locus) if value != old)
    ordered = _deterministic_order(possibilities, f"round-{round_number:02d}\0{slot_id}\0mutation")
    for attempt, (locus, new_value) in enumerate(ordered):
        genes = copy.deepcopy(parent["genes"])
        old_value = _locus_value(genes, locus)
        _set_locus(genes, locus, new_value)
        digest = genome_hash(genes)
        if digest in used:
            continue
        lineage = {
            "round": round_number,
            "operation": "one_gene_mutation",
            "parents": [parent["genome_id"]],
            "designated_parent_slot": slot_id,
            "founder_id": None,
            "mutation": {"locus": locus, "from": old_value, "to": new_value, "attempt": attempt},
            "crossover_sources": None,
        }
        return make_genome(genes, lineage)
    raise EvolutionError(f"no unique one-gene mutation remains for {slot_id}")


def _mate_order(round_number: int, target_index: int) -> list[int]:
    offsets = [((round_number - 1 + k) % 5) + 1 for k in range(5)]
    return [(target_index + offset) % 6 for offset in offsets]


def crossover_genome(
    parents: list[dict[str, Any]], target_index: int, round_number: int, used: set[str]
) -> dict[str, Any]:
    first = parents[target_index]["genome"]
    slot_id = parents[target_index]["slot_id"]
    for mate_index in _mate_order(round_number, target_index):
        second = parents[mate_index]["genome"]
        masks = _deterministic_order(range(1, (1 << 12) - 1), f"round-{round_number:02d}\0{slot_id}\0{SLOT_IDS[mate_index]}\0crossover")
        for attempt, mask in enumerate(masks):
            sources = [second if mask & (1 << bit) else first for bit in range(12)]
            genes = {
                "decision_system_id": sources[0]["genes"]["decision_system_id"],
                "worker_lens_ids": [sources[i + 1]["genes"]["worker_lens_ids"][i] for i in range(10)],
                "judge_policy_id": sources[11]["genes"]["judge_policy_id"],
            }
            digest = genome_hash(genes)
            if digest in used or digest in {first["genome_sha256"], second["genome_sha256"]}:
                continue
            lineage = {
                "round": round_number,
                "operation": "crossover",
                "parents": [first["genome_id"], second["genome_id"]],
                "designated_parent_slot": slot_id,
                "founder_id": None,
                "mutation": None,
                "crossover_sources": {
                    "decision_system_id": sources[0]["genome_id"],
                    "worker_lens_ids": [sources[i + 1]["genome_id"] for i in range(10)],
                    "judge_policy_id": sources[11]["genome_id"],
                    "mate_slot": SLOT_IDS[mate_index],
                    "mask": mask,
                    "attempt": attempt,
                },
            }
            return make_genome(genes, lineage)
    raise EvolutionError(f"no unique crossover remains for {slot_id}")


def make_round(
    round_number: int, parents: dict[str, Any], parent_file_hash: str, catalog: dict[str, Any], catalog_hash: str
) -> dict[str, Any]:
    validate_parent_population(parents, catalog, catalog_hash)
    if round_number != parents["round_completed"] + 1 or not 1 <= round_number <= ROUNDS:
        raise EvolutionError("round must be the next of exactly eight rounds")
    parent_slots = parents["slots"]
    used = set(parents["history_genome_sha256s"])
    mutation_slots = set(_mutation_slots(round_number))
    children: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for index, item in enumerate(parent_slots):
        if item["slot_id"] in mutation_slots:
            child = mutate_genome(item["genome"], item["slot_id"], round_number, used)
        else:
            child = crossover_genome(parent_slots, index, round_number, used)
        used.add(child["genome_sha256"])
        children.append(child)
        pairs.append({
            "slot_id": item["slot_id"],
            "operation": child["lineage"]["operation"],
            "parent_genome_id": item["genome"]["genome_id"],
            "child_genome_id": child["genome_id"],
        })
    genomes = [item["genome"] for item in parent_slots] + children
    if len({item["genome_sha256"] for item in genomes}) != 12:
        raise EvolutionError("round candidates are not twelve unique canonical genomes")
    body = {
        "schema_version": CANDIDATES_SCHEMA,
        **_common(catalog_hash),
        "round": round_number,
        "source_parent_artifact_sha256": parents["artifact_sha256"],
        "source_parent_file_sha256": parent_file_hash,
        "search_blocks": _search_blocks(round_number),
        "expected_cases_per_candidate": 24,
        "expected_calls_per_candidate": 20,
        "best_founder_freeze_artifact_sha256": parents["best_founder_freeze_artifact_sha256"],
        "history_genome_sha256s_before": parents["history_genome_sha256s"],
        "history_genome_sha256s": sorted(used),
        "genomes": genomes,
        "parent_child_pairs": pairs,
        "reproduction_summary": {"parents": 6, "one_gene_mutations": 4, "crossovers": 2},
    }
    return seal_artifact(body)


def validate_candidates(value: Any, catalog_hash: str) -> dict[str, Any]:
    candidates = verify_artifact(value, CANDIDATES_SCHEMA)
    _check_common(candidates, catalog_hash)
    round_number = _integer(candidates.get("round"), "candidate round", 1)
    if round_number > ROUNDS or candidates.get("search_blocks") != _search_blocks(round_number):
        raise EvolutionError("candidate round has the wrong search blocks")
    if candidates.get("expected_cases_per_candidate") != 24 or candidates.get("expected_calls_per_candidate") != 20:
        raise EvolutionError("candidate artifact changes the registered evaluation budget")
    if round_number == 1:
        if candidates.get("best_founder_freeze_artifact_sha256") is not None:
            raise EvolutionError("round 1 cannot already have a best-founder freeze")
    else:
        _sha(candidates.get("best_founder_freeze_artifact_sha256"), "best-founder freeze artifact hash")
    _sha(candidates.get("source_parent_artifact_sha256"), "source parent artifact hash")
    _sha(candidates.get("source_parent_file_sha256"), "source parent file hash")
    genomes = candidates.get("genomes")
    pairs = candidates.get("parent_child_pairs")
    if not isinstance(genomes, list) or len(genomes) != 12 or not isinstance(pairs, list) or len(pairs) != 6:
        raise EvolutionError("candidate artifact needs twelve genomes and six pairs")
    for genome in genomes:
        validate_genome(genome)
    if len({item["genome_sha256"] for item in genomes}) != 12:
        raise EvolutionError("candidate genomes must be unique")
    lookup = {item["genome_id"]: item for item in genomes}
    expected_operations = {slot: ("one_gene_mutation" if slot in _mutation_slots(round_number) else "crossover") for slot in SLOT_IDS}
    parent_ids: set[str] = set()
    child_ids: set[str] = set()
    for index, pair in enumerate(pairs):
        _keys(pair, {"slot_id", "operation", "parent_genome_id", "child_genome_id"}, "parent-child pair")
        if pair["slot_id"] != SLOT_IDS[index] or pair["operation"] != expected_operations[pair["slot_id"]]:
            raise EvolutionError("parent-child schedule differs from the frozen schedule")
        if pair["parent_genome_id"] not in lookup or pair["child_genome_id"] not in lookup:
            raise EvolutionError("pair references an absent genome")
        parent_ids.add(pair["parent_genome_id"])
        child_ids.add(pair["child_genome_id"])
        child = lookup[pair["child_genome_id"]]
        if child["lineage"]["round"] != round_number or child["lineage"]["designated_parent_slot"] != pair["slot_id"]:
            raise EvolutionError("child lineage does not match its challenge pair")
        if child["lineage"]["parents"][0] != pair["parent_genome_id"]:
            raise EvolutionError("child does not challenge its designated first parent")
        _validate_reproduction(child, lookup)
    if len(parent_ids) != 6 or len(child_ids) != 6 or parent_ids & child_ids:
        raise EvolutionError("each of six unique children must challenge one unique parent")
    before = candidates.get("history_genome_sha256s_before")
    history = candidates.get("history_genome_sha256s")
    if not isinstance(before, list) or before != sorted(set(before)) or not isinstance(history, list) or history != sorted(set(history)):
        raise EvolutionError("candidate histories must be canonical unique hash lists")
    if len(history) != len(before) + 6 or not set(before) < set(history):
        raise EvolutionError("candidate history must add exactly six new genomes")
    if len(before) != 6 + 6 * (round_number - 1):
        raise EvolutionError("candidate prior history length differs from its round")
    if {lookup[item]["genome_sha256"] for item in parent_ids} - set(before):
        raise EvolutionError("candidate parents are absent from prior history")
    if {lookup[item]["genome_sha256"] for item in child_ids} & set(before):
        raise EvolutionError("duplicate genome was reintroduced")
    if candidates.get("reproduction_summary") != {"parents": 6, "one_gene_mutations": 4, "crossovers": 2}:
        raise EvolutionError("round must contain six parents, four mutations, and two crossovers")
    return candidates


def _validate_reproduction(child: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> None:
    lineage = child["lineage"]
    parents = [lookup[item] for item in lineage["parents"]]
    if lineage["operation"] == "one_gene_mutation":
        mutation = lineage["mutation"]
        changed = [locus for locus in GENE_LOCI if _locus_value(child["genes"], locus) != _locus_value(parents[0]["genes"], locus)]
        if changed != [mutation["locus"]]:
            raise EvolutionError("mutation does not change exactly its recorded gene")
        if mutation["from"] != _locus_value(parents[0]["genes"], mutation["locus"]) or mutation["to"] != _locus_value(child["genes"], mutation["locus"]):
            raise EvolutionError("mutation endpoints do not reconstruct child")
        return
    sources = lineage["crossover_sources"]
    by_id = {item["genome_id"]: item for item in parents}
    if child["genes"]["decision_system_id"] != by_id[sources["decision_system_id"]]["genes"]["decision_system_id"]:
        raise EvolutionError("crossover decision source does not reconstruct child")
    if child["genes"]["judge_policy_id"] != by_id[sources["judge_policy_id"]]["genes"]["judge_policy_id"]:
        raise EvolutionError("crossover policy source does not reconstruct child")
    for index, source in enumerate(sources["worker_lens_ids"]):
        if child["genes"]["worker_lens_ids"][index] != by_id[source]["genes"]["worker_lens_ids"][index]:
            raise EvolutionError("crossover lens source does not reconstruct child")


def _binary(value: Any, label: str) -> int:
    if value in (0, "0"):
        return 0
    if value in (1, "1"):
        return 1
    raise EvolutionError(f"{label} must be 0 or 1")


def _csv_integer(value: Any, label: str, minimum: int = 0) -> int:
    if not isinstance(value, str) or not value.strip().isdigit():
        raise EvolutionError(f"{label} must be a base-10 integer")
    return _integer(int(value), label, minimum)


def _method_integer(method: dict[str, Any], names: tuple[str, ...], label: str) -> int:
    present = [(name, method[name]) for name in names if name in method]
    if not present:
        raise EvolutionError(f"method score lacks {label}")
    values = {_integer(value, f"{label} ({name})") for name, value in present}
    if len(values) != 1:
        raise EvolutionError(f"conflicting aliases for {label}")
    return next(iter(values))


def _read_answer_case_ids(path: Path, expected_cases: int) -> set[str]:
    case_ids: list[str] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise EvolutionError(f"blank answer JSONL line {line_number}")
            record = parse_json_strict(line)
            if not isinstance(record, dict) or not isinstance(record.get("case_id"), str) or not record["case_id"]:
                raise EvolutionError(f"answer JSONL line {line_number} has no case_id")
            case_ids.append(record["case_id"])
    if len(case_ids) != expected_cases or len(set(case_ids)) != expected_cases:
        raise EvolutionError(f"answers must contain exactly {expected_cases} unique cases")
    return set(case_ids)


def _read_case_matrix(
    path: Path, genome_ids: list[str], expected_blocks: list[str], expected_cases: int
) -> tuple[dict[str, dict[str, int]], set[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows_reader = csv.reader(handle)
        try:
            header = next(rows_reader)
        except StopIteration as exc:
            raise EvolutionError("case matrix is empty") from exc
        if len(header) != len(set(header)):
            raise EvolutionError("case matrix contains duplicate columns")
        rows = [dict(zip(header, row, strict=True)) for row in rows_reader]
    if len(rows) != expected_cases:
        raise EvolutionError(f"case matrix must contain exactly {expected_cases} rows")
    if "case_id" not in header or "block" not in header:
        raise EvolutionError("case matrix needs case_id and block columns")
    case_ids = [row["case_id"] for row in rows]
    if any(not case_id for case_id in case_ids) or len(set(case_ids)) != expected_cases:
        raise EvolutionError("case matrix case IDs must be non-empty and unique")
    blocks = [row["block"] for row in rows]
    if Counter(blocks) != Counter({block: 12 for block in expected_blocks}):
        raise EvolutionError("case matrix must contain exactly twelve cases in every registered block")
    metrics: dict[str, dict[str, int]] = {}
    for genome_id_value in genome_ids:
        exact_column = f"{genome_id_value}.exact"
        harmful_column = f"{genome_id_value}.harmful_override"
        term_column = f"{genome_id_value}.term_correct"
        format_columns = [
            column for column in (f"{genome_id_value}.format_valid", f"{genome_id_value}.format_compliant")
            if column in header
        ]
        required = [exact_column, harmful_column, term_column]
        if any(column not in header for column in required) or len(format_columns) != 1:
            raise EvolutionError(f"case matrix lacks registered fitness columns for {genome_id_value}")
        block_exact = {
            block: sum(_binary(row[exact_column], exact_column) for row in rows if row["block"] == block)
            for block in expected_blocks
        }
        exact = sum(block_exact.values())
        harmful = sum(_binary(row[harmful_column], harmful_column) for row in rows)
        term_correct = sum(_csv_integer(row[term_column], term_column) for row in rows)
        format_valid = sum(_binary(row[format_columns[0]], format_columns[0]) for row in rows)
        metrics[genome_id_value] = {
            "exact_cases": exact,
            "weakest_block_exact": min(block_exact.values()),
            "harmful_overrides": harmful,
            "term_correct": term_correct,
            "format_valid": format_valid,
            "block_exact": block_exact,
        }
    return metrics, set(case_ids)


def _validate_protocol_key(value: Any, expected: list[int], label: str) -> None:
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise EvolutionError(f"{label} must be a five-integer array")
    if value != expected:
        raise EvolutionError(f"{label} differs from the recomputed protocol fitness")


def evaluate_scores(
    summary: Any,
    genome_ids: list[str],
    case_matrix_path: Path,
    answers_path: Path,
    predictions_path: Path,
    expected_blocks: list[str],
    expected_cases: int,
    expected_calls: int,
) -> dict[str, dict[str, Any]]:
    if not isinstance(summary, dict) or summary.get("schema_version") != "4.0":
        raise EvolutionError("score summary must use schema_version 4.0")
    if summary.get("n_cases") != expected_cases:
        raise EvolutionError(f"score summary n_cases must be exactly {expected_cases}")
    inputs = summary.get("inputs")
    if not isinstance(inputs, dict):
        raise EvolutionError("score summary lacks inputs")
    answers_hash = sha256_file(answers_path)
    predictions_hash = sha256_file(predictions_path)
    if inputs.get("answers_sha256") != answers_hash or inputs.get("predictions_sha256") != predictions_hash:
        raise EvolutionError("score summary is not bound to the explicit answers/predictions files")
    methods = summary.get("methods")
    if not isinstance(methods, dict) or set(methods) != set(genome_ids):
        raise EvolutionError("score summary methods differ from the exact candidate population")
    matrix_metrics, matrix_case_ids = _read_case_matrix(
        case_matrix_path, genome_ids, expected_blocks, expected_cases
    )
    if _read_answer_case_ids(answers_path, expected_cases) != matrix_case_ids:
        raise EvolutionError("answers and case matrix cover different cases")
    top_protocol = summary.get("protocol_fitness")
    if top_protocol is not None and (not isinstance(top_protocol, dict) or set(top_protocol) != set(genome_ids)):
        raise EvolutionError("summary protocol_fitness population differs from methods")
    fitness: dict[str, dict[str, Any]] = {}
    for genome_id_value in genome_ids:
        method = methods[genome_id_value]
        if not isinstance(method, dict):
            raise EvolutionError(f"method score for {genome_id_value} must be an object")
        calls = _method_integer(method, ("calls",), f"{genome_id_value} calls")
        completed_calls = _method_integer(
            method, ("completed_calls",), f"{genome_id_value} completed_calls"
        )
        case_count = _method_integer(method, ("case_count",), f"{genome_id_value} case_count")
        if calls != expected_calls or completed_calls != expected_calls or case_count != expected_cases:
            raise EvolutionError(
                f"{genome_id_value} must bind exactly {expected_cases} cases and {expected_calls} completed calls"
            )
        observed = matrix_metrics[genome_id_value]
        summary_values = {
            "exact_cases": _method_integer(method, ("exact_cases", "exact_correct"), f"{genome_id_value} exact"),
            "harmful_overrides": _method_integer(method, ("harmful_overrides",), f"{genome_id_value} harmful overrides"),
            "term_correct": _method_integer(method, ("term_correct",), f"{genome_id_value} correct terms"),
            "format_valid": _method_integer(
                method, ("format_valid", "format_valid_cases"), f"{genome_id_value} format-valid cases"
            ),
        }
        if any(summary_values[key] != observed[key] for key in summary_values):
            raise EvolutionError(f"summary fitness totals disagree with case matrix for {genome_id_value}")
        key = [
            observed["exact_cases"],
            observed["weakest_block_exact"],
            -observed["harmful_overrides"],
            observed["term_correct"],
            observed["format_valid"],
        ]
        if "protocol_fitness_key" in method:
            _validate_protocol_key(method["protocol_fitness_key"], key, f"{genome_id_value} method protocol_fitness_key")
        if top_protocol is not None:
            top_entry = top_protocol[genome_id_value]
            if not isinstance(top_entry, dict) or "protocol_fitness_key" not in top_entry:
                raise EvolutionError("top-level protocol_fitness entry is malformed")
            _validate_protocol_key(top_entry["protocol_fitness_key"], key, f"{genome_id_value} top-level protocol key")
        fitness[genome_id_value] = {
            **observed,
            "calls": calls,
            "case_count": case_count,
            "fitness_key": key,
        }
    return fitness


def _validate_fitness(value: Any, expected_cases: int, expected_calls: int) -> dict[str, Any]:
    required = {
        "exact_cases", "weakest_block_exact", "harmful_overrides", "term_correct", "format_valid",
        "block_exact", "calls", "case_count", "fitness_key",
    }
    _keys(value, required, "fitness")
    for key in required - {"block_exact", "fitness_key"}:
        _integer(value[key], f"fitness {key}")
    if value["case_count"] != expected_cases or value["calls"] != expected_calls:
        raise EvolutionError("fitness budget differs from its phase")
    expected_key = [
        value["exact_cases"], value["weakest_block_exact"], -value["harmful_overrides"],
        value["term_correct"], value["format_valid"],
    ]
    _validate_protocol_key(value["fitness_key"], expected_key, "fitness_key")
    return value


def _best_entry(entries: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    best_key = max(tuple(entry[2]["fitness_key"]) for entry in entries)
    tied = [entry for entry in entries if tuple(entry[2]["fitness_key"]) == best_key]
    return min(tied, key=lambda entry: entry[1]["genome_sha256"])


def select_round(
    round_number: int,
    candidates: dict[str, Any],
    candidate_file_hash: str,
    summary: Any,
    summary_file_hash: str,
    case_matrix_path: Path,
    answers_path: Path,
    predictions_path: Path,
    catalog_hash: str,
    expected_answers_hash: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    validate_candidates(candidates, catalog_hash)
    if round_number != candidates["round"]:
        raise EvolutionError("--round differs from candidate artifact")
    genome_lookup = {item["genome_id"]: item for item in candidates["genomes"]}
    genome_ids = [item["genome_id"] for item in candidates["genomes"]]
    fitness = evaluate_scores(
        summary, genome_ids, case_matrix_path, answers_path, predictions_path,
        candidates["search_blocks"], 24, 20,
    )
    matrix_hash = sha256_file(case_matrix_path)
    answers_hash = sha256_file(answers_path)
    predictions_hash = sha256_file(predictions_path)
    if answers_hash != expected_answers_hash:
        raise EvolutionError(f"round {round_number} answers differ from the frozen benchmark manifest")
    best_freeze: dict[str, Any] | None = None
    best_freeze_hash = candidates["best_founder_freeze_artifact_sha256"]
    if round_number == 1:
        founders = [
            (pair["slot_id"], genome_lookup[pair["parent_genome_id"]], fitness[pair["parent_genome_id"]])
            for pair in candidates["parent_child_pairs"]
        ]
        best_slot, best_genome, best_fitness = _best_entry(founders)
        best_freeze = seal_artifact({
            "schema_version": BEST_FOUNDER_SCHEMA,
            **_common(catalog_hash),
            "round_frozen": 1,
            "source_candidates_artifact_sha256": candidates["artifact_sha256"],
            "source_candidates_file_sha256": candidate_file_hash,
            "source_summary_file_sha256": summary_file_hash,
            "source_case_matrix_file_sha256": matrix_hash,
            "source_answers_file_sha256": answers_hash,
            "source_predictions_file_sha256": predictions_hash,
            "selection_rule": list(FITNESS_RULE),
            "genome_hash_tie_break": "lexicographically smaller canonical genome_sha256",
            "founder_slot_id": best_slot,
            "founder_genome": best_genome,
            "fitness": best_fitness,
            "freeze_status": "best_founder_frozen_after_round_1_before_validation_or_final_answers",
        })
        best_freeze_hash = best_freeze["artifact_sha256"]
    slots: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for pair in candidates["parent_child_pairs"]:
        parent = genome_lookup[pair["parent_genome_id"]]
        child = genome_lookup[pair["child_genome_id"]]
        parent_fitness = fitness[parent["genome_id"]]
        child_fitness = fitness[child["genome_id"]]
        if tuple(child_fitness["fitness_key"]) > tuple(parent_fitness["fitness_key"]):
            survivor = child
            decision = "replace_parent"
        else:
            survivor = parent
            decision = (
                "keep_parent_exact_tie"
                if child_fitness["fitness_key"] == parent_fitness["fitness_key"]
                else "keep_better_parent"
            )
        slots.append({"slot_id": pair["slot_id"], "genome": survivor})
        receipts.append({
            "slot_id": pair["slot_id"],
            "parent_genome_id": parent["genome_id"],
            "child_genome_id": child["genome_id"],
            "parent_fitness": parent_fitness,
            "child_fitness": child_fitness,
            "decision": decision,
            "survivor_genome_id": survivor["genome_id"],
        })
    body = {
        "schema_version": PARENTS_SCHEMA,
        **_common(catalog_hash),
        "round_completed": round_number,
        "source_candidates_artifact_sha256": candidates["artifact_sha256"],
        "source_candidates_file_sha256": candidate_file_hash,
        "source_summary_file_sha256": summary_file_hash,
        "source_case_matrix_file_sha256": matrix_hash,
        "source_answers_file_sha256": answers_hash,
        "source_predictions_file_sha256": predictions_hash,
        "best_founder_freeze_artifact_sha256": best_freeze_hash,
        "history_genome_sha256s": candidates["history_genome_sha256s"],
        "slots": slots,
        "comparison_receipts": receipts,
    }
    survivors = seal_artifact(body)
    return survivors, best_freeze


def validate_best_founder(value: Any, catalog_hash: str) -> dict[str, Any]:
    freeze = verify_artifact(value, BEST_FOUNDER_SCHEMA)
    _check_common(freeze, catalog_hash)
    if freeze.get("round_frozen") != 1 or freeze.get("founder_slot_id") not in SLOT_IDS:
        raise EvolutionError("best founder was not frozen from round 1")
    genome = validate_genome(freeze.get("founder_genome"))
    if genome["lineage"]["operation"] != "founder" or genome["lineage"]["designated_parent_slot"] != freeze["founder_slot_id"]:
        raise EvolutionError("best-founder artifact does not contain a founder from its slot")
    _validate_fitness(freeze.get("fitness"), 24, 20)
    for key in (
        "source_candidates_artifact_sha256", "source_candidates_file_sha256", "source_summary_file_sha256",
        "source_case_matrix_file_sha256", "source_answers_file_sha256", "source_predictions_file_sha256",
    ):
        _sha(freeze.get(key), key)
    if freeze.get("selection_rule") != list(FITNESS_RULE):
        raise EvolutionError("best-founder selection rule differs from protocol")
    return freeze


def select_validation(
    population: dict[str, Any],
    population_file_hash: str,
    summary: Any,
    summary_file_hash: str,
    case_matrix_path: Path,
    answers_path: Path,
    predictions_path: Path,
    best_founder: dict[str, Any],
    best_founder_file_hash: str,
    catalog: dict[str, Any],
    catalog_hash: str,
    expected_answers_hash: str,
) -> dict[str, Any]:
    validate_parent_population(population, catalog, catalog_hash)
    if population["round_completed"] != ROUNDS:
        raise EvolutionError("validation selection requires the six round-08 survivors")
    validate_best_founder(best_founder, catalog_hash)
    if population["best_founder_freeze_artifact_sha256"] != best_founder["artifact_sha256"]:
        raise EvolutionError("final survivors are not bound to the supplied best-founder freeze")
    if sha256_file(answers_path) != expected_answers_hash:
        raise EvolutionError("validation answers differ from the frozen benchmark manifest")
    slots = population["slots"]
    genome_ids = [item["genome"]["genome_id"] for item in slots]
    fitness = evaluate_scores(
        summary, genome_ids, case_matrix_path, answers_path, predictions_path,
        _validation_blocks(), 72, 60,
    )
    entries = [(item["slot_id"], item["genome"], fitness[item["genome"]["genome_id"]]) for item in slots]
    champion_slot, champion_genome, champion_fitness = _best_entry(entries)
    survivor_scores = [
        {"slot_id": slot_id, "genome_id": genome["genome_id"], "fitness": item_fitness}
        for slot_id, genome, item_fitness in entries
    ]
    body = {
        "schema_version": CHAMPION_SCHEMA,
        **_common(catalog_hash),
        "source_population_artifact_sha256": population["artifact_sha256"],
        "source_population_file_sha256": population_file_hash,
        "source_summary_file_sha256": summary_file_hash,
        "source_case_matrix_file_sha256": sha256_file(case_matrix_path),
        "source_answers_file_sha256": sha256_file(answers_path),
        "source_predictions_file_sha256": sha256_file(predictions_path),
        "source_best_founder_artifact_sha256": best_founder["artifact_sha256"],
        "source_best_founder_file_sha256": best_founder_file_hash,
        "validation_blocks": _validation_blocks(),
        "selection_rule": list(FITNESS_RULE),
        "genome_hash_tie_break": "lexicographically smaller canonical genome_sha256",
        "survivor_scores": survivor_scores,
        "champion_slot_id": champion_slot,
        "champion_genome": champion_genome,
        "champion_fitness": champion_fitness,
        "best_founder_slot_id": best_founder["founder_slot_id"],
        "best_founder_genome": best_founder["founder_genome"],
        "freeze_status": "validation_champion_frozen_before_hidden_final_answers",
    }
    return seal_artifact(body)


def _write_fake_evaluation(
    directory: Path, genomes: list[dict[str, Any]], blocks: list[str], calls: int, exact_by_id: dict[str, int]
) -> tuple[dict[str, Any], str, Path, Path, Path]:
    case_ids = [f"X{i:03d}" for i in range(1, len(blocks) * 12 + 1)]
    answers_path = directory / f"answers-{blocks[0]}.jsonl"
    predictions_path = directory / f"predictions-{blocks[0]}.json"
    matrix_path = directory / f"matrix-{blocks[0]}.csv"
    answers_path.write_text("".join(json.dumps({"case_id": case_id}) + "\n" for case_id in case_ids), encoding="utf-8")
    predictions_path.write_text(json.dumps({"genomes": [item["genome_id"] for item in genomes]}), encoding="utf-8")
    fieldnames = ["case_id", "block"]
    for genome in genomes:
        genome_id_value = genome["genome_id"]
        fieldnames.extend([
            f"{genome_id_value}.exact", f"{genome_id_value}.harmful_override",
            f"{genome_id_value}.term_correct", f"{genome_id_value}.format_valid",
        ])
    metrics: dict[str, dict[str, int]] = {}
    rows: list[dict[str, Any]] = []
    for index, case_id in enumerate(case_ids):
        row: dict[str, Any] = {"case_id": case_id, "block": blocks[index // 12]}
        for genome in genomes:
            genome_id_value = genome["genome_id"]
            exact = int(index < exact_by_id[genome_id_value])
            row[f"{genome_id_value}.exact"] = exact
            row[f"{genome_id_value}.harmful_override"] = 0
            row[f"{genome_id_value}.term_correct"] = 5 * exact
            row[f"{genome_id_value}.format_valid"] = 1
        rows.append(row)
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    matrix_metrics, _ = _read_case_matrix(matrix_path, [item["genome_id"] for item in genomes], blocks, len(case_ids))
    methods: dict[str, Any] = {}
    protocol: dict[str, Any] = {}
    for genome in genomes:
        genome_id_value = genome["genome_id"]
        observed = matrix_metrics[genome_id_value]
        key = [observed["exact_cases"], observed["weakest_block_exact"], 0, observed["term_correct"], observed["format_valid"]]
        methods[genome_id_value] = {
            "calls": calls, "completed_calls": calls, "case_count": len(case_ids),
            "exact_cases": observed["exact_cases"], "harmful_overrides": 0,
            "term_correct": observed["term_correct"], "format_valid": observed["format_valid"],
            "protocol_fitness_key": key,
        }
        protocol[genome_id_value] = {"protocol_fitness_key": key}
    summary = {
        "schema_version": "4.0",
        "n_cases": len(case_ids),
        "inputs": {"answers_sha256": sha256_file(answers_path), "predictions_sha256": sha256_file(predictions_path)},
        "methods": methods,
        "protocol_fitness": protocol,
    }
    return summary, sha256_bytes(canonical_bytes(summary)), matrix_path, answers_path, predictions_path


def self_test(catalog: dict[str, Any], catalog_hash: str) -> dict[str, Any]:
    initial = init_population(catalog, catalog_hash)
    validate_parent_population(initial, catalog, catalog_hash)
    duplicate = make_round(1, initial, sha256_bytes(canonical_bytes(initial)), catalog, catalog_hash)
    round_one = make_round(1, initial, sha256_bytes(canonical_bytes(initial)), catalog, catalog_hash)
    assert canonical_bytes(duplicate) == canonical_bytes(round_one)
    validate_candidates(round_one, catalog_hash)
    assert Counter(pair["operation"] for pair in round_one["parent_child_pairs"]) == {
        "one_gene_mutation": 4, "crossover": 2,
    }
    with tempfile.TemporaryDirectory(prefix="experiment-04-evolve-test-") as temporary:
        directory = Path(temporary)
        population = initial
        best_founder: dict[str, Any] | None = None
        for round_number in range(1, ROUNDS + 1):
            candidates = make_round(
                round_number, population, sha256_bytes(canonical_bytes(population)), catalog, catalog_hash
            )
            exact = {item["genome_id"]: 8 for item in candidates["genomes"]}
            if round_number == 1:
                first_pair = candidates["parent_child_pairs"][0]
                exact[first_pair["child_genome_id"]] = 9
            summary, summary_hash, matrix, answers, predictions = _write_fake_evaluation(
                directory, candidates["genomes"], candidates["search_blocks"], 20, exact
            )
            population, new_freeze = select_round(
                round_number, candidates, sha256_bytes(canonical_bytes(candidates)), summary, summary_hash,
                matrix, answers, predictions, catalog_hash, sha256_file(answers),
            )
            if new_freeze is not None:
                best_founder = new_freeze
            validate_parent_population(population, catalog, catalog_hash)
        assert population["round_completed"] == 8
        assert len(population["history_genome_sha256s"]) == 54
        assert best_founder is not None
        validate_best_founder(best_founder, catalog_hash)
        validation_genomes = [item["genome"] for item in population["slots"]]
        validation_exact = {item["genome_id"]: 20 for item in validation_genomes}
        validation_exact[validation_genomes[-1]["genome_id"]] = 21
        summary, summary_hash, matrix, answers, predictions = _write_fake_evaluation(
            directory, validation_genomes, _validation_blocks(), 60, validation_exact
        )
        champion = select_validation(
            population, sha256_bytes(canonical_bytes(population)), summary, summary_hash,
            matrix, answers, predictions, best_founder, sha256_bytes(canonical_bytes(best_founder)),
            catalog, catalog_hash, sha256_file(answers),
        )
        verify_artifact(champion, CHAMPION_SCHEMA)
        assert champion["champion_genome"]["genome_id"] == validation_genomes[-1]["genome_id"]
        bad_summary = copy.deepcopy(summary)
        bad_summary["inputs"]["answers_sha256"] = "0" * 64
        try:
            evaluate_scores(
                bad_summary, [item["genome_id"] for item in validation_genomes], matrix, answers,
                predictions, _validation_blocks(), 72, 60,
            )
        except EvolutionError:
            pass
        else:
            raise AssertionError("unbound score summary was accepted")
    return {
        "status": "ok",
        "rounds_exercised": 8,
        "founders": 6,
        "candidates_per_round": 12,
        "mutations_per_round": 4,
        "crossovers_per_round": 2,
        "unique_genomes_after_round_8": 54,
        "pairwise_tie_keeps_parent": True,
        "best_founder_frozen_after_round_1": True,
        "validation_cases_per_survivor": 72,
        "score_hash_tamper_rejected": True,
    }


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_BENCHMARK_MANIFEST)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="create the six frozen founders")
    _add_output(init_parser)
    make_parser = commands.add_parser("make-round", help="create six children for the next fixed round")
    make_parser.add_argument("--round", type=int, required=True)
    make_parser.add_argument("--parents", type=Path, required=True)
    _add_output(make_parser)
    select_parser = commands.add_parser("select-round", help="apply paired parent-child replacement")
    select_parser.add_argument("--round", type=int, required=True)
    select_parser.add_argument("--candidates", type=Path, required=True)
    select_parser.add_argument("--summary", type=Path, required=True)
    select_parser.add_argument("--case-matrix", type=Path, required=True)
    select_parser.add_argument("--answers", type=Path, required=True)
    select_parser.add_argument("--predictions", type=Path, required=True)
    select_parser.add_argument("--best-founder-output", type=Path)
    _add_output(select_parser)
    validation_parser = commands.add_parser("select-validation", help="freeze champion from six survivors")
    validation_parser.add_argument("--population", type=Path, required=True)
    validation_parser.add_argument("--summary", type=Path, required=True)
    validation_parser.add_argument("--case-matrix", type=Path, required=True)
    validation_parser.add_argument("--answers", type=Path, required=True)
    validation_parser.add_argument("--predictions", type=Path, required=True)
    validation_parser.add_argument("--best-founder", type=Path, required=True)
    _add_output(validation_parser)
    commands.add_parser("self-test", help="exercise all eight rounds and tamper checks")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        catalog, catalog_hash = load_catalog(args.catalog)
        if args.command == "init":
            result = init_population(catalog, catalog_hash)
            atomic_write_json(args.output, result, args.overwrite)
        elif args.command == "make-round":
            parents, parent_file_hash = load_json(args.parents)
            result = make_round(args.round, parents, parent_file_hash, catalog, catalog_hash)
            atomic_write_json(args.output, result, args.overwrite)
        elif args.command == "select-round":
            if not 1 <= args.round <= ROUNDS:
                raise EvolutionError("--round must be from 1 through 8")
            if (args.round == 1) != (args.best_founder_output is not None):
                raise EvolutionError("--best-founder-output is required only for round 1")
            if args.best_founder_output is not None and args.output.resolve() == args.best_founder_output.resolve():
                raise EvolutionError("round-1 survivor and best-founder outputs must be different paths")
            candidates, candidate_file_hash = load_json(args.candidates)
            summary, summary_file_hash = load_json(args.summary)
            answer_bindings = load_answer_bindings(args.benchmark_manifest)
            expected_answers_hash = answer_bindings[f"hidden/search_R{args.round:02d}_answers.jsonl"]
            result, best_freeze = select_round(
                args.round, candidates, candidate_file_hash, summary, summary_file_hash,
                args.case_matrix, args.answers, args.predictions, catalog_hash, expected_answers_hash,
            )
            if best_freeze is not None:
                if args.best_founder_output.exists() and not args.overwrite:
                    raise EvolutionError(f"refusing to overwrite {args.best_founder_output}; pass --overwrite intentionally")
                atomic_write_json(args.best_founder_output, best_freeze, args.overwrite)
            atomic_write_json(args.output, result, args.overwrite)
        elif args.command == "select-validation":
            population, population_file_hash = load_json(args.population)
            summary, summary_file_hash = load_json(args.summary)
            best_founder, best_founder_file_hash = load_json(args.best_founder)
            answer_bindings = load_answer_bindings(args.benchmark_manifest)
            result = select_validation(
                population, population_file_hash, summary, summary_file_hash, args.case_matrix,
                args.answers, args.predictions, best_founder, best_founder_file_hash, catalog, catalog_hash,
                answer_bindings["hidden/validation_answers.jsonl"],
            )
            atomic_write_json(args.output, result, args.overwrite)
        else:
            print(json.dumps(self_test(catalog, catalog_hash), indent=2, sort_keys=True))
        return 0
    except (EvolutionError, OSError, csv.Error) as exc:
        parser.exit(2, f"evolve.py: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
