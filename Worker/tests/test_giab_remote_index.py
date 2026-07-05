"""Tests for GIAB remote BAM index helpers (fcntl mocked for Windows)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("fcntl", MagicMock())

from app.benchmark.giab.data import (  # noqa: E402
    ASSETS,
    remote_hg002_bam_index_path,
)


def test_remote_bam_index_path_name():
    path = remote_hg002_bam_index_path()
    assert path.name == "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"


def test_bam_remote_bai_url():
    assert ASSETS["bam_remote_bai"].endswith(".bam.bai")


def test_pysam_extract_region_import():
    from app.benchmark.giab.data import _pysam_extract_region  # noqa: PLC0415

    assert callable(_pysam_extract_region)
