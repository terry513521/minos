from pathlib import Path

import pytest

from app.assets import resolve_benchmark_bam, resolve_assets
from app.config import Settings


@pytest.fixture
def worker_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("app.assets.WORKER_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def settings() -> Settings:
    return Settings(
        data_dir="datasets",
        benchmark_mode=True,
        benchmark_truth_vcf="data/truth.vcf.gz",
    )


def test_resolve_benchmark_bam_region_exact(worker_root: Path, settings: Settings):
    bams = worker_root / "datasets" / "bams"
    bams.mkdir(parents=True)
    region_bam = bams / "HG002_chr21_24742108-29742108.bam"
    region_bam.write_bytes(b"x")

    resolved = resolve_benchmark_bam(
        "chr21",
        settings,
        window="chr21:24742108-29742108",
    )
    assert resolved == region_bam


def test_resolve_benchmark_bam_best_overlap(worker_root: Path, settings: Settings):
    bams = worker_root / "datasets" / "bams"
    bams.mkdir(parents=True)
    (bams / "HG002_chr21_10000000-20000000.bam").write_bytes(b"a")
    target = bams / "HG002_chr21_24742108-29742108.bam"
    target.write_bytes(b"b")

    resolved = resolve_benchmark_bam(
        "chr21",
        settings,
        window="chr21:25000000-26000000",
    )
    assert resolved == target


def test_resolve_benchmark_bam_minos_window_fallback(worker_root: Path, settings: Settings):
    root = worker_root / "datasets"
    bams = root / "bams"
    bams.mkdir(parents=True)
    minos = bams / "HG002_chr21_minos_window.bam"
    minos.write_bytes(b"x")
    (bams / f"{minos.name}.bai").write_bytes(b"i")

    (root / "reference" / "chr21").mkdir(parents=True)
    (root / "reference" / "chr21" / "chr21.fa").write_text(">chr21\n")
    (root / "reference" / "chr21" / "chr21.fa.fai").write_text("x")
    (root / "reference" / "chr21" / "chr21.sdf").mkdir()
    (root / "data").mkdir()
    (root / "data" / "truth.vcf.gz").write_bytes(b"t")

    assets = resolve_assets("chr21:10000000-15000000", settings)
    assert assets.bam_path == minos
