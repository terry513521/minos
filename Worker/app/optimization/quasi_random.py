"""Latin Hypercube and Sobol quasi-random search over discrete param axes."""

from __future__ import annotations

import hashlib
from typing import Any

from app.optimization.param_specs import TuneSpec
from app.optimization.search import _values_for_param


def seed_from_job_id(job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode()).hexdigest()
    return int(digest[:8], 16)


def unit_to_index(u: float, size: int) -> int:
    if size <= 1:
        return 0
    clamped = min(max(float(u), 0.0), 1.0 - 1e-12)
    return min(int(clamped * size), size - 1)


def params_from_unit_row(
    unit_row: list[float],
    *,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
) -> dict[str, Any]:
    param_values: dict[str, Any] = {}
    for u, spec in zip(unit_row, specs, strict=True):
        values = _values_for_param(base_conf, tool, spec)
        param_values[spec.name] = values[unit_to_index(u, len(values))]
    return param_values


def generate_unit_samples(algorithm: str, n: int, dimensions: int, seed: int) -> list[list[float]]:
    """Return n points in [0, 1)^dimensions using LHS or Sobol."""
    if n <= 0 or dimensions <= 0:
        return []

    from scipy.stats import qmc

    if algorithm == "sobol":
        draw_n = 1 if n == 1 else 1 << (n - 1).bit_length()
        engine = qmc.Sobol(d=dimensions, scramble=True, seed=seed)
        matrix = engine.random(n=draw_n)[:n]
    elif algorithm == "lhs":
        engine = qmc.LatinHypercube(d=dimensions, seed=seed)
        matrix = engine.random(n=n)
    else:
        raise ValueError(f"Unsupported quasi-random algorithm: {algorithm}")

    return [list(map(float, row)) for row in matrix]


def build_quasi_sample_confs(
    algorithm: str,
    *,
    n: int,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    seed: int,
) -> list[dict[str, Any]]:
    """Unit hypercube samples mapped onto discrete search axes."""
    unit_samples = generate_unit_samples(algorithm, n, len(specs), seed)
    return [
        params_from_unit_row(row, base_conf=base_conf, tool=tool, specs=specs)
        for row in unit_samples
    ]
