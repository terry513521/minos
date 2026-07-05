"""Tests for GIAB BAM cache helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("fcntl", MagicMock())

from app.benchmark.giab.data import _bam_cache_ready, _clear_incomplete_bam  # noqa: E402


def test_bam_cache_ready_requires_index(tmp_path: Path) -> None:
    bam = tmp_path / "slice.bam"
    bam.write_bytes(b"x" * 2048)
    assert not _bam_cache_ready(bam)
    (tmp_path / "slice.bam.bai").write_bytes(b"bai")
    assert _bam_cache_ready(bam)


def test_clear_incomplete_bam_removes_partial_files(tmp_path: Path) -> None:
    bam = tmp_path / "slice.bam"
    bai = tmp_path / "slice.bam.bai"
    bam.write_bytes(b"partial")
    bai.write_bytes(b"partial")
    _clear_incomplete_bam(bam)
    assert not bam.exists()
    assert not bai.exists()
