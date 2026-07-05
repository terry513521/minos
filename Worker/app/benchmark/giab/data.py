"""GIAB data layer — delegates to minos/tuning/giab/data (samtools + BAM cache)."""

from __future__ import annotations

from pathlib import Path

from app.benchmark.giab.tuning_bridge import ensure_tuning_giab

ensure_tuning_giab()

from tuning.giab.data import (  # noqa: E402
    ASSETS,
    GIAB_BASE,
    bam_cache_ready,
    bam_cache_ready_for_region,
    bam_index_path,
    chrom_from_region,
    ensure_bam_for_region,
    ensure_regional_bam,
    ensure_sdf,
    ensure_truth_assets,
    parse_region_bounds,
    prepare_all,
    reference_for_chrom,
    region_contains,
    regional_bam_cache_path,
    regional_bam_valid,
    repair_giab_bam_indexes,
    _remove_regional_bam,
    _samtools_bin,
)

# Worker compatibility aliases (legacy private names).
_bam_cache_ready = bam_cache_ready


def _clear_incomplete_bam(bam: Path) -> None:
    _remove_regional_bam(bam)


def ensure_remote_bam_index() -> Path:
    """No-op compatibility — tuning samtools fetches remote .bai via htslib."""
    from app.benchmark.giab.paths import giab_data_dir

    giab_data_dir().mkdir(parents=True, exist_ok=True)
    return giab_data_dir() / Path(ASSETS["bam_remote"]).name.replace(".bam", ".bam.bai")
