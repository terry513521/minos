"""Tests for GIAB remote BAM samtools helpers (fcntl mocked for Windows)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("fcntl", MagicMock())

from app.benchmark.giab.data import (  # noqa: E402
    ASSETS,
    _INDEX_FMT_OPTION_KEYS,
    _SAMTOOLS_DOCKER_IMAGE,
    _build_docker_samtools_cmd,
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


def test_docker_remote_view_uses_samtools_entrypoint():
    bai_name = "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"
    cmd = _build_docker_samtools_cmd(
        [
            "view",
            "-b",
            "-o",
            "/out/HG002_chr22_22358161-27358161.bam",
            "--input-fmt-option",
            f"index=/idx/{bai_name}",
            ASSETS["bam_remote"],
            "chr22:22358161-27358161",
        ],
        volumes=[
            ("/datasets/giab/data", "/idx", "ro"),
            ("/datasets/giab/bam", "/out", "rw"),
        ],
        network_host=True,
    )
    assert cmd[0] == "docker"
    assert "--entrypoint" in cmd
    entry_idx = cmd.index("--entrypoint")
    assert cmd[entry_idx + 1] == "samtools"
    assert _SAMTOOLS_DOCKER_IMAGE in cmd
    assert "sh" not in cmd
    assert f"index=/idx/{bai_name}" in cmd
    assert "chr22:22358161-27358161" in cmd
    assert "--network=host" in cmd
