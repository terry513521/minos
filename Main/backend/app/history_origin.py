"""Classify round_history rows as portfolio (real) vs seed vs worker vs import."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")

HISTORY_ORIGIN_PORTFOLIO = "portfolio"
HISTORY_ORIGIN_SEED = "seed"
HISTORY_ORIGIN_WORKER = "worker"
HISTORY_ORIGIN_IMPORT = "import"

HISTORY_ORIGINS: frozenset[str] = frozenset(
    {
        HISTORY_ORIGIN_PORTFOLIO,
        HISTORY_ORIGIN_SEED,
        HISTORY_ORIGIN_WORKER,
        HISTORY_ORIGIN_IMPORT,
    }
)

HISTORY_ORIGIN_LABELS: dict[str, str] = {
    HISTORY_ORIGIN_PORTFOLIO: "Real",
    HISTORY_ORIGIN_SEED: "Seeded",
    HISTORY_ORIGIN_WORKER: "Worker",
    HISTORY_ORIGIN_IMPORT: "Import",
}

# Chromosome length (GRCh38) — skip remap when end exceeds chr22.
CHR22_MAX_END = 51_033_777

SEED_SOURCE_CHROMS: frozenset[str] = frozenset({"chr20", "chr21"})

SEED_SOURCE_KEY_PREFIX = "seed:chr22:from:"


def worker_for_seed_slot(worker_ids: list[str], slot: int) -> str:
    """Round-robin worker pick for seed slot 0, 1, 2, …"""
    return worker_ids[slot % len(worker_ids)]


def chunk_seed_work_items(items: list[T], wave_size: int) -> list[list[T]]:
    """Split seed jobs into waves of at most one task per worker."""
    if wave_size <= 0:
        return [items] if items else []
    return [items[i : i + wave_size] for i in range(0, len(items), wave_size)]


def infer_history_origin(source_key: str | None) -> str:
    """Best-effort origin from source_key (used when backfilling legacy rows)."""
    if not source_key:
        return HISTORY_ORIGIN_PORTFOLIO
    key = source_key.lower()
    if key.startswith("seed:"):
        return HISTORY_ORIGIN_SEED
    if key.startswith("run:"):
        return HISTORY_ORIGIN_WORKER
    if key.startswith("import:"):
        return HISTORY_ORIGIN_IMPORT
    return HISTORY_ORIGIN_PORTFOLIO


def seed_source_key(source_history_id: str) -> str:
    return f"{SEED_SOURCE_KEY_PREFIX}{source_history_id}"


def parse_seed_source_history_id(source_key: str | None) -> str | None:
    """Portfolio round_history id embedded in a chr22 seed source_key."""
    if not source_key or not source_key.startswith(SEED_SOURCE_KEY_PREFIX):
        return None
    suffix = source_key[len(SEED_SOURCE_KEY_PREFIX) :].strip()
    return suffix or None


def seed_result_fingerprint(window: str, tool: str, conf: dict[str, Any] | None) -> tuple[str, str, str]:
    """Stable identity for an existing chr22 seed row (window + tool + conf)."""
    payload = json.dumps(conf or {}, sort_keys=True, separators=(",", ":"))
    return (window.strip(), tool.lower().strip(), payload)


@dataclass
class ExistingSeedState:
    """Chr22 rows already seeded — skip re-benchmarking these portfolio sources."""

    source_keys: set[str] = field(default_factory=set)
    portfolio_ids: set[str] = field(default_factory=set)
    fingerprints: set[tuple[str, str, str]] = field(default_factory=set)

    def register_seed(
        self,
        *,
        source_key: str,
        portfolio_id: str,
        target_window: str,
        tool: str,
        conf: dict[str, Any],
    ) -> None:
        self.source_keys.add(source_key)
        self.portfolio_ids.add(portfolio_id)
        self.fingerprints.add(seed_result_fingerprint(target_window, tool, conf))

    def is_already_seeded(
        self,
        *,
        portfolio_id: str,
        target_window: str,
        tool: str,
        conf: dict[str, Any],
    ) -> bool:
        if seed_source_key(portfolio_id) in self.source_keys:
            return True
        if portfolio_id in self.portfolio_ids:
            return True
        return seed_result_fingerprint(target_window, tool, conf) in self.fingerprints


def remap_window_to_chr22(window: str) -> str | None:
    """Map chr20/chr21 window to chr22 with same coordinates, or None if invalid."""
    from app.selector import parse_window

    try:
        parsed = parse_window(window)
    except ValueError:
        return None

    chrom = parsed.chromosome.lower()
    if chrom not in SEED_SOURCE_CHROMS:
        return None
    if parsed.end > CHR22_MAX_END or parsed.start >= parsed.end:
        return None
    return f"chr22:{parsed.start}-{parsed.end}"
