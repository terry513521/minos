from __future__ import annotations

OPTUNA_ALGORITHMS = frozenset({"optuna", "gp"})
EXPLORATION_ALGORITHMS = frozenset({"random", "sobol", "lhs"})
ADAPTIVE_ALGORITHMS = frozenset({*OPTUNA_ALGORITHMS, *EXPLORATION_ALGORITHMS})
SUPPORTED_ALGORITHMS = ADAPTIVE_ALGORITHMS
DEFAULT_ALGORITHM = "optuna"


def normalize_algorithm(raw: str) -> str:
    algo = str(raw or DEFAULT_ALGORITHM).strip().lower()
    if algo in SUPPORTED_ALGORITHMS:
        return algo
    raise ValueError(
        f"Unsupported algorithm: {raw!r} (use optuna, gp, random, sobol, or lhs)"
    )


def is_adaptive_algorithm(algorithm: str) -> bool:
    return algorithm in ADAPTIVE_ALGORITHMS


def is_optuna_algorithm(algorithm: str) -> bool:
    return algorithm in OPTUNA_ALGORITHMS
