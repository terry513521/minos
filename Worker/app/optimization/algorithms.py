from __future__ import annotations

OPTUNA_ALGORITHMS = frozenset({"optuna", "gp"})
EXPLORATION_ALGORITHMS = frozenset({"random", "sobol", "lhs", "grid", "delta"})
EVOLUTIONARY_ALGORITHMS = frozenset({"pbt", "cascade"})
ADAPTIVE_ALGORITHMS = frozenset(
    {*OPTUNA_ALGORITHMS, *EXPLORATION_ALGORITHMS, *EVOLUTIONARY_ALGORITHMS}
)
SUPPORTED_ALGORITHMS = ADAPTIVE_ALGORITHMS
DEFAULT_ALGORITHM = "cascade"
RECOMMENDED_HIGH_CONCURRENCY = frozenset({"pbt", "cascade"})


def normalize_algorithm(raw: str) -> str:
    algo = str(raw or DEFAULT_ALGORITHM).strip().lower()
    if algo in SUPPORTED_ALGORITHMS:
        return algo
    raise ValueError(
        f"Unsupported algorithm: {raw!r} "
        f"(use {', '.join(sorted(SUPPORTED_ALGORITHMS))})"
    )


def is_adaptive_algorithm(algorithm: str) -> bool:
    return algorithm in ADAPTIVE_ALGORITHMS


def is_optuna_algorithm(algorithm: str) -> bool:
    return algorithm in OPTUNA_ALGORITHMS


def is_parallel_algorithm(algorithm: str) -> bool:
    """Algorithms that evaluate multiple trials concurrently."""
    return algorithm in EXPLORATION_ALGORITHMS or algorithm in EVOLUTIONARY_ALGORITHMS


def is_grid_algorithm(algorithm: str) -> bool:
    return algorithm == "grid"
