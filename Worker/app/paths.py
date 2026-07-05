"""Filesystem roots for the Worker package."""

from __future__ import annotations

from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = WORKER_ROOT / "vendor"


def get_vendor_root() -> Path:
    """Bundled templates, utils, and tuning/giab shipped inside Worker/."""
    return VENDOR_ROOT


def get_repo_root() -> Path:
    """Backward-compatible alias for get_vendor_root()."""
    return get_vendor_root()


def data_root(data_dir: str = "datasets") -> Path:
    return WORKER_ROOT / data_dir
