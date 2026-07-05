"""GIAB asset paths under Worker/datasets/giab/."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.paths import WORKER_ROOT

# Minos-like 5 Mb windows (from recent round history).
MINOS_GIAB_REGIONS = (
    ("chr20", "chr20:39669962-44669962"),
    ("chr21", "chr21:35444092-40444092"),
    ("chr22", "chr22:35444092-40444092"),
)


def _data_root() -> Path:
    return WORKER_ROOT / get_settings().data_dir


def giab_root() -> Path:
    return _data_root() / "giab"


def giab_data_dir() -> Path:
    return giab_root() / "data"


def giab_bam_dir() -> Path:
    return giab_root() / "bam"


def giab_vcf_dir() -> Path:
    return giab_root() / "vcf"


def reference_dir(chrom: str) -> Path:
    return _data_root() / "reference" / chrom
