"""Tests for GIAB remote BAM samtools helpers (fcntl mocked for Windows)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("fcntl", MagicMock())

from app.benchmark.giab.data import (  # noqa: E402
    ASSETS,
    _SAMTOOLS_DOCKER_IMAGE,
    _build_docker_samtools_cmd,
    _remote_bam_transports,
    _samtools_remote_view_cmd,
    remote_bam_url_for_samtools,
    remote_hg002_bam_index_path,
)


def test_remote_bam_index_path_name():
    path = remote_hg002_bam_index_path()
    assert path.name == "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"


def test_remote_bam_url_uses_ftp_for_samtools():
    url = remote_bam_url_for_samtools()
    assert url.startswith("ftp://")
    assert url == ASSETS["bam_remote_ftp"]
    assert ASSETS["bam_remote"].startswith("https://")


def test_samtools_remote_view_cmd_uses_ftp_without_index_option():
    ftp = ASSETS["bam_remote_ftp"]
    cmd = _samtools_remote_view_cmd(
        remote_bam=ftp,
        region="chr22:22358161-27358161",
        dest=Path("/out/slice.bam"),
        samtools="samtools",
    )
    assert cmd == [
        "samtools",
        "view",
        "-b",
        "-o",
        "/out/slice.bam",
        ftp,
        "chr22:22358161-27358161",
    ]
    assert "--input-fmt-option" not in cmd


def test_remote_bam_transports_prefers_ftp_then_https():
    transports = _remote_bam_transports()
    assert len(transports) == 2
    assert transports[0] == (ASSETS["bam_remote_ftp"], "ftp")
    assert transports[1] == (ASSETS["bam_remote"], "https")


def test_docker_local_view_uses_samtools_entrypoint():
    cmd = _build_docker_samtools_cmd(
        [
            "view",
            "-b",
            "/data/HG002_chr22_slice.bam",
            "chr22:22358161-27358161",
            "-o",
            "/out/slice.bam",
        ],
        volumes=[
            ("/datasets/giab/bam", "/data", "ro"),
            ("/datasets/giab/bam", "/out", "rw"),
        ],
        network_host=False,
    )
    assert cmd[0] == "docker"
    assert "--entrypoint" in cmd
    entry_idx = cmd.index("--entrypoint")
    assert cmd[entry_idx + 1] == "samtools"
    assert _SAMTOOLS_DOCKER_IMAGE in cmd
    assert "sh" not in cmd
