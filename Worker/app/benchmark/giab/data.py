"""GIAB data layer — bundled vendor/tuning/giab/data (samtools + BAM cache)."""

from __future__ import annotations

from typing import Any

from app.benchmark.giab.tuning_bridge import ensure_tuning_giab


def __getattr__(name: str) -> Any:
    ensure_tuning_giab()
    from tuning.giab import data as tuning_data

    if name == "_bam_cache_ready":
        return tuning_data.bam_cache_ready
    if name == "_clear_incomplete_bam":
        return _clear_incomplete_bam
    try:
        return getattr(tuning_data, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def _clear_incomplete_bam(bam) -> None:
    ensure_tuning_giab()
    from tuning.giab.data import _remove_regional_bam

    _remove_regional_bam(bam)


def ensure_remote_bam_index():
    """No-op compatibility — tuning samtools fetches remote .bai via htslib."""
    from pathlib import Path

    ensure_tuning_giab()
    from tuning.giab.data import ASSETS

    from app.benchmark.giab.paths import giab_data_dir

    giab_data_dir().mkdir(parents=True, exist_ok=True)
    return giab_data_dir() / Path(ASSETS["bam_remote"]).name.replace(".bam", ".bam.bai")
