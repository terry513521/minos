"""Filesystem roots for the Worker package."""

from __future__ import annotations

import os
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]


def get_repo_root() -> Path:
    """minos_subnet checkout (templates + utils.scoring)."""
    env_root = os.getenv("WORKER_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return WORKER_ROOT.parent


def data_root(data_dir: str = "datasets") -> Path:
    return WORKER_ROOT / data_dir
