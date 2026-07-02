from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkResult:
    success: bool
    score: float
    raw_score: float
    conf: dict[str, Any]
    variant_count: int
    error: str | None = None
    cached: bool = False
