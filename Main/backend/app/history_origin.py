"""Classify round_history rows as portfolio (real) vs seed vs worker vs import."""

from __future__ import annotations

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
    return f"seed:chr22:from:{source_history_id}"


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
