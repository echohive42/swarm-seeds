#!/usr/bin/env python3
"""Generate the deterministic RuleWeave-5 benchmark using Python built-ins only."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


BENCHMARK_ID = "ruleweave-5-v1"
ROOT_SEED = "swarm-seeds-02-ruleweave-5-2026-07-13"
FAMILIES = (
    "POLY",
    "PDELTA",
    "AFFINE",
    "LIN2",
    "LAGPOLY",
    "INTERLEAVE",
    "GROWBLOCK",
    "MODAFFINE",
)
TIERS = ("hard", "very-hard", "stress")
VISIBLE_BY_TIER = {"hard": 12, "very-hard": 13, "stress": 14}
TIER_NUMBER = {"hard": 1, "very-hard": 2, "stress": 3}
COEFF_LIMIT = {"hard": 5, "very-hard": 7, "stress": 9}
SEED_LIMIT = {"hard": 12, "very-hard": 20, "stress": 30}
MULTIPLIERS = (-3, -2, -1, 2, 3)
LIN_COEFFICIENTS = (-2, -1, 1, 2)
PRIMES = tuple(
    p
    for p in range(19, 128)
    if all(p % d for d in range(2, int(math.isqrt(p)) + 1))
)
STRUCTURAL_KEYS = {"d", "p", "L", "k", "l0", "dv", "dd"}
VISIBLE_MAX = 10**9
TARGET_MAX = 10**12
INTERMEDIATE_MAX = 10**15

SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
BENCHMARK_DIR = EXPERIMENT_DIR / "benchmark"
PUBLIC_DIR = BENCHMARK_DIR / "public"
HIDDEN_DIR = BENCHMARK_DIR / "hidden"


class SplitMix64:
    """Small deterministic PRNG with stable behavior across Python versions."""

    MASK = (1 << 64) - 1

    def __init__(self, key: str):
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        self.state = int.from_bytes(digest[:8], "big")

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return (z ^ (z >> 31)) & self.MASK

    def randint(self, low: int, high: int) -> int:
        if high < low:
            raise ValueError("invalid integer range")
        return low + self.next_u64() % (high - low + 1)

    def choice(self, values: Iterable[Any]) -> Any:
        sequence = tuple(values)
        if not sequence:
            raise ValueError("cannot choose from an empty sequence")
        return sequence[self.next_u64() % len(sequence)]

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            other = self.next_u64() % (index + 1)
            values[index], values[other] = values[other], values[index]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    else:
        text = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def int_string(value: int) -> str:
    return str(value)


def encode_program(value: Any, key: str | None = None) -> Any:
    """Store mathematical integers as decimal strings and structural sizes as JSON numbers."""
    if isinstance(value, dict):
        return {name: encode_program(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [encode_program(item, key) for item in value]
    if isinstance(value, int):
        return value if key in STRUCTURAL_KEYS else str(value)
    return value


def decode_program(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: decode_program(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [decode_program(item, key) for item in value]
    if isinstance(value, str) and (value.isdigit() or (value.startswith("-") and value[1:].isdigit())):
        return int(value)
    return value


def canonical_program(program: dict[str, Any]) -> str:
    return json.dumps(encode_program(program), sort_keys=True, separators=(",", ":"))


def binomial_polynomial(coefficients: list[int], x: int, mark) -> int:
    total = 0
    for degree, coefficient in enumerate(coefficients):
        product = coefficient * math.comb(x, degree)
        mark(product)
        total += product
        mark(total)
    return total


def evaluate(program: dict[str, Any], count: int, *, with_intermediate: bool = False):
    maximum = 0

    def mark(value: int) -> None:
        nonlocal maximum
        maximum = max(maximum, abs(value))

    family = program["family"]
    output: list[int] = []

    if family == "POLY":
        output = [binomial_polynomial(program["coefficients"], n - 1, mark) for n in range(1, count + 1)]

    elif family == "PDELTA":
        output = [program["seed"]]
        mark(output[0])
        for n in range(2, count + 1):
            t = n - 2
            phase = t % program["p"]
            cycle = t // program["p"]
            delta = binomial_polynomial(program["coefficients"][phase], cycle, mark)
            value = output[-1] + delta
            mark(value)
            output.append(value)

    elif family == "AFFINE":
        output = [program["seed"]]
        mark(output[0])
        for n in range(2, count + 1):
            phase = (n - 2) % program["p"]
            raw = program["multipliers"][phase] * output[-1]
            mark(raw)
            value = raw + program["biases"][phase]
            mark(value)
            output.append(value)

    elif family == "LIN2":
        output = [program["seeds"][0], program["seeds"][1]]
        for value in output:
            mark(value)
        for n in range(3, count + 1):
            phase = (n - 3) % program["p"]
            left = program["u"] * output[-1]
            right = program["v"] * output[-2]
            mark(left)
            mark(right)
            value = left + right + program["biases"][phase]
            mark(value)
            output.append(value)

    elif family == "LAGPOLY":
        output = list(program["seeds"])
        for value in output:
            mark(value)
        for n in range(program["L"] + 1, count + 1):
            phase = (n - 1) % program["L"]
            cycle = (n - 1) // program["L"] - 1
            step = binomial_polynomial(program["coefficients"][phase], cycle, mark)
            value = output[n - program["L"] - 1] + step
            mark(value)
            output.append(value)

    elif family == "INTERLEAVE":
        atom_cache: dict[int, list[int]] = {}
        required = (count + program["k"] - 1) // program["k"]
        for index, atom in enumerate(program["atoms"]):
            if atom["kind"] == "APOLY":
                atom_cache[index] = [
                    binomial_polynomial(atom["coefficients"], j - 1, mark)
                    for j in range(1, required + 1)
                ]
            else:
                values = [atom["seed"]]
                mark(values[0])
                while len(values) < required:
                    raw = atom["m"] * values[-1]
                    mark(raw)
                    value = raw + atom["b"]
                    mark(value)
                    values.append(value)
                atom_cache[index] = values
        for n in range(1, count + 1):
            phase = (n - 1) % program["k"]
            local_index = (n - 1) // program["k"]
            output.append(atom_cache[phase][local_index])

    elif family == "GROWBLOCK":
        block = 0
        while len(output) < count:
            length = program["l0"] + block
            start = binomial_polynomial(program["V"], block, mark)
            step = binomial_polynomial(program["D"], block, mark)
            for offset in range(length):
                raw = offset * step
                mark(raw)
                value = start + raw
                mark(value)
                output.append(value)
                if len(output) == count:
                    break
            block += 1

    elif family == "MODAFFINE":
        output = [program["seed"]]
        mark(output[0])
        for n in range(2, count + 1):
            phase = (n - 2) % program["p"]
            raw = program["multipliers"][phase] * output[-1] + program["biases"][phase]
            mark(raw)
            value = raw % program["M"]
            mark(value)
            output.append(value)

    else:
        raise ValueError(f"unknown family: {family}")

    if len(output) != count:
        raise AssertionError(f"{family} generated {len(output)} terms, expected {count}")
    return (output, maximum) if with_intermediate else output


def coefficient_vector(rng: SplitMix64, length: int, limit: int, *, leading: bool = True) -> list[int]:
    values = [rng.randint(-limit, limit) for _ in range(length)]
    if leading and values[-1] == 0:
        values[-1] = rng.choice(tuple(value for value in range(-limit, limit + 1) if value))
    return values


def generate_program(family: str, tier: str, rng: SplitMix64) -> dict[str, Any]:
    level = TIER_NUMBER[tier]
    coefficient_limit = COEFF_LIMIT[tier]
    seed_limit = SEED_LIMIT[tier]

    if family == "POLY":
        degree = {1: 3, 2: 4, 3: 5}[level]
        coefficients = coefficient_vector(rng, degree + 1, coefficient_limit)
        coefficients[0] = rng.randint(-seed_limit, seed_limit)
        return {"family": family, "d": degree, "coefficients": coefficients}

    if family == "PDELTA":
        if level == 1:
            period, degree = 2, 0
        elif level == 2:
            period, degree = rng.choice((2, 3)), 1
        else:
            period, degree = rng.choice((3, 4)), rng.choice((1, 2))
        vectors = [coefficient_vector(rng, degree + 1, coefficient_limit) for _ in range(period)]
        if len({tuple(vector) for vector in vectors}) == 1:
            vectors[-1][0] += 1 if vectors[-1][0] < coefficient_limit else -1
        return {
            "family": family,
            "p": period,
            "d": degree,
            "seed": rng.randint(-seed_limit, seed_limit),
            "coefficients": vectors,
        }

    if family == "AFFINE":
        period = level
        multipliers = [rng.choice(MULTIPLIERS) for _ in range(period)]
        biases = [rng.randint(-coefficient_limit, coefficient_limit) for _ in range(period)]
        if period > 1 and len(set(zip(multipliers, biases))) == 1:
            biases[-1] += 1 if biases[-1] < coefficient_limit else -1
        return {
            "family": family,
            "p": period,
            "seed": rng.randint(-seed_limit, seed_limit),
            "multipliers": multipliers,
            "biases": biases,
        }

    if family == "LIN2":
        period = level
        biases = [rng.randint(-coefficient_limit, coefficient_limit) for _ in range(period)]
        if period > 1 and len(set(biases)) == 1:
            biases[-1] += 1 if biases[-1] < coefficient_limit else -1
        return {
            "family": family,
            "p": period,
            "seeds": [rng.randint(-seed_limit, seed_limit), rng.randint(-seed_limit, seed_limit)],
            "u": rng.choice(LIN_COEFFICIENTS),
            "v": rng.choice(LIN_COEFFICIENTS),
            "biases": biases,
        }

    if family == "LAGPOLY":
        if level == 1:
            lag, degree = 2, 0
        elif level == 2:
            lag, degree = rng.choice((2, 3)), 1
        else:
            lag, degree = rng.choice(((3, 2), (4, 1)))
        vectors = [coefficient_vector(rng, degree + 1, coefficient_limit) for _ in range(lag)]
        if len({tuple(vector) for vector in vectors}) == 1:
            vectors[-1][0] += 1 if vectors[-1][0] < coefficient_limit else -1
        return {
            "family": family,
            "L": lag,
            "d": degree,
            "seeds": [rng.randint(-seed_limit, seed_limit) for _ in range(lag)],
            "coefficients": vectors,
        }

    if family == "INTERLEAVE":
        width = 2 if level == 1 else 3
        if level == 1:
            shapes = (("APOLY", 2), ("AAFFINE", None))
        elif level == 2:
            shapes = (("APOLY", 2), ("AAFFINE", None), ("APOLY", 1))
        else:
            shapes = (("APOLY", 3), ("AAFFINE", None), ("APOLY", 2))
        shapes = list(shapes)
        rng.shuffle(shapes)
        atoms = []
        for kind, degree in shapes[:width]:
            if kind == "APOLY":
                coefficients = coefficient_vector(rng, int(degree) + 1, coefficient_limit)
                coefficients[0] = rng.randint(-seed_limit, seed_limit)
                atoms.append({"kind": kind, "d": degree, "coefficients": coefficients})
            else:
                atoms.append(
                    {
                        "kind": kind,
                        "seed": rng.randint(-seed_limit, seed_limit),
                        "m": rng.choice((-2, -1, 2)),
                        "b": rng.randint(-coefficient_limit, coefficient_limit),
                    }
                )
        return {"family": family, "k": width, "atoms": atoms}

    if family == "GROWBLOCK":
        degree_v = level
        degree_d = 0 if level == 1 else 1
        vector_v = coefficient_vector(rng, degree_v + 1, coefficient_limit)
        vector_v[0] = rng.randint(-seed_limit, seed_limit)
        vector_d = coefficient_vector(rng, degree_d + 1, coefficient_limit)
        return {
            "family": family,
            "l0": rng.choice((1, 2)),
            "dv": degree_v,
            "dd": degree_d,
            "V": vector_v,
            "D": vector_d,
        }

    if family == "MODAFFINE":
        if level == 1:
            period = 1
            candidates = tuple(prime for prime in PRIMES if 19 <= prime <= 43)
        elif level == 2:
            period = rng.choice((1, 2))
            candidates = tuple(prime for prime in PRIMES if 31 <= prime <= 79)
        else:
            period = 2
            candidates = tuple(prime for prime in PRIMES if 53 <= prime <= 127)
        modulus = rng.choice(candidates)
        multipliers = [rng.randint(2, min(9, modulus - 2)) for _ in range(period)]
        biases = [rng.randint(0, modulus - 1) for _ in range(period)]
        if period > 1 and len(set(zip(multipliers, biases))) == 1:
            biases[-1] = (biases[-1] + 1) % modulus
        return {
            "family": family,
            "p": period,
            "M": modulus,
            "seed": rng.randint(0, modulus - 1),
            "multipliers": multipliers,
            "biases": biases,
        }

    raise ValueError(f"unknown family: {family}")


def binomial_coefficients_from_values(values: list[int], degree: int) -> list[int] | None:
    if len(values) < degree + 1:
        return None
    row = list(values)
    coefficients = []
    for _ in range(degree + 1):
        coefficients.append(row[0])
        row = [row[index + 1] - row[index] for index in range(len(row) - 1)]
    for x, expected in enumerate(values):
        actual = sum(coefficients[d] * math.comb(x, d) for d in range(degree + 1))
        if actual != expected:
            return None
    return coefficients


def allowed_program_shape(program: dict[str, Any]) -> bool:
    family = program["family"]
    if family == "POLY":
        return 2 <= program["d"] <= 5 and program["coefficients"][-1] != 0
    if family == "PDELTA":
        return (program["p"], program["d"]) in {
            (2, 0), (2, 1), (3, 1), (3, 2), (4, 1), (4, 2)
        }
    if family in {"AFFINE", "LIN2"}:
        return 1 <= program["p"] <= 3
    if family == "LAGPOLY":
        return (program["L"], program["d"]) in {(2, 0), (2, 1), (3, 1), (3, 2), (4, 1)}
    if family == "INTERLEAVE":
        return 2 <= program["k"] <= 3
    if family == "GROWBLOCK":
        return program["l0"] in (1, 2) and 1 <= program["dv"] <= 3 and 0 <= program["dd"] <= 1
    if family == "MODAFFINE":
        return program["M"] in PRIMES and 1 <= program["p"] <= 2
    return False


def minimum_tier(program: dict[str, Any]) -> int:
    family = program["family"]
    if family == "POLY":
        return 1 if program["d"] <= 3 else 2 if program["d"] == 4 else 3
    if family == "PDELTA":
        p, degree = program["p"], program["d"]
        if (p, degree) == (2, 0):
            return 1
        if degree == 1 and p <= 3:
            return 2
        return 3
    if family in {"AFFINE", "LIN2"}:
        return program["p"]
    if family == "LAGPOLY":
        if (program["L"], program["d"]) == (2, 0):
            return 1
        if program["d"] == 1 and program["L"] <= 3:
            return 2
        return 3
    if family == "INTERLEAVE":
        highest_degree = max((atom.get("d", 0) for atom in program["atoms"]), default=0)
        if program["k"] == 2 and highest_degree <= 2:
            return 1
        if highest_degree <= 2:
            return 2
        return 3
    if family == "GROWBLOCK":
        return program["dv"]
    if family == "MODAFFINE":
        if program["p"] == 1 and program["M"] <= 43:
            return 1
        if program["p"] == 1 or program["M"] < 53:
            return 2
        return 3
    raise ValueError(f"unknown family: {family}")


def atom_bounds_ok(atom: dict[str, Any]) -> bool:
    if atom["kind"] == "APOLY":
        return (
            1 <= atom["d"] <= 3
            and abs(atom["coefficients"][0]) <= 30
            and all(abs(value) <= 9 for value in atom["coefficients"][1:])
            and atom["coefficients"][-1] != 0
        )
    if atom["kind"] == "AAFFINE":
        return (
            abs(atom["seed"]) <= 30
            and atom["m"] in (-2, -1, 2)
            and abs(atom["b"]) <= 9
        )
    return False


def parameter_bounds_ok(program: dict[str, Any]) -> bool:
    family = program["family"]
    encoded = encode_program(program)
    del encoded
    if not allowed_program_shape(program):
        return False
    if family == "POLY":
        return abs(program["coefficients"][0]) <= 30 and all(abs(v) <= 9 for v in program["coefficients"][1:])
    if family == "PDELTA":
        return abs(program["seed"]) <= 30 and all(abs(v) <= 9 for row in program["coefficients"] for v in row)
    if family == "AFFINE":
        return (
            abs(program["seed"]) <= 30
            and all(v in MULTIPLIERS for v in program["multipliers"])
            and all(abs(v) <= 9 for v in program["biases"])
        )
    if family == "LIN2":
        return (
            all(abs(v) <= 30 for v in program["seeds"])
            and program["u"] in LIN_COEFFICIENTS
            and program["v"] in LIN_COEFFICIENTS
            and all(abs(v) <= 9 for v in program["biases"])
        )
    if family == "LAGPOLY":
        return all(abs(v) <= 30 for v in program["seeds"]) and all(
            abs(v) <= 9 for row in program["coefficients"] for v in row
        )
    if family == "INTERLEAVE":
        for atom in program["atoms"]:
            if not atom_bounds_ok(atom):
                return False
        fingerprints = []
        for atom in program["atoms"]:
            pseudo = {"family": "INTERLEAVE", "k": 1, "atoms": [atom]}
            fingerprints.append(tuple(evaluate(pseudo, 9)))
        return len(set(fingerprints)) == len(fingerprints)
    if family == "GROWBLOCK":
        return (
            abs(program["V"][0]) <= 30
            and all(abs(v) <= 9 for v in program["V"][1:])
            and all(abs(v) <= 9 for v in program["D"])
            and any(program["D"])
        )
    if family == "MODAFFINE":
        return (
            0 <= program["seed"] < program["M"]
            and all(2 <= value <= 9 for value in program["multipliers"])
            and all(0 <= value < program["M"] for value in program["biases"])
        )
    return False


def recognize_poly(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for degree in range(2, 6):
        coefficients = binomial_coefficients_from_values(prefix, degree)
        if coefficients is None:
            continue
        program = {"family": "POLY", "d": degree, "coefficients": coefficients}
        if parameter_bounds_ok(program):
            candidates.append(program)
    return candidates


def recognize_pdelta(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    deltas = [prefix[index] - prefix[index - 1] for index in range(1, len(prefix))]
    for period, degree in ((2, 0), (2, 1), (3, 1), (3, 2), (4, 1), (4, 2)):
        phase_values = [deltas[phase::period] for phase in range(period)]
        vectors = [binomial_coefficients_from_values(values, degree) for values in phase_values]
        if any(vector is None for vector in vectors):
            continue
        program = {
            "family": "PDELTA",
            "p": period,
            "d": degree,
            "seed": prefix[0],
            "coefficients": vectors,
        }
        if len({tuple(row) for row in vectors}) > 1 and parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
            candidates.append(program)
    return candidates


def recognize_affine(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for period in range(1, 4):
        for multipliers in itertools.product(MULTIPLIERS, repeat=period):
            biases: list[int | None] = [None] * period
            valid = True
            for n in range(2, len(prefix) + 1):
                phase = (n - 2) % period
                bias = prefix[n - 1] - multipliers[phase] * prefix[n - 2]
                if biases[phase] is None:
                    biases[phase] = bias
                elif biases[phase] != bias:
                    valid = False
                    break
            if not valid or any(value is None for value in biases):
                continue
            program = {
                "family": "AFFINE",
                "p": period,
                "seed": prefix[0],
                "multipliers": list(multipliers),
                "biases": [int(value) for value in biases],
            }
            if parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
                candidates.append(program)
    return candidates


def recognize_lin2(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    if len(prefix) < 3:
        return candidates
    for period in range(1, 4):
        for u, v in itertools.product(LIN_COEFFICIENTS, repeat=2):
            biases: list[int | None] = [None] * period
            valid = True
            for n in range(3, len(prefix) + 1):
                phase = (n - 3) % period
                bias = prefix[n - 1] - u * prefix[n - 2] - v * prefix[n - 3]
                if biases[phase] is None:
                    biases[phase] = bias
                elif biases[phase] != bias:
                    valid = False
                    break
            if not valid or any(value is None for value in biases):
                continue
            program = {
                "family": "LIN2",
                "p": period,
                "seeds": prefix[:2],
                "u": u,
                "v": v,
                "biases": [int(value) for value in biases],
            }
            if parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
                candidates.append(program)
    return candidates


def recognize_lagpoly(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for lag, degree in ((2, 0), (2, 1), (3, 1), (3, 2), (4, 1)):
        phase_values = [[] for _ in range(lag)]
        for n in range(lag + 1, len(prefix) + 1):
            phase = (n - 1) % lag
            phase_values[phase].append(prefix[n - 1] - prefix[n - lag - 1])
        vectors = [binomial_coefficients_from_values(values, degree) for values in phase_values]
        if any(vector is None for vector in vectors):
            continue
        program = {
            "family": "LAGPOLY",
            "L": lag,
            "d": degree,
            "seeds": prefix[:lag],
            "coefficients": vectors,
        }
        if len({tuple(row) for row in vectors}) > 1 and parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
            candidates.append(program)
    return candidates


def recognize_atoms(values: list[int]) -> list[dict[str, Any]]:
    atoms = []
    for degree in range(1, 4):
        coefficients = binomial_coefficients_from_values(values, degree)
        if coefficients is not None:
            atom = {"kind": "APOLY", "d": degree, "coefficients": coefficients}
            pseudo = {"family": "INTERLEAVE", "k": 1, "atoms": [atom]}
            if atom_bounds_ok(atom) and evaluate(pseudo, len(values)) == values:
                atoms.append(atom)
    for multiplier in (-2, -1, 2):
        if len(values) < 2:
            continue
        bias = values[1] - multiplier * values[0]
        atom = {"kind": "AAFFINE", "seed": values[0], "m": multiplier, "b": bias}
        pseudo = {"family": "INTERLEAVE", "k": 1, "atoms": [atom]}
        if atom_bounds_ok(atom) and evaluate(pseudo, len(values)) == values:
            atoms.append(atom)
    unique = {json.dumps(encode_program(atom), sort_keys=True): atom for atom in atoms}
    return list(unique.values())


def recognize_interleave(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for width in (2, 3):
        child_options = [recognize_atoms(prefix[phase::width]) for phase in range(width)]
        if any(not options for options in child_options):
            continue
        for atoms in itertools.product(*child_options):
            program = {"family": "INTERLEAVE", "k": width, "atoms": list(atoms)}
            if parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
                candidates.append(program)
    return candidates


def visible_blocks(prefix: list[int], l0: int):
    blocks = []
    cursor = 0
    block = 0
    while cursor < len(prefix):
        length = l0 + block
        values = prefix[cursor : min(cursor + length, len(prefix))]
        blocks.append((block, values, length))
        cursor += length
        block += 1
    return blocks


def recognize_growblock(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for l0 in (1, 2):
        blocks = visible_blocks(prefix, l0)
        starts = [values[0] for _, values, _ in blocks]
        observed_steps = []
        arithmetic = True
        for block, values, _ in blocks:
            if len(values) >= 2:
                step = values[1] - values[0]
                if any(values[index] - values[index - 1] != step for index in range(2, len(values))):
                    arithmetic = False
                    break
                observed_steps.append((block, step))
        if not arithmetic:
            continue
        for degree_v in range(1, 4):
            vector_v = binomial_coefficients_from_values(starts, degree_v)
            if vector_v is None:
                continue
            for degree_d in range(0, 2):
                vector_d = None
                if degree_d == 0 and observed_steps:
                    if len({step for _, step in observed_steps}) == 1:
                        vector_d = [observed_steps[0][1]]
                elif degree_d == 1 and len(observed_steps) >= 2:
                    (x1, y1), (x2, y2) = observed_steps[0], observed_steps[1]
                    if x2 != x1 and (y2 - y1) % (x2 - x1) == 0:
                        slope = (y2 - y1) // (x2 - x1)
                        intercept = y1 - slope * x1
                        if all(intercept + slope * x == y for x, y in observed_steps):
                            vector_d = [intercept, slope]
                if vector_d is None:
                    continue
                program = {
                    "family": "GROWBLOCK",
                    "l0": l0,
                    "dv": degree_v,
                    "dd": degree_d,
                    "V": vector_v,
                    "D": vector_d,
                }
                if parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
                    candidates.append(program)
    return candidates


def recognize_modaffine(prefix: list[int]) -> list[dict[str, Any]]:
    candidates = []
    for modulus in PRIMES:
        if any(value < 0 or value >= modulus for value in prefix):
            continue
        for period in (1, 2):
            for multipliers in itertools.product(range(2, 10), repeat=period):
                biases: list[int | None] = [None] * period
                valid = True
                for n in range(2, len(prefix) + 1):
                    phase = (n - 2) % period
                    bias = (prefix[n - 1] - multipliers[phase] * prefix[n - 2]) % modulus
                    if biases[phase] is None:
                        biases[phase] = bias
                    elif biases[phase] != bias:
                        valid = False
                        break
                if not valid or any(value is None for value in biases):
                    continue
                program = {
                    "family": "MODAFFINE",
                    "p": period,
                    "M": modulus,
                    "seed": prefix[0],
                    "multipliers": list(multipliers),
                    "biases": [int(value) for value in biases],
                }
                if parameter_bounds_ok(program) and evaluate(program, len(prefix)) == prefix:
                    candidates.append(program)
    return candidates


RECOGNIZERS = (
    recognize_poly,
    recognize_pdelta,
    recognize_affine,
    recognize_lin2,
    recognize_lagpoly,
    recognize_interleave,
    recognize_growblock,
    recognize_modaffine,
)


def recognize(prefix: list[int]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for recognizer in RECOGNIZERS:
        for program in recognizer(prefix):
            candidates[canonical_program(program)] = program
    return list(candidates.values())


def ambiguity_audit(program: dict[str, Any], visible: list[int], target_count: int = 5) -> dict[str, Any]:
    visible_count = len(visible)
    candidates = recognize(visible)
    intended_fingerprint = tuple(evaluate(program, 25))
    semantic: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    predictions: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for candidate in candidates:
        fingerprint = tuple(evaluate(candidate, 25))
        semantic.setdefault(fingerprint, []).append(candidate)
        prediction = tuple(evaluate(candidate, visible_count + target_count)[visible_count:])
        predictions.setdefault(prediction, []).append(candidate)
    family_counts = Counter(candidate["family"] for candidate in candidates)
    lower_tier = [candidate for candidate in candidates if minimum_tier(candidate) < minimum_tier(program)]

    probes = []
    for prefix_length in sorted({max(6, visible_count - 4), max(6, visible_count - 2), visible_count}):
        probe_candidates = recognize(visible[:prefix_length])
        probe_predictions = set()
        for candidate in probe_candidates:
            values = evaluate(candidate, visible_count + target_count)
            probe_predictions.add(tuple(values[visible_count : visible_count + target_count]))
        probes.append(
            {
                "prefix_length": prefix_length,
                "candidate_count": len(probe_candidates),
                "candidate_families": sorted({candidate["family"] for candidate in probe_candidates}),
                "distinct_target_predictions": len(probe_predictions),
            }
        )

    return {
        "candidate_count": len(candidates),
        "semantic_candidate_count": len(semantic),
        "distinct_target_predictions": len(predictions),
        "candidate_family_counts": dict(sorted(family_counts.items())),
        "intended_semantics_present": intended_fingerprint in semantic,
        "lower_tier_candidate_count": len(lower_tier),
        "unique_next_five": len(predictions) == 1,
        "probes": probes,
    }


def case_bounds_ok(program: dict[str, Any], visible_count: int) -> tuple[bool, dict[str, int]]:
    values, maximum_intermediate = evaluate(program, visible_count + 5, with_intermediate=True)
    visible = values[:visible_count]
    targets = values[visible_count:]
    if any(abs(value) > VISIBLE_MAX for value in visible):
        return False, {}
    if any(abs(value) > TARGET_MAX for value in targets):
        return False, {}
    if maximum_intermediate > INTERMEDIATE_MAX:
        return False, {}
    if len(set(visible)) < 6:
        return False, {}
    if program["family"] != "GROWBLOCK":
        run = 1
        for index in range(1, len(visible)):
            run = run + 1 if visible[index] == visible[index - 1] else 1
            if run > 3:
                return False, {}
    if program["family"] != "MODAFFINE":
        for left, right in zip(values, values[1:]):
            left_digits = len(str(abs(left))) if left else 1
            right_digits = len(str(abs(right))) if right else 1
            if right_digits - left_digits > 4:
                return False, {}
    if program["family"] == "MODAFFINE":
        wraps = 0
        for n in range(2, visible_count + 1):
            phase = (n - 2) % program["p"]
            raw = program["multipliers"][phase] * values[n - 2] + program["biases"][phase]
            wraps += raw >= program["M"]
        if wraps < 2 or len(set(values)) != len(values):
            return False, {}
    return True, {
        "max_abs_visible": max(abs(value) for value in visible),
        "max_abs_target": max(abs(value) for value in targets),
        "max_abs_intermediate": maximum_intermediate,
    }


def make_case(split: str, case_id: str, family: str, tier: str, repetition: int) -> tuple[dict, dict, dict]:
    visible_count = VISIBLE_BY_TIER[tier]
    for attempt in range(1, 20001):
        rng = SplitMix64(f"{ROOT_SEED}|{split}|{family}|{tier}|{repetition}|{attempt}")
        program = generate_program(family, tier, rng)
        if minimum_tier(program) != TIER_NUMBER[tier]:
            continue
        bounds_ok, bounds = case_bounds_ok(program, visible_count)
        if not bounds_ok:
            continue
        values = evaluate(program, visible_count + 5)
        visible = values[:visible_count]
        targets = values[visible_count:]
        audit = ambiguity_audit(program, visible)
        if not audit["intended_semantics_present"] or not audit["unique_next_five"]:
            continue
        if tier != "hard" and audit["lower_tier_candidate_count"]:
            continue
        public = {
            "case_id": case_id,
            "terms": [int_string(value) for value in visible],
            "target_count": 5,
            "answer_format": {"next": ["decimal-string"] * 5, "confidence": "0.00..1.00"},
        }
        public_digest = sha256_bytes(json_bytes(public))
        hidden = {
            "case_id": case_id,
            "split": split,
            "family": family,
            "tier": tier,
            "visible_count": visible_count,
            "next": [int_string(value) for value in targets],
            "program": encode_program(program),
            "public_case_sha256": public_digest,
            "generation_attempt": attempt,
        }
        audit_record = {
            "case_id": case_id,
            "split": split,
            "family": family,
            "tier": tier,
            "visible_count": visible_count,
            "program_sha256": sha256_bytes(canonical_program(program).encode("utf-8")),
            "target_sha256": sha256_bytes(",".join(map(str, targets)).encode("utf-8")),
            "bounds": {name: int_string(value) for name, value in bounds.items()},
            **audit,
        }
        return public, hidden, audit_record
    raise RuntimeError(f"could not generate {split} {family} {tier} after 20000 attempts")


def build_assignments():
    development_cells = []
    calibration_cells = []
    for family_index, family in enumerate(FAMILIES):
        for tier_index, tier in enumerate(TIERS):
            destination = development_cells if (family_index + tier_index) % 2 == 0 else calibration_cells
            destination.append((family, tier, 1))
    SplitMix64(f"{ROOT_SEED}|development-order").shuffle(development_cells)
    SplitMix64(f"{ROOT_SEED}|calibration-order").shuffle(calibration_cells)

    final_cells = []
    for block in range(4):
        family_indices = range(0, 4) if block in (0, 2) else range(4, 8)
        repetition = 1 if block < 2 else 2
        block_cells = [
            (FAMILIES[family_index], tier, repetition)
            for tier in TIERS
            for family_index in family_indices
        ]
        SplitMix64(f"{ROOT_SEED}|final-block-{block + 1}").shuffle(block_cells)
        final_cells.extend(block_cells)
    return {
        "development": development_cells,
        "calibration": calibration_cells,
        "final": final_cells,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = b"".join(json_bytes(record) for record in records)
    path.write_bytes(payload)


def task_block(block_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "experiment_id": "swarm-seeds-02",
        "block_id": block_id,
        "cases": [
            {"case_id": record["case_id"], "prefix": list(record["terms"])}
            for record in records
        ],
    }


def readme_text() -> str:
    return """# RuleWeave-5 benchmark\n\nRuleWeave-5 contains procedurally generated integer-sequence tasks. Each public case provides 12 to 14 terms and asks for the next five. Every value is a decimal string, every rule is deterministic, and all reference arithmetic uses Python integers.\n\n## Layout\n\n- `public/development_cases.jsonl`: 12 development cases\n- `public/calibration_cases.jsonl`: 12 calibration cases\n- `public/final_cases.jsonl`: 48 untouched final cases\n- `public/development_block.json`: the development call block\n- `public/calibration_block.json`: the calibration call block\n- `public/final_B01.json` through `public/final_B04.json`: four final call blocks\n- `public/final_blocks.json`: answer-free final block manifest\n- `hidden/*_answers.jsonl`: programs and exact next-five answers\n- `hidden/recognizer_audit.json`: cross-family ambiguity and bounds audit\n- `manifest.json`: design invariants and SHA-256 checksums\n\nDo not provide `hidden/`, the generator seed, or generated answers to subject agents during the run. Each model call receives one complete 12-case block assembled from the public cases. Subjects may not use tools, code, Python, web search, or files.\n\n`manifest.json` uses benchmark-manifest schema `1.0`. Experimental prompts, task blocks, packets, and model outputs use the separate experiment schema `2.0`.\n\nThe final set has exactly two cases in every family and tier cell. Each family occurs six times, each tier occurs sixteen times, and every consecutive 12-case block contains four cases from each tier.\n"""


def generate() -> dict[str, Any]:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_DIR.mkdir(parents=True, exist_ok=True)
    assignments = build_assignments()
    all_audits = []
    generated: dict[str, dict[str, list[dict[str, Any]]]] = {}

    prefixes = {"development": "D", "calibration": "C", "final": "F"}
    widths = {"development": 2, "calibration": 2, "final": 3}
    for split, cells in assignments.items():
        public_records = []
        hidden_records = []
        for index, (family, tier, repetition) in enumerate(cells, start=1):
            case_id = f"{prefixes[split]}{index:0{widths[split]}d}"
            public, hidden, audit = make_case(split, case_id, family, tier, repetition)
            public_records.append(public)
            hidden_records.append(hidden)
            all_audits.append(audit)
        generated[split] = {"public": public_records, "hidden": hidden_records}
        write_jsonl(PUBLIC_DIR / f"{split}_cases.jsonl", public_records)
        write_jsonl(HIDDEN_DIR / f"{split}_answers.jsonl", hidden_records)

    development_block = task_block("development-b01", generated["development"]["public"])
    calibration_block = task_block("calibration-b01", generated["calibration"]["public"])
    (PUBLIC_DIR / "development_block.json").write_bytes(json_bytes(development_block, pretty=True))
    (PUBLIC_DIR / "calibration_block.json").write_bytes(json_bytes(calibration_block, pretty=True))
    final_blocks = []
    for block_index in range(4):
        block_id = f"B{block_index + 1:02d}"
        records = generated["final"]["public"][block_index * 12 : (block_index + 1) * 12]
        block = task_block(block_id, records)
        final_blocks.append(block)
        (PUBLIC_DIR / f"final_{block_id}.json").write_bytes(json_bytes(block, pretty=True))
    final_block_manifest = {
        "schema_version": "2.0",
        "experiment_id": "swarm-seeds-02",
        "final_blocks": final_blocks,
    }
    (PUBLIC_DIR / "final_blocks.json").write_bytes(json_bytes(final_block_manifest, pretty=True))

    audit_document = {
        "benchmark_id": BENCHMARK_ID,
        "definition": "All recognized DSL programs matching a complete prefix must predict the same next five terms.",
        "cases": all_audits,
    }
    (HIDDEN_DIR / "recognizer_audit.json").write_bytes(json_bytes(audit_document, pretty=True))
    generation_receipt = {
        "benchmark_id": BENCHMARK_ID,
        "root_seed": ROOT_SEED,
        "root_seed_sha256": sha256_bytes(ROOT_SEED.encode("utf-8")),
        "generator": "experiment/scripts/generate_benchmark.py",
        "arithmetic": "Python arbitrary-precision integers",
    }
    (HIDDEN_DIR / "generation_receipt.json").write_bytes(json_bytes(generation_receipt, pretty=True))
    (BENCHMARK_DIR / "README.md").write_text(readme_text(), encoding="utf-8")

    data_paths = [
        PUBLIC_DIR / "development_cases.jsonl",
        PUBLIC_DIR / "calibration_cases.jsonl",
        PUBLIC_DIR / "final_cases.jsonl",
        PUBLIC_DIR / "development_block.json",
        PUBLIC_DIR / "calibration_block.json",
        PUBLIC_DIR / "final_B01.json",
        PUBLIC_DIR / "final_B02.json",
        PUBLIC_DIR / "final_B03.json",
        PUBLIC_DIR / "final_B04.json",
        PUBLIC_DIR / "final_blocks.json",
        HIDDEN_DIR / "development_answers.jsonl",
        HIDDEN_DIR / "calibration_answers.jsonl",
        HIDDEN_DIR / "final_answers.jsonl",
        HIDDEN_DIR / "recognizer_audit.json",
        HIDDEN_DIR / "generation_receipt.json",
        BENCHMARK_DIR / "README.md",
    ]
    checksums = {
        str(path.relative_to(BENCHMARK_DIR)): sha256_bytes(path.read_bytes())
        for path in data_paths
    }

    final_hidden = generated["final"]["hidden"]
    final_family_counts = Counter(record["family"] for record in final_hidden)
    final_tier_counts = Counter(record["tier"] for record in final_hidden)
    block_tier_counts = []
    for block in range(4):
        block_records = final_hidden[block * 12 : (block + 1) * 12]
        block_tier_counts.append(dict(sorted(Counter(record["tier"] for record in block_records).items())))

    manifest = {
        "schema_version": "1.0",
        "schema_scope": "RuleWeave benchmark manifest only; experiment packets and outputs use schema 2.0",
        "benchmark_id": BENCHMARK_ID,
        "task": "continue each integer sequence with exactly five terms",
        "public_reasoning_labels": ["light", "medium"],
        "provider_reasoning_setting_for_light": "low",
        "families": list(FAMILIES),
        "tiers": list(TIERS),
        "visible_terms": VISIBLE_BY_TIER,
        "target_terms": 5,
        "splits": {"development": 12, "calibration": 12, "final": 48},
        "development_plus_calibration_cover_every_family_tier_cell": True,
        "final_cases_per_family_tier_cell": 2,
        "final_family_counts": dict(sorted(final_family_counts.items())),
        "final_tier_counts": dict(sorted(final_tier_counts.items())),
        "final_12_case_block_tier_counts": block_tier_counts,
        "integer_policy": {
            "public_encoding": "signed decimal strings",
            "visible_max_abs": str(VISIBLE_MAX),
            "target_max_abs": str(TARGET_MAX),
            "intermediate_max_abs": str(INTERMEDIATE_MAX),
            "reference_arithmetic": "Python arbitrary-precision integers",
        },
        "ambiguity_policy": "all recognized full-prefix DSL candidates must predict one identical next-five tuple",
        "root_seed_sha256": sha256_bytes(ROOT_SEED.encode("utf-8")),
        "checksums": checksums,
    }
    (BENCHMARK_DIR / "manifest.json").write_bytes(json_bytes(manifest, pretty=True))
    return manifest


if __name__ == "__main__":
    generated_manifest = generate()
    print(json.dumps({
        "benchmark_id": generated_manifest["benchmark_id"],
        "splits": generated_manifest["splits"],
        "final_family_counts": generated_manifest["final_family_counts"],
        "final_tier_counts": generated_manifest["final_tier_counts"],
        "status": "generated",
    }, indent=2, sort_keys=True))
