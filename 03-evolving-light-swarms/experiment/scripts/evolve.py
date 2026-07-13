#!/usr/bin/env python3
"""Deterministic symbolic evolution controller for Swarm Seeds Experiment 03.

This program never invokes a model. It creates six-genome population artifacts,
ranks aggregate score JSON, makes four one-gene mutations plus two crossovers,
selects three validation finalists, and freezes one validation champion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


EXPERIMENT_ID = "swarm-seeds-03"
PUBLIC_LABEL = "Light reasoning"
PROVIDER_EFFORT = "low"
CALL_BUDGET = 10
WORKER_LENS_SLOTS = 9
POPULATION_SIZE = 6
GENERATION_COUNT = 3
FINAL_GENERATION = 2
TRAINING_CASES = 12
VALIDATION_CASES = 24
DEFAULT_SEED = "swarm-seeds-03-evolution-v1"
SELECTION_RULE = (
    "more exact next-five cases",
    "fewer harmful overrides",
    "more correct terms",
    "more format-valid cases",
    "lexicographically larger canonical genome hash",
)

POPULATION_SCHEMA = "experiment-03-population-v1"
VALIDATION_SCHEMA = "experiment-03-validation-selection-v1"
CHAMPION_SCHEMA = "experiment-03-champion-freeze-v1"
CATALOG_SCHEMA = "experiment-03-genome-catalog-v1"

EXPECTED_LENSES = (
    "generalist",
    "differences",
    "recurrences",
    "streams",
    "modular",
    "simplicity",
    "diversifier",
    "audit",
)
EXPECTED_POLICIES = (
    "plurality_preserving",
    "evidence_weighted",
    "minority_aware",
    "robustness_first",
)
EXPECTED_SPECIES = {"consensus", "falsification", "specialization", "paired_revision"}
EXPECTED_TOPOLOGIES: dict[str, tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = {
    "consensus_9p_1j": (
        "consensus",
        (
            ("proposer", tuple(f"W{index:02d}" for index in range(1, 10))),
            ("judge", ("J01",)),
        ),
    ),
    "falsification_7p_2c_1j": (
        "falsification",
        (
            ("proposer", tuple(f"W{index:02d}" for index in range(1, 8))),
            ("critic", ("W08", "W09")),
            ("judge", ("J01",)),
        ),
    ),
    "specialization_7p_2v_1j": (
        "specialization",
        (
            ("proposer", tuple(f"W{index:02d}" for index in range(1, 8))),
            ("verifier", ("W08", "W09")),
            ("judge", ("J01",)),
        ),
    ),
    "paired_revision_5p_2r_2v_1j": (
        "paired_revision",
        (
            ("proposer", tuple(f"W{index:02d}" for index in range(1, 6))),
            ("reviser", ("W06", "W07")),
            ("verifier", ("W08", "W09")),
            ("judge", ("J01",)),
        ),
    ),
}

SCRIPT_PATH = Path(__file__).resolve()
EXPERIMENT_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_CATALOG = EXPERIMENT_ROOT / "genomes" / "GENOME_CATALOG.json"
DEFAULT_LENSES = EXPERIMENT_ROOT / "prompts" / "LENSES.json"
DEFAULT_BENCHMARK_MANIFEST = EXPERIMENT_ROOT / "benchmark" / "manifest.json"


class EvolutionError(ValueError):
    """Raised when a genome, score, or evolution artifact is unsafe."""


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
    except json.JSONDecodeError as exc:
        raise EvolutionError(f"invalid JSON: {exc}") from exc


def load_json(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
    return parse_json_strict(raw.decode("utf-8")), sha256_bytes(raw)


def seal_artifact(value: dict[str, Any]) -> dict[str, Any]:
    if "artifact_sha256" in value:
        raise EvolutionError("artifact must be unsealed before hashing")
    output = copy.deepcopy(value)
    output["artifact_sha256"] = sha256_bytes(canonical_bytes(value))
    return output


def verify_artifact(value: Any, schema: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise EvolutionError(f"expected {schema} artifact")
    recorded = value.get("artifact_sha256")
    body = dict(value)
    body.pop("artifact_sha256", None)
    actual = sha256_bytes(canonical_bytes(body))
    if recorded != actual:
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


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise EvolutionError(f"{label} must be an object")
    if set(value) != expected:
        raise EvolutionError(
            f"{label} keys differ; missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}"
        )


def _seeded_rng(seed: str, label: str) -> random.Random:
    integer = int(sha256_bytes(f"{seed}\0{label}".encode("utf-8")), 16)
    return random.Random(integer)


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvolutionError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _locus_value(genes: dict[str, Any], locus: str) -> str:
    if locus == "topology_id":
        return genes["topology_id"]
    if locus == "final_policy_id":
        return genes["final_policy_id"]
    if locus.startswith("role_lenses."):
        index_text = locus.removeprefix("role_lenses.")
        if index_text.isdigit() and 0 <= int(index_text) < WORKER_LENS_SLOTS:
            return genes["role_lenses"][int(index_text)]
    raise EvolutionError(f"unknown symbolic gene locus: {locus}")


def validate_genes(genes: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(genes, {"topology_id", "role_lenses", "final_policy_id"}, "genes")
    topology_id = genes["topology_id"]
    lenses = genes["role_lenses"]
    final_policy = genes["final_policy_id"]
    if topology_id not in catalog["topologies"]:
        raise EvolutionError(f"unknown topology_id: {topology_id}")
    if not isinstance(lenses, list) or len(lenses) != WORKER_LENS_SLOTS:
        raise EvolutionError("role_lenses must contain exactly nine lens IDs")
    if any(lens not in catalog["lens_ids"] for lens in lenses):
        raise EvolutionError("role_lenses contains an unknown lens ID")
    if final_policy not in catalog["final_policy_ids"]:
        raise EvolutionError(f"unknown final_policy_id: {final_policy}")
    return copy.deepcopy(genes)


def genome_hash(genes: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(genes))


def genome_id(genes_sha256: str) -> str:
    return "G-" + genes_sha256[:12].upper()


def make_genome(genes: dict[str, Any], lineage: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    genes = validate_genes(genes, catalog)
    digest = genome_hash(genes)
    output = {
        "genome_id": genome_id(digest),
        "genome_sha256": digest,
        "genes": genes,
        "lineage": copy.deepcopy(lineage),
    }
    validate_genome(output, catalog)
    return output


def validate_genome(genome: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(genome, {"genome_id", "genome_sha256", "genes", "lineage"}, "genome")
    genes = validate_genes(genome["genes"], catalog)
    digest = genome_hash(genes)
    if genome["genome_sha256"] != digest or genome["genome_id"] != genome_id(digest):
        raise EvolutionError("genome ID or hash does not match its symbolic genes")
    lineage = genome["lineage"]
    _exact_keys(
        lineage,
        {
            "generation",
            "operation",
            "parents",
            "founding_species",
            "founder_id",
            "mutation",
            "crossover_sources",
        },
        "genome.lineage",
    )
    generation = lineage["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or not 0 <= generation <= FINAL_GENERATION:
        raise EvolutionError("lineage generation is outside the frozen three-generation run")
    operation = lineage["operation"]
    if operation not in {"founder", "one_gene_mutation", "crossover"}:
        raise EvolutionError(f"unknown lineage operation: {operation}")
    parents = lineage["parents"]
    if not isinstance(parents, list) or len(set(parents)) != len(parents) or any(not isinstance(item, str) for item in parents):
        raise EvolutionError("lineage parents must be unique genome IDs")
    species = lineage["founding_species"]
    if not isinstance(species, list) or not species or species != sorted(set(species)) or not set(species) <= EXPECTED_SPECIES:
        raise EvolutionError("founding_species must be a sorted non-empty subset of the four species")
    founder_id = lineage["founder_id"]
    mutation = lineage["mutation"]
    crossover = lineage["crossover_sources"]
    if operation == "founder":
        if generation != 0 or parents or not isinstance(founder_id, str) or mutation is not None or crossover is not None:
            raise EvolutionError("founder lineage is malformed")
        founders = {item["founder_id"]: item for item in catalog["founders"]}
        if founder_id not in founders:
            raise EvolutionError(f"unknown founder_id: {founder_id}")
        founder = founders[founder_id]
        if founder["genes"] != genes or species != [founder["species"]]:
            raise EvolutionError("founder genes or species differ from the frozen catalog")
    elif operation == "one_gene_mutation":
        if generation < 1 or len(parents) != 1 or founder_id is not None or not isinstance(mutation, dict) or crossover is not None:
            raise EvolutionError("mutation lineage is malformed")
        _exact_keys(mutation, {"locus", "from", "to"}, "mutation")
        if mutation["from"] == mutation["to"]:
            raise EvolutionError("one-gene mutation must change its selected locus")
        locus = mutation["locus"]
        if not isinstance(locus, str):
            raise EvolutionError("mutation locus must be a string")
        _locus_value(genes, locus)
        if not isinstance(mutation["from"], str) or not isinstance(mutation["to"], str):
            raise EvolutionError("mutation endpoints must be symbolic IDs")
        if locus == "topology_id":
            allowed = set(catalog["topologies"])
        elif locus == "final_policy_id":
            allowed = set(catalog["final_policy_ids"])
        else:
            allowed = set(catalog["lens_ids"])
        if mutation["from"] not in allowed or mutation["to"] not in allowed:
            raise EvolutionError("mutation endpoints are outside the frozen grammar")
    else:
        if generation < 1 or len(parents) != 2 or founder_id is not None or mutation is not None or not isinstance(crossover, dict):
            raise EvolutionError("crossover lineage is malformed")
        _exact_keys(crossover, {"topology_id", "role_lenses", "final_policy_id"}, "crossover_sources")
        if crossover["topology_id"] not in parents or crossover["final_policy_id"] not in parents:
            raise EvolutionError("crossover scalar source is not a parent")
        lens_sources = crossover["role_lenses"]
        if not isinstance(lens_sources, list) or len(lens_sources) != WORKER_LENS_SLOTS:
            raise EvolutionError("crossover role_lenses source map must have nine entries")
        for source in lens_sources:
            _exact_keys(source, {"parent", "source_slot"}, "crossover lens source")
            if source["parent"] not in parents or source["source_slot"] not in {
                f"W{index:02d}" for index in range(1, 10)
            }:
                raise EvolutionError("crossover lens source is invalid")
    return genome


def validate_lineage_against_parents(
    genome: dict[str, Any], parent_lookup: dict[str, dict[str, Any]], catalog: dict[str, Any]
) -> None:
    """Verify that recorded symbolic lineage reconstructs the child exactly."""
    lineage = genome["lineage"]
    if lineage["operation"] == "founder":
        return
    try:
        parents = [parent_lookup[parent_id] for parent_id in lineage["parents"]]
    except KeyError as exc:
        raise EvolutionError(f"lineage references unavailable parent {exc.args[0]}") from exc
    if any(parent["lineage"]["generation"] >= lineage["generation"] for parent in parents):
        raise EvolutionError("a derived genome must use parents from earlier generations")
    if lineage["operation"] == "one_gene_mutation":
        parent = parents[0]
        mutation = lineage["mutation"]
        loci = [
            "topology_id",
            *(f"role_lenses.{index}" for index in range(WORKER_LENS_SLOTS)),
            "final_policy_id",
        ]
        changed = [
            locus
            for locus in loci
            if _locus_value(parent["genes"], locus) != _locus_value(genome["genes"], locus)
        ]
        if changed != [mutation["locus"]]:
            raise EvolutionError("mutation lineage does not describe exactly one changed gene")
        if (
            mutation["from"] != _locus_value(parent["genes"], mutation["locus"])
            or mutation["to"] != _locus_value(genome["genes"], mutation["locus"])
        ):
            raise EvolutionError("mutation endpoints do not reconstruct the child")
        if lineage["founding_species"] != parent["lineage"]["founding_species"]:
            raise EvolutionError("mutation founding species differ from its parent")
        return

    by_id = {parent["genome_id"]: parent for parent in parents}
    sources = lineage["crossover_sources"]
    topology_parent = by_id[sources["topology_id"]]
    policy_parent = by_id[sources["final_policy_id"]]
    if genome["genes"]["topology_id"] != topology_parent["genes"]["topology_id"]:
        raise EvolutionError("crossover topology source does not reconstruct the child")
    if genome["genes"]["final_policy_id"] != policy_parent["genes"]["final_policy_id"]:
        raise EvolutionError("crossover policy source does not reconstruct the child")
    for target_index, source in enumerate(sources["role_lenses"]):
        source_index = int(source["source_slot"].removeprefix("W")) - 1
        source_value = by_id[source["parent"]]["genes"]["role_lenses"][source_index]
        if genome["genes"]["role_lenses"][target_index] != source_value:
            raise EvolutionError("crossover lens source map does not reconstruct the child")
    expected_species = sorted(
        set(parents[0]["lineage"]["founding_species"])
        | set(parents[1]["lineage"]["founding_species"])
    )
    if lineage["founding_species"] != expected_species:
        raise EvolutionError("crossover founding species differ from its parents")


def load_benchmark_bindings(path: Path = DEFAULT_BENCHMARK_MANIFEST) -> dict[str, str]:
    manifest, manifest_file_hash = load_json(path)
    if not isinstance(manifest, dict) or manifest.get("benchmark_id") != "ruleweave-5-evolution-v1":
        raise EvolutionError("invalid frozen RuleWeave-5 benchmark manifest")
    if manifest.get("splits") != {"training": TRAINING_CASES, "validation": VALIDATION_CASES, "final": 48}:
        raise EvolutionError("benchmark split sizes differ from the frozen protocol")
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise EvolutionError("benchmark manifest has no checksum map")
    relative_paths = {
        "training_answers_sha256": "hidden/training_answers.jsonl",
        "validation_answers_sha256": "hidden/validation_answers.jsonl",
    }
    result = {"benchmark_manifest_file_sha256": manifest_file_hash}
    for output_key, relative in relative_paths.items():
        declared = _require_sha256(checksums.get(relative), f"benchmark checksum {relative}")
        actual = sha256_file(path.parent / relative)
        if actual != declared:
            raise EvolutionError(f"benchmark file hash differs from manifest: {relative}")
        result[output_key] = declared
    return result


def load_catalog(path: Path = DEFAULT_CATALOG, lenses_path: Path = DEFAULT_LENSES) -> tuple[dict[str, Any], dict[str, str]]:
    catalog, catalog_file_hash = load_json(path)
    if not isinstance(catalog, dict) or catalog.get("schema_version") != CATALOG_SCHEMA:
        raise EvolutionError("invalid Experiment 03 genome catalog")
    required = {
        "schema_version",
        "experiment_id",
        "public_condition_label",
        "provider_reasoning_effort",
        "call_budget_per_genome",
        "worker_lens_slots",
        "population_size",
        "generation_count",
        "lens_ids",
        "final_policy_ids",
        "topologies",
        "founders",
    }
    _exact_keys(catalog, required, "catalog")
    fixed = (
        catalog["experiment_id"] == EXPERIMENT_ID
        and catalog["public_condition_label"] == PUBLIC_LABEL
        and catalog["provider_reasoning_effort"] == PROVIDER_EFFORT
        and catalog["call_budget_per_genome"] == CALL_BUDGET
        and catalog["worker_lens_slots"] == WORKER_LENS_SLOTS
        and catalog["population_size"] == POPULATION_SIZE
        and catalog["generation_count"] == GENERATION_COUNT
    )
    if not fixed:
        raise EvolutionError("catalog changes a frozen Experiment 03 constant")
    if tuple(catalog["lens_ids"]) != EXPECTED_LENSES:
        raise EvolutionError("catalog lens IDs differ from the frozen protocol")
    if tuple(catalog["final_policy_ids"]) != EXPECTED_POLICIES:
        raise EvolutionError("catalog final policies differ from the frozen protocol")
    if set(catalog["topologies"]) != set(EXPECTED_TOPOLOGIES):
        raise EvolutionError("catalog topology IDs differ from the frozen protocol")
    for topology_id, (species, expected_stages) in EXPECTED_TOPOLOGIES.items():
        topology = catalog["topologies"][topology_id]
        _exact_keys(topology, {"founding_species", "stages"}, f"topology {topology_id}")
        if topology["founding_species"] != species:
            raise EvolutionError(f"topology {topology_id} has the wrong founding species")
        stages = topology["stages"]
        observed: list[tuple[str, tuple[str, ...]]] = []
        for index, stage in enumerate(stages):
            _exact_keys(stage, {"stage_index", "role", "slots"}, f"topology {topology_id} stage")
            if stage["stage_index"] != index or not isinstance(stage["slots"], list):
                raise EvolutionError(f"topology {topology_id} has non-contiguous stages")
            observed.append((stage["role"], tuple(stage["slots"])))
        if tuple(observed) != expected_stages:
            raise EvolutionError(f"topology {topology_id} stage counts differ from the frozen protocol")
        slots = [slot for _, stage_slots in observed for slot in stage_slots]
        if len(slots) != CALL_BUDGET or set(slots) != {"J01", *(f"W{i:02d}" for i in range(1, 10))}:
            raise EvolutionError(f"topology {topology_id} must use W01-W09 and J01 exactly once")

    lenses, lenses_file_hash = load_json(lenses_path)
    if (
        not isinstance(lenses, dict)
        or not isinstance(lenses.get("worker"), dict)
        or set(lenses["worker"]) != set(EXPECTED_LENSES)
        or any(not isinstance(text, str) or not text.strip() for text in lenses["worker"].values())
    ):
        raise EvolutionError("prompt LENSES.json worker IDs do not match the genome catalog")
    if (
        not isinstance(lenses.get("judge"), dict)
        or set(lenses["judge"]) != set(EXPECTED_POLICIES)
        or any(not isinstance(text, str) or not text.strip() for text in lenses["judge"].values())
    ):
        raise EvolutionError("prompt LENSES.json judge policies do not match the genome catalog")

    founders = catalog["founders"]
    if not isinstance(founders, list) or len(founders) != POPULATION_SIZE:
        raise EvolutionError("catalog must contain exactly six founders")
    ids: set[str] = set()
    hashes: set[str] = set()
    species_seen: set[str] = set()
    for founder in founders:
        _exact_keys(founder, {"founder_id", "species", "genes"}, "founder")
        if not isinstance(founder["founder_id"], str) or founder["founder_id"] in ids:
            raise EvolutionError("founder IDs must be unique strings")
        ids.add(founder["founder_id"])
        if founder["species"] not in EXPECTED_SPECIES:
            raise EvolutionError("founder has an unknown species")
        species_seen.add(founder["species"])
        genes = validate_genes(founder["genes"], catalog)
        topology_species = catalog["topologies"][genes["topology_id"]]["founding_species"]
        if founder["species"] != topology_species:
            raise EvolutionError("founder species does not match its topology")
        digest = genome_hash(genes)
        if digest in hashes:
            raise EvolutionError("founder genomes must be distinct")
        hashes.add(digest)
    if species_seen != EXPECTED_SPECIES:
        raise EvolutionError("all four founding species must appear in Generation 0")
    hashes_out = {
        "catalog_file_sha256": catalog_file_hash,
        "catalog_semantic_sha256": sha256_bytes(canonical_bytes(catalog)),
        "lenses_file_sha256": lenses_file_hash,
        **load_benchmark_bindings(),
    }
    return catalog, hashes_out


def common_artifact_fields(catalog_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "public_condition_label": PUBLIC_LABEL,
        "provider_reasoning_effort": PROVIDER_EFFORT,
        "call_budget_per_genome": CALL_BUDGET,
        "population_size": POPULATION_SIZE,
        "generation_count": GENERATION_COUNT,
        **catalog_hashes,
    }


def validate_population(value: Any, catalog: dict[str, Any], catalog_hashes: dict[str, str]) -> dict[str, Any]:
    population = verify_artifact(value, POPULATION_SCHEMA)
    expected_keys = set(common_artifact_fields(catalog_hashes)) | {
        "schema_version",
        "generation",
        "evolution_seed",
        "source_population_sha256",
        "source_score_file_sha256",
        "parent_selection",
        "reproduction_summary",
        "evaluated_archive",
        "history_genome_sha256s",
        "genomes",
        "artifact_sha256",
    }
    _exact_keys(population, expected_keys, "population")
    for key, expected in common_artifact_fields(catalog_hashes).items():
        if population.get(key) != expected:
            raise EvolutionError(f"population changes or mismatches frozen field {key}")
    generation = population.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or not 0 <= generation <= FINAL_GENERATION:
        raise EvolutionError("population generation is invalid")
    if population["evolution_seed"] != DEFAULT_SEED:
        raise EvolutionError("population changes the frozen evolution PRNG seed")
    genomes = population.get("genomes")
    if not isinstance(genomes, list) or len(genomes) != POPULATION_SIZE:
        raise EvolutionError("population must contain six genomes")
    for genome in genomes:
        validate_genome(genome, catalog)
        if genome["lineage"]["generation"] != generation:
            raise EvolutionError("genome lineage generation does not match population")
    if len({genome["genome_sha256"] for genome in genomes}) != POPULATION_SIZE:
        raise EvolutionError("population genomes must be distinct")
    history = population.get("history_genome_sha256s")
    if not isinstance(history, list) or history != sorted(set(history)):
        raise EvolutionError("history_genome_sha256s must be sorted and unique")
    archive = population.get("evaluated_archive")
    if not isinstance(archive, list):
        raise EvolutionError("evaluated_archive must be an array")
    archive_ids: set[str] = set()
    for item in archive:
        _exact_keys(
            item,
            {"genome", "source_generation", "source_population_sha256", "score_file_sha256", "fitness"},
            "evaluated archive item",
        )
        genome = validate_genome(item["genome"], catalog)
        if genome["genome_id"] in archive_ids:
            raise EvolutionError("evaluated_archive contains duplicate genomes")
        archive_ids.add(genome["genome_id"])
        if item["source_generation"] != genome["lineage"]["generation"]:
            raise EvolutionError("archive source generation does not match genome lineage")
        _require_sha256(item["source_population_sha256"], "archive source_population_sha256")
        _require_sha256(item["score_file_sha256"], "archive score_file_sha256")
        fitness = validate_fitness(item["fitness"], genome)
        if fitness["case_count"] != TRAINING_CASES:
            raise EvolutionError(f"training fitness must cover exactly {TRAINING_CASES} cases")
        if fitness["completed_calls"] != CALL_BUDGET or fitness["calls"] < CALL_BUDGET:
            raise EvolutionError("archived training fitness violates the 10-call budget")
    if archive_ids & {genome["genome_id"] for genome in genomes}:
        raise EvolutionError("current genomes must not already be in evaluated_archive")
    if generation == 0 and archive:
        raise EvolutionError("Generation 0 cannot contain evaluated ancestors")
    if generation > 0 and len(archive) != generation * POPULATION_SIZE:
        raise EvolutionError("evaluated_archive does not contain all prior generations")
    expected_distribution = {index: POPULATION_SIZE for index in range(generation)}
    if dict(Counter(item["source_generation"] for item in archive)) != expected_distribution:
        raise EvolutionError("evaluated_archive must contain six genomes from every prior generation")
    if archive != sorted(
        archive,
        key=lambda item: (item["source_generation"], item["genome"]["genome_sha256"]),
    ):
        raise EvolutionError("evaluated_archive is not in canonical generation/hash order")

    all_genomes = [item["genome"] for item in archive] + genomes
    all_ids = [genome["genome_id"] for genome in all_genomes]
    all_hashes = [genome["genome_sha256"] for genome in all_genomes]
    if len(set(all_ids)) != len(all_ids) or len(set(all_hashes)) != len(all_hashes):
        raise EvolutionError("search history contains a duplicate genome ID or hash")
    if history != sorted(all_hashes):
        raise EvolutionError("history_genome_sha256s must equal the complete search history")
    parent_lookup = {genome["genome_id"]: genome for genome in all_genomes}
    for genome in all_genomes:
        validate_lineage_against_parents(genome, parent_lookup, catalog)

    parent_selection = population["parent_selection"]
    reproduction = population["reproduction_summary"]
    _exact_keys(reproduction, {"founders", "one_gene_mutations", "crossovers"}, "reproduction_summary")
    if generation == 0:
        if population["source_population_sha256"] is not None or population["source_score_file_sha256"] is not None:
            raise EvolutionError("Generation 0 cannot name a source population or score file")
        if parent_selection != [] or reproduction != {"founders": 6, "one_gene_mutations": 0, "crossovers": 0}:
            raise EvolutionError("Generation 0 reproduction metadata is malformed")
    else:
        source_population_hash = _require_sha256(
            population["source_population_sha256"], "source_population_sha256"
        )
        source_score_hash = _require_sha256(
            population["source_score_file_sha256"], "source_score_file_sha256"
        )
        newest_entries = [item for item in archive if item["source_generation"] == generation - 1]
        if any(
            item["source_population_sha256"] != source_population_hash
            or item["score_file_sha256"] != source_score_hash
            for item in newest_entries
        ):
            raise EvolutionError("latest archive scores do not match the declared source artifacts")
        ranked = sorted(archive, key=fitness_rank_key)
        expected_selection = [
            {
                "rank": index,
                "genome_id": item["genome"]["genome_id"],
                "genome_sha256": item["genome"]["genome_sha256"],
                "source_generation": item["source_generation"],
                "fitness": copy.deepcopy(item["fitness"]),
            }
            for index, item in enumerate(ranked[:2], 1)
        ]
        if parent_selection != expected_selection:
            raise EvolutionError("parent_selection is not the deterministic top two seen so far")
        selected_ids = {item["genome_id"] for item in expected_selection}
        if any(not set(genome["lineage"]["parents"]) <= selected_ids for genome in genomes):
            raise EvolutionError("offspring lineage uses a genome outside the selected top two")
        operations = Counter(genome["lineage"]["operation"] for genome in genomes)
        if operations != {"one_gene_mutation": 4, "crossover": 2}:
            raise EvolutionError("each evolved generation needs four mutations and two crossovers")
        if reproduction != {"founders": 0, "one_gene_mutations": 4, "crossovers": 2}:
            raise EvolutionError("evolved reproduction metadata is malformed")
    return population


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvolutionError(f"{label} must be an integer at least {minimum}")
    return value


def _first(record: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def normalize_fitness(record: Any, genome: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise EvolutionError(f"score for {genome['genome_id']} must be an object")
    case_count = _integer(_first(record, ("case_count", "n")), "case_count", 1)
    exact_cases = _integer(_first(record, ("exact_cases", "exact_correct")), "exact_cases")
    harmful = _integer(record.get("harmful_overrides"), "harmful_overrides")
    term_correct = _integer(record.get("term_correct"), "term_correct")
    format_valid = _integer(_first(record, ("format_valid", "format_valid_cases")), "format_valid")
    calls = _integer(record.get("calls"), "calls")
    completed_calls = _integer(record.get("completed_calls"), "completed_calls")
    if exact_cases > case_count or harmful > case_count or format_valid > case_count:
        raise EvolutionError("case-level score exceeds case_count")
    if harmful > case_count - exact_cases:
        raise EvolutionError("harmful_overrides cannot exceed the number of wrong final cases")
    if term_correct > 5 * format_valid or term_correct < 5 * exact_cases:
        raise EvolutionError("term_correct is inconsistent with exact_cases and case_count")
    if exact_cases > format_valid:
        raise EvolutionError("an exact case must also be format-valid")
    scalar = (6 * exact_cases + term_correct - harmful) / (11 * case_count)
    return {
        "genome_id": genome["genome_id"],
        "genome_sha256": genome["genome_sha256"],
        "case_count": case_count,
        "exact_cases": exact_cases,
        "harmful_overrides": harmful,
        "term_correct": term_correct,
        "format_valid": format_valid,
        "calls": calls,
        "completed_calls": completed_calls,
        "fitness_scalar": scalar,
        "fitness_order": [exact_cases, -harmful, term_correct, format_valid, genome["genome_sha256"]],
    }


def validate_fitness(fitness: Any, genome: dict[str, Any]) -> dict[str, Any]:
    expected = normalize_fitness(fitness, genome)
    for key in (
        "genome_id",
        "genome_sha256",
        "case_count",
        "exact_cases",
        "harmful_overrides",
        "term_correct",
        "format_valid",
        "calls",
        "completed_calls",
    ):
        if fitness.get(key) != expected[key]:
            raise EvolutionError(f"stored fitness field {key} is inconsistent")
    scalar = fitness.get("fitness_scalar")
    if isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not math.isfinite(float(scalar)):
        raise EvolutionError("fitness_scalar must be finite")
    if abs(float(scalar) - expected["fitness_scalar"]) > 1e-12:
        raise EvolutionError("fitness_scalar is inconsistent")
    if fitness.get("fitness_order") != expected["fitness_order"]:
        raise EvolutionError("fitness_order is inconsistent")
    return fitness


def extract_scores(
    score_data: Any,
    genomes: list[dict[str, Any]],
    phase: str,
    expected_answers_sha256: str,
    expected_planned_calls: int,
) -> dict[str, dict[str, Any]]:
    expected = {genome["genome_id"]: genome for genome in genomes}
    if not isinstance(score_data, dict):
        raise EvolutionError("score JSON must be an object")
    declared_phase = score_data.get("phase")
    if declared_phase is not None and declared_phase != phase:
        raise EvolutionError(f"score phase must be {phase!r}")
    if isinstance(score_data.get("methods"), dict):
        if score_data.get("schema_version") != "experiment-03-score-v1":
            raise EvolutionError("methods score input must be an Experiment 03 score.py summary")
        inputs = score_data.get("inputs")
        if not isinstance(inputs, dict) or inputs.get("answers_sha256") != expected_answers_sha256:
            raise EvolutionError(f"score input is not bound to the frozen {phase} answers")
        _require_sha256(inputs.get("predictions_sha256"), "score predictions_sha256")
        source = score_data["methods"]
    elif isinstance(score_data.get("scores"), list):
        if score_data.get("schema_version") != "experiment-03-compact-score-v1":
            raise EvolutionError("compact score input needs schema_version experiment-03-compact-score-v1")
        if declared_phase != phase or score_data.get("answers_sha256") != expected_answers_sha256:
            raise EvolutionError(f"compact score input is not bound to the frozen {phase} split")
        _require_sha256(score_data.get("predictions_sha256"), "compact score predictions_sha256")
        source = {}
        for row in score_data["scores"]:
            if not isinstance(row, dict) or not isinstance(row.get("genome_id"), str):
                raise EvolutionError("each score row needs genome_id")
            if row["genome_id"] in source:
                raise EvolutionError(f"duplicate score for {row['genome_id']}")
            source[row["genome_id"]] = row
    else:
        raise EvolutionError("score JSON needs a methods object or scores array")
    missing = sorted(set(expected) - set(source))
    if missing:
        raise EvolutionError(f"score JSON is missing genomes: {missing}")
    result = {
        genome_id_value: normalize_fitness(source[genome_id_value], genome)
        for genome_id_value, genome in expected.items()
    }
    case_counts = {record["case_count"] for record in result.values()}
    if len(case_counts) != 1:
        raise EvolutionError("all compared genomes must use the same case_count")
    for genome_id_value, record in result.items():
        if record["completed_calls"] != expected_planned_calls:
            raise EvolutionError(
                f"{genome_id_value} has {record['completed_calls']} planned call identities; "
                f"expected {expected_planned_calls}"
            )
        if record["calls"] < record["completed_calls"]:
            raise EvolutionError(f"{genome_id_value} reports fewer attempts than completed call identities")
    return result


def fitness_rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    fitness = item["fitness"]
    return (
        -fitness["exact_cases"],
        fitness["harmful_overrides"],
        -fitness["term_correct"],
        -fitness["format_valid"],
        -int(item["genome"]["genome_sha256"], 16),
    )


def make_archive_entries(
    population: dict[str, Any], scores: dict[str, dict[str, Any]], score_file_hash: str
) -> list[dict[str, Any]]:
    return [
        {
            "genome": copy.deepcopy(genome),
            "source_generation": population["generation"],
            "source_population_sha256": population["artifact_sha256"],
            "score_file_sha256": score_file_hash,
            "fitness": copy.deepcopy(scores[genome["genome_id"]]),
        }
        for genome in population["genomes"]
    ]


def init_population(catalog: dict[str, Any], catalog_hashes: dict[str, str]) -> dict[str, Any]:
    genomes: list[dict[str, Any]] = []
    for founder in catalog["founders"]:
        lineage = {
            "generation": 0,
            "operation": "founder",
            "parents": [],
            "founding_species": [founder["species"]],
            "founder_id": founder["founder_id"],
            "mutation": None,
            "crossover_sources": None,
        }
        genomes.append(make_genome(founder["genes"], lineage, catalog))
    _seeded_rng(DEFAULT_SEED, "generation-00-order").shuffle(genomes)
    body = {
        "schema_version": POPULATION_SCHEMA,
        **common_artifact_fields(catalog_hashes),
        "generation": 0,
        "evolution_seed": DEFAULT_SEED,
        "source_population_sha256": None,
        "source_score_file_sha256": None,
        "parent_selection": [],
        "reproduction_summary": {"founders": 6, "one_gene_mutations": 0, "crossovers": 0},
        "evaluated_archive": [],
        "history_genome_sha256s": sorted(genome["genome_sha256"] for genome in genomes),
        "genomes": genomes,
    }
    return seal_artifact(body)


def _founding_species(genome: dict[str, Any]) -> list[str]:
    return list(genome["lineage"]["founding_species"])


def mutate_genome(parent: dict[str, Any], generation: int, rng: random.Random, catalog: dict[str, Any]) -> dict[str, Any]:
    genes = copy.deepcopy(parent["genes"])
    loci = ["topology_id", *(f"role_lenses.{index}" for index in range(WORKER_LENS_SLOTS)), "final_policy_id"]
    locus = rng.choice(loci)
    if locus == "topology_id":
        old = genes["topology_id"]
        choices = sorted(set(catalog["topologies"]) - {old})
        new = rng.choice(choices)
        genes["topology_id"] = new
    elif locus == "final_policy_id":
        old = genes["final_policy_id"]
        choices = sorted(set(catalog["final_policy_ids"]) - {old})
        new = rng.choice(choices)
        genes["final_policy_id"] = new
    else:
        index = int(locus.split(".")[1])
        old = genes["role_lenses"][index]
        choices = sorted(set(catalog["lens_ids"]) - {old})
        new = rng.choice(choices)
        genes["role_lenses"][index] = new
    lineage = {
        "generation": generation,
        "operation": "one_gene_mutation",
        "parents": [parent["genome_id"]],
        "founding_species": _founding_species(parent),
        "founder_id": None,
        "mutation": {"locus": locus, "from": old, "to": new},
        "crossover_sources": None,
    }
    return make_genome(genes, lineage, catalog)


def crossover_genomes(
    first: dict[str, Any], second: dict[str, Any], generation: int, rng: random.Random, catalog: dict[str, Any]
) -> dict[str, Any]:
    parents = [first, second]
    parent_ids = [first["genome_id"], second["genome_id"]]
    topology_parent = rng.randrange(2)
    policy_parent = rng.randrange(2)
    offsets = [rng.randrange(WORKER_LENS_SLOTS), rng.randrange(WORKER_LENS_SLOTS)]
    if offsets == [0, 0]:
        offsets[rng.randrange(2)] = 1
    source_choices = [rng.randrange(2) for _ in range(WORKER_LENS_SLOTS)]
    if len(set(source_choices)) == 1:
        source_choices[rng.randrange(WORKER_LENS_SLOTS)] = 1 - source_choices[0]
    role_lenses: list[str] = []
    lens_sources: list[dict[str, str]] = []
    for target_index, source_parent in enumerate(source_choices):
        source_index = (target_index + offsets[source_parent]) % WORKER_LENS_SLOTS
        role_lenses.append(parents[source_parent]["genes"]["role_lenses"][source_index])
        lens_sources.append(
            {"parent": parent_ids[source_parent], "source_slot": f"W{source_index + 1:02d}"}
        )
    genes = {
        "topology_id": parents[topology_parent]["genes"]["topology_id"],
        "role_lenses": role_lenses,
        "final_policy_id": parents[policy_parent]["genes"]["final_policy_id"],
    }
    lineage = {
        "generation": generation,
        "operation": "crossover",
        "parents": sorted(parent_ids),
        "founding_species": sorted(set(_founding_species(first)) | set(_founding_species(second))),
        "founder_id": None,
        "mutation": None,
        "crossover_sources": {
            "topology_id": parent_ids[topology_parent],
            "role_lenses": lens_sources,
            "final_policy_id": parent_ids[policy_parent],
        },
    }
    return make_genome(genes, lineage, catalog)


def _unique_child(factory: Any, used: set[str], limit: int = 10_000) -> dict[str, Any]:
    for _ in range(limit):
        child = factory()
        if child["genome_sha256"] not in used:
            used.add(child["genome_sha256"])
            return child
    raise EvolutionError("could not generate a distinct offspring under the frozen grammar")


def next_generation(
    population: dict[str, Any], score_data: Any, score_file_hash: str, catalog: dict[str, Any],
    catalog_hashes: dict[str, str]
) -> dict[str, Any]:
    population = validate_population(population, catalog, catalog_hashes)
    generation = population["generation"]
    if generation >= FINAL_GENERATION:
        raise EvolutionError("Generation 2 is final; select validation finalists instead of creating Generation 3")
    current_scores = extract_scores(
        score_data,
        population["genomes"],
        "training",
        catalog_hashes["training_answers_sha256"],
        CALL_BUDGET,
    )
    if {score["case_count"] for score in current_scores.values()} != {TRAINING_CASES}:
        raise EvolutionError(f"each training score must cover exactly {TRAINING_CASES} cases")
    current_entries = make_archive_entries(population, current_scores, score_file_hash)
    all_entries = [copy.deepcopy(item) for item in population["evaluated_archive"]] + current_entries
    if len({item["genome"]["genome_id"] for item in all_entries}) != len(all_entries):
        raise EvolutionError("evaluated genome archive contains duplicates")
    ranked = sorted(all_entries, key=fitness_rank_key)
    parents = [ranked[0]["genome"], ranked[1]["genome"]]
    next_index = generation + 1
    rng = _seeded_rng(population["evolution_seed"], f"generation-{next_index:02d}")
    used = set(population["history_genome_sha256s"])
    children: list[dict[str, Any]] = []
    for index in range(4):
        parent = parents[index % 2]
        children.append(
            _unique_child(lambda parent=parent: mutate_genome(parent, next_index, rng, catalog), used)
        )
    for index in range(2):
        first, second = (parents[0], parents[1]) if index == 0 else (parents[1], parents[0])
        children.append(
            _unique_child(lambda first=first, second=second: crossover_genomes(first, second, next_index, rng, catalog), used)
        )
    if Counter(child["lineage"]["operation"] for child in children) != {
        "one_gene_mutation": 4,
        "crossover": 2,
    }:
        raise AssertionError("frozen reproduction counts changed")
    parent_selection = [
        {
            "rank": index,
            "genome_id": item["genome"]["genome_id"],
            "genome_sha256": item["genome"]["genome_sha256"],
            "source_generation": item["source_generation"],
            "fitness": copy.deepcopy(item["fitness"]),
        }
        for index, item in enumerate(ranked[:2], 1)
    ]
    body = {
        "schema_version": POPULATION_SCHEMA,
        **common_artifact_fields(catalog_hashes),
        "generation": next_index,
        "evolution_seed": population["evolution_seed"],
        "source_population_sha256": population["artifact_sha256"],
        "source_score_file_sha256": score_file_hash,
        "parent_selection": parent_selection,
        "reproduction_summary": {"founders": 0, "one_gene_mutations": 4, "crossovers": 2},
        "evaluated_archive": sorted(
            all_entries,
            key=lambda item: (item["source_generation"], item["genome"]["genome_sha256"]),
        ),
        "history_genome_sha256s": sorted(used),
        "genomes": children,
    }
    return seal_artifact(body)


def select_validation(
    population: dict[str, Any], score_data: Any, score_file_hash: str, catalog: dict[str, Any],
    catalog_hashes: dict[str, str]
) -> dict[str, Any]:
    population = validate_population(population, catalog, catalog_hashes)
    if population["generation"] != FINAL_GENERATION:
        raise EvolutionError("validation finalists may be selected only after scoring Generation 2")
    current_scores = extract_scores(
        score_data,
        population["genomes"],
        "training",
        catalog_hashes["training_answers_sha256"],
        CALL_BUDGET,
    )
    if {score["case_count"] for score in current_scores.values()} != {TRAINING_CASES}:
        raise EvolutionError(f"each training score must cover exactly {TRAINING_CASES} cases")
    all_entries = [copy.deepcopy(item) for item in population["evaluated_archive"]]
    all_entries.extend(make_archive_entries(population, current_scores, score_file_hash))
    if len(all_entries) != POPULATION_SIZE * GENERATION_COUNT:
        raise EvolutionError("validation selection requires all 18 scored genomes")
    if len({item["genome"]["genome_id"] for item in all_entries}) != len(all_entries):
        raise EvolutionError("the 18-genome search history is not distinct")
    all_entries = sorted(
        all_entries,
        key=lambda item: (item["source_generation"], item["genome"]["genome_sha256"]),
    )
    ranked = sorted(all_entries, key=fitness_rank_key)
    candidates = [
        {
            "training_rank": index,
            "genome": copy.deepcopy(item["genome"]),
            "training_fitness": copy.deepcopy(item["fitness"]),
            "source_generation": item["source_generation"],
        }
        for index, item in enumerate(ranked[:3], 1)
    ]
    founders = [item for item in ranked if item["source_generation"] == 0]
    best_founder = {
        "genome": copy.deepcopy(founders[0]["genome"]),
        "training_fitness": copy.deepcopy(founders[0]["fitness"]),
        "training_rank_overall": ranked.index(founders[0]) + 1,
    }
    body = {
        "schema_version": VALIDATION_SCHEMA,
        **common_artifact_fields(catalog_hashes),
        "evolution_seed": population["evolution_seed"],
        "source_population_sha256": population["artifact_sha256"],
        "source_score_file_sha256": score_file_hash,
        "evaluated_genome_count": len(all_entries),
        "selection_count": 3,
        "selection_rule": list(SELECTION_RULE),
        "evaluated_archive": all_entries,
        "candidates": candidates,
        "best_founder": best_founder,
    }
    return seal_artifact(body)


def validate_selection(value: Any, catalog: dict[str, Any], catalog_hashes: dict[str, str]) -> dict[str, Any]:
    selection = verify_artifact(value, VALIDATION_SCHEMA)
    expected_keys = set(common_artifact_fields(catalog_hashes)) | {
        "schema_version",
        "evolution_seed",
        "source_population_sha256",
        "source_score_file_sha256",
        "evaluated_genome_count",
        "selection_count",
        "selection_rule",
        "evaluated_archive",
        "candidates",
        "best_founder",
        "artifact_sha256",
    }
    _exact_keys(selection, expected_keys, "validation selection")
    for key, expected in common_artifact_fields(catalog_hashes).items():
        if selection.get(key) != expected:
            raise EvolutionError(f"validation selection mismatches frozen field {key}")
    if selection["evolution_seed"] != DEFAULT_SEED:
        raise EvolutionError("validation selection changes the frozen PRNG seed")
    source_population_hash = _require_sha256(
        selection["source_population_sha256"], "validation source_population_sha256"
    )
    source_score_hash = _require_sha256(
        selection["source_score_file_sha256"], "validation source_score_file_sha256"
    )
    if selection.get("evaluated_genome_count") != 18 or selection.get("selection_count") != 3:
        raise EvolutionError("validation selection must contain three finalists from 18 genomes")
    if selection["selection_rule"] != list(SELECTION_RULE):
        raise EvolutionError("validation selection changes the frozen fitness order")

    archive = selection["evaluated_archive"]
    if not isinstance(archive, list) or len(archive) != POPULATION_SIZE * GENERATION_COUNT:
        raise EvolutionError("validation archive must contain all 18 evaluated genomes")
    if archive != sorted(
        archive,
        key=lambda item: (item["source_generation"], item["genome"]["genome_sha256"]),
    ):
        raise EvolutionError("validation archive is not in canonical generation/hash order")
    if dict(Counter(item.get("source_generation") for item in archive)) != {
        0: POPULATION_SIZE,
        1: POPULATION_SIZE,
        2: POPULATION_SIZE,
    }:
        raise EvolutionError("validation archive must contain six genomes per generation")
    genomes: list[dict[str, Any]] = []
    for item in archive:
        _exact_keys(
            item,
            {"genome", "source_generation", "source_population_sha256", "score_file_sha256", "fitness"},
            "validation archive item",
        )
        genome = validate_genome(item["genome"], catalog)
        if genome["lineage"]["generation"] != item["source_generation"]:
            raise EvolutionError("validation archive generation differs from genome lineage")
        _require_sha256(item["source_population_sha256"], "validation archive population hash")
        _require_sha256(item["score_file_sha256"], "validation archive score hash")
        fitness = validate_fitness(item["fitness"], genome)
        if (
            fitness["case_count"] != TRAINING_CASES
            or fitness["completed_calls"] != CALL_BUDGET
            or fitness["calls"] < CALL_BUDGET
        ):
            raise EvolutionError("validation archive contains non-comparable training fitness")
        genomes.append(genome)
    if len({genome["genome_id"] for genome in genomes}) != 18 or len(
        {genome["genome_sha256"] for genome in genomes}
    ) != 18:
        raise EvolutionError("validation archive genomes must be distinct")
    parent_lookup = {genome["genome_id"]: genome for genome in genomes}
    for genome in genomes:
        validate_lineage_against_parents(genome, parent_lookup, catalog)
    newest = [item for item in archive if item["source_generation"] == FINAL_GENERATION]
    if any(
        item["source_population_sha256"] != source_population_hash
        or item["score_file_sha256"] != source_score_hash
        for item in newest
    ):
        raise EvolutionError("Generation 2 archive entries do not match validation selection sources")

    ranked = sorted(archive, key=fitness_rank_key)
    expected_candidates = [
        {
            "training_rank": index,
            "genome": copy.deepcopy(item["genome"]),
            "training_fitness": copy.deepcopy(item["fitness"]),
            "source_generation": item["source_generation"],
        }
        for index, item in enumerate(ranked[:3], 1)
    ]
    if selection["candidates"] != expected_candidates:
        raise EvolutionError("validation candidates are not the deterministic top three")
    founders = [item for item in ranked if item["source_generation"] == 0]
    expected_founder = {
        "genome": copy.deepcopy(founders[0]["genome"]),
        "training_fitness": copy.deepcopy(founders[0]["fitness"]),
        "training_rank_overall": ranked.index(founders[0]) + 1,
    }
    if selection["best_founder"] != expected_founder:
        raise EvolutionError("best_founder is not the highest-ranked Generation 0 genome")
    return selection


def freeze_champion(
    selection: dict[str, Any], score_data: Any, score_file_hash: str, catalog: dict[str, Any],
    catalog_hashes: dict[str, str]
) -> dict[str, Any]:
    selection = validate_selection(selection, catalog, catalog_hashes)
    genomes = [candidate["genome"] for candidate in selection["candidates"]]
    scores = extract_scores(
        score_data,
        genomes,
        "validation",
        catalog_hashes["validation_answers_sha256"],
        2 * CALL_BUDGET,
    )
    if {score["case_count"] for score in scores.values()} != {VALIDATION_CASES}:
        raise EvolutionError(f"each validation score must cover exactly {VALIDATION_CASES} cases")
    candidates = [
        {
            "genome": copy.deepcopy(genome),
            "fitness": copy.deepcopy(scores[genome["genome_id"]]),
        }
        for genome in genomes
    ]
    ranked = sorted(candidates, key=fitness_rank_key)
    champion = ranked[0]
    body = {
        "schema_version": CHAMPION_SCHEMA,
        **common_artifact_fields(catalog_hashes),
        "evolution_seed": selection["evolution_seed"],
        "source_validation_selection_sha256": selection["artifact_sha256"],
        "source_validation_score_file_sha256": score_file_hash,
        "validation_case_count": champion["fitness"]["case_count"],
        "champion": {
            "validation_rank": 1,
            "genome": copy.deepcopy(champion["genome"]),
            "validation_fitness": copy.deepcopy(champion["fitness"]),
        },
        "validation_ranking": [
            {
                "rank": index,
                "genome_id": item["genome"]["genome_id"],
                "genome_sha256": item["genome"]["genome_sha256"],
                "validation_fitness": copy.deepcopy(item["fitness"]),
            }
            for index, item in enumerate(ranked, 1)
        ],
        "best_founder": copy.deepcopy(selection["best_founder"]),
        "freeze_status": "champion_frozen_before_final_answers",
    }
    return seal_artifact(body)


def _fake_summary(
    genomes: list[dict[str, Any]],
    generation: int,
    case_count: int,
    answers_sha256: str,
    planned_calls: int,
) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for index, genome in enumerate(sorted(genomes, key=lambda item: item["genome_sha256"])):
        exact = max(0, case_count - ((index + generation) % 5))
        wrong = case_count - exact
        methods[genome["genome_id"]] = {
            "case_count": case_count,
            "exact_cases": exact,
            "harmful_overrides": min(wrong, (index + generation) % 2),
            "term_correct": min(5 * case_count, 5 * exact + ((index * 3 + generation) % (5 * (case_count - exact) + 1))),
            "format_valid": case_count,
            "calls": planned_calls,
            "completed_calls": planned_calls,
        }
    predictions_hash = sha256_bytes(canonical_bytes({"generation": generation, "methods": sorted(methods)}))
    return {
        "schema_version": "experiment-03-score-v1",
        "inputs": {
            "answers_sha256": answers_sha256,
            "predictions_sha256": predictions_hash,
            "completed_jobs": len(genomes) * planned_calls,
        },
        "methods": methods,
    }


def self_test() -> dict[str, Any]:
    catalog, hashes = load_catalog()
    generation0 = init_population(catalog, hashes)
    validate_population(generation0, catalog, hashes)
    assert len({genome["genome_sha256"] for genome in generation0["genomes"]}) == 6
    assert {species for genome in generation0["genomes"] for species in genome["lineage"]["founding_species"]} == EXPECTED_SPECIES

    score0 = _fake_summary(generation0["genomes"], 0, 12, hashes["training_answers_sha256"], 10)
    generation1 = next_generation(generation0, score0, sha256_bytes(canonical_bytes(score0)), catalog, hashes)
    validate_population(generation1, catalog, hashes)
    assert Counter(genome["lineage"]["operation"] for genome in generation1["genomes"]) == {
        "one_gene_mutation": 4,
        "crossover": 2,
    }
    assert all(
        sum(
            [child["genes"]["topology_id"] != parent["genes"]["topology_id"]]
            + [a != b for a, b in zip(child["genes"]["role_lenses"], parent["genes"]["role_lenses"])]
            + [child["genes"]["final_policy_id"] != parent["genes"]["final_policy_id"]]
        ) == 1
        for child in generation1["genomes"]
        if child["lineage"]["operation"] == "one_gene_mutation"
        for parent in [next(
            item["genome"] for item in generation1["evaluated_archive"]
            if item["genome"]["genome_id"] == child["lineage"]["parents"][0]
        )]
    )
    duplicate = next_generation(generation0, score0, sha256_bytes(canonical_bytes(score0)), catalog, hashes)
    assert canonical_bytes(generation1) == canonical_bytes(duplicate)

    score1 = _fake_summary(generation1["genomes"], 1, 12, hashes["training_answers_sha256"], 10)
    generation2 = next_generation(generation1, score1, sha256_bytes(canonical_bytes(score1)), catalog, hashes)
    validate_population(generation2, catalog, hashes)
    assert len(generation2["evaluated_archive"]) == 12
    assert len(generation2["history_genome_sha256s"]) == 18

    score2 = _fake_summary(generation2["genomes"], 2, 12, hashes["training_answers_sha256"], 10)
    selection = select_validation(generation2, score2, sha256_bytes(canonical_bytes(score2)), catalog, hashes)
    validate_selection(selection, catalog, hashes)
    assert len(selection["candidates"]) == 3
    validation_score = _fake_summary(
        [item["genome"] for item in selection["candidates"]],
        0,
        24,
        hashes["validation_answers_sha256"],
        20,
    )
    champion = freeze_champion(
        selection,
        validation_score,
        sha256_bytes(canonical_bytes(validation_score)),
        catalog,
        hashes,
    )
    verify_artifact(champion, CHAMPION_SCHEMA)
    assert champion["validation_case_count"] == 24
    assert champion["champion"]["genome"]["genome_id"] in {
        item["genome"]["genome_id"] for item in selection["candidates"]
    }

    bad_score = copy.deepcopy(score2)
    bad_score["methods"].pop(next(iter(bad_score["methods"])))
    try:
        select_validation(generation2, bad_score, "bad", catalog, hashes)
    except EvolutionError:
        pass
    else:
        raise AssertionError("missing genome score was accepted")
    return {
        "ok": True,
        "tests": 24,
        "generation_0_genomes": 6,
        "generation_1_mutations": 4,
        "generation_1_crossovers": 2,
        "distinct_genomes_after_generation_2": 18,
        "validation_finalists": 3,
        "call_budget_per_genome": 10,
        "public_condition_label": PUBLIC_LABEL,
        "provider_reasoning_effort": PROVIDER_EFFORT,
    }


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--lenses", type=Path, default=DEFAULT_LENSES)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create six distinct Generation 0 founders")
    _add_output_options(init_parser)

    next_parser = subparsers.add_parser("next-generation", help="score one generation and create six offspring")
    next_parser.add_argument("--population", type=Path, required=True)
    next_parser.add_argument("--scores", type=Path, required=True)
    _add_output_options(next_parser)

    validation_parser = subparsers.add_parser("select-validation", help="select the top three of all 18 genomes")
    validation_parser.add_argument("--population", type=Path, required=True, help="scored Generation 2 population")
    validation_parser.add_argument("--scores", type=Path, required=True, help="Generation 2 score JSON")
    _add_output_options(validation_parser)

    champion_parser = subparsers.add_parser("freeze-champion", help="freeze one champion from validation scores")
    champion_parser.add_argument("--selection", type=Path, required=True)
    champion_parser.add_argument("--scores", type=Path, required=True)
    _add_output_options(champion_parser)

    subparsers.add_parser("self-test", help="run deterministic standard-library tests")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "self-test":
            print(json.dumps(self_test(), indent=2, sort_keys=True))
            return 0
        catalog, hashes = load_catalog(args.catalog.resolve(), args.lenses.resolve())
        if args.command == "init":
            artifact = init_population(catalog, hashes)
        elif args.command == "next-generation":
            population, _ = load_json(args.population)
            score_data, score_hash = load_json(args.scores)
            artifact = next_generation(population, score_data, score_hash, catalog, hashes)
        elif args.command == "select-validation":
            population, _ = load_json(args.population)
            score_data, score_hash = load_json(args.scores)
            artifact = select_validation(population, score_data, score_hash, catalog, hashes)
        elif args.command == "freeze-champion":
            selection, _ = load_json(args.selection)
            score_data, score_hash = load_json(args.scores)
            artifact = freeze_champion(selection, score_data, score_hash, catalog, hashes)
        else:
            raise AssertionError("unreachable")
        atomic_write_json(args.output.resolve(), artifact, args.overwrite)
        print(json.dumps({
            "artifact_sha256": artifact["artifact_sha256"],
            "output": str(args.output.resolve()),
            "schema_version": artifact["schema_version"],
        }, indent=2, sort_keys=True))
        return 0
    except (EvolutionError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
