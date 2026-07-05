"""Tests for GIAB remote BAM samtools helpers (fcntl mocked for Windows)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("fcntl", MagicMock())

from app.benchmark.giab.data import (  # noqa: E402
    ASSETS,
    _INDEX_FMT_OPTION_KEYS,
    _docker_samtools_remote_view_script,
    _samtools_remote_view_cmd,
    remote_hg002_bam_index_path,
)


def test_remote_bam_index_path_name():
    path = remote_hg002_bam_index_path()
    assert path.name == "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"


def test_samtools_remote_view_prefers_index_option():
    cmd = _samtools_remote_view_cmd(
        remote_bam=ASSETS["bam_remote"],
        local_bai=Path("/data/HG002.bam.bai"),
        region="chr22:22358161-27358161",
        dest=Path("/out/slice.bam"),
        samtools="samtools",
        index_option_key="index",
    )
    assert "--input-fmt-option" in cmd
    assert "index=/data/HG002.bam.bai" in cmd
    assert _INDEX_FMT_OPTION_KEYS[0] == "index"


def test_docker_remote_view_script_tries_index_options():
    bai_name = "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"
    script = _docker_samtools_remote_view_script(
        remote_bam=ASSETS["bam_remote"],
        local_bai=Path(f"/datasets/giab/data/{bai_name}"),
        region="chr22:22358161-27358161",
        dest_name="HG002_chr22_22358161-27358161.bam",
    )
    assert f"index=/idx/{bai_name}" in script
    assert f"load_index=/idx/{bai_name}" in script
    assert "chr22:22358161-27358161" in script
