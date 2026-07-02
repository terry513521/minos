from __future__ import annotations


def normalize_algorithm(raw: str) -> str:
    algo = str(raw or "grid").strip().lower()
    if algo in ("grid", "random", "optuna"):
        return algo
    raise ValueError(f"Unsupported algorithm: {raw!r} (use grid, random, or optuna)")


def is_adaptive_algorithm(algorithm: str) -> bool:
    return algorithm in ("random", "optuna")
