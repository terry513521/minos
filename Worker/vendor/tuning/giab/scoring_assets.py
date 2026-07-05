"""Cached GIAB scoring inputs (truth slice, confident BED) — quality-neutral speedups."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from tuning.giab.data import chrom_from_region, ensure_sdf, ensure_truth_assets, parse_region_bounds
from tuning.giab.paths import GIAB_DATA_DIR

logger = logging.getLogger(__name__)

REGION_CACHE_DIR = GIAB_DATA_DIR / "region_cache"


def _region_slug(region: str) -> str:
    return region.replace(":", "_").replace("-", "_")


def cached_truth_vcf_for_region(region: str) -> Path:
    """Region-sliced GIAB truth VCF (same bcftools slice as hap.py, cached on disk)."""
    REGION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = REGION_CACHE_DIR / f"truth_{_region_slug(region)}.vcf.gz"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    truth_vcf, _ = ensure_truth_assets()
    from utils.scoring import slice_truth_vcf

    if slice_truth_vcf(truth_vcf, dest, region):
        logger.info("Cached GIAB truth slice: %s", dest.name)
        return dest
    return truth_vcf


def cached_confident_bed_for_region(region: str) -> Path:
    """Confident BED subset overlapping *region* (cached on disk)."""
    REGION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = REGION_CACHE_DIR / f"confident_{_region_slug(region)}.bed"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    _, truth_bed = ensure_truth_assets()
    from utils.scoring import subset_bed

    if subset_bed(truth_bed, dest, region):
        logger.info("Cached GIAB confident BED: %s", dest.name)
        return dest
    return truth_bed


def prepare_region_scoring_assets(region: str) -> None:
    """Pre-build truth/BED/SDF cache for a round region (background-safe)."""
    try:
        parse_region_bounds(region)
    except ValueError:
        return
    cached_truth_vcf_for_region(region)
    cached_confident_bed_for_region(region)
    ensure_sdf(chrom_from_region(region))


def giab_hap_threads() -> int:
    raw = os.getenv("GIAB_HAP_THREADS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return max(1, min(8, os.cpu_count() or 4))
