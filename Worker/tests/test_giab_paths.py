from app.benchmark.giab.paths import MINOS_REGION_BY_CHROM, minos_region_for_chrom


def test_minos_region_chr22():
    assert minos_region_for_chrom("chr22") == "chr22:35444092-40444092"


def test_minos_region_by_chrom_includes_chr22():
    assert "chr22" in MINOS_REGION_BY_CHROM


def test_chr22_bam_slug():
    region = minos_region_for_chrom("chr22")
    assert region is not None
    assert region.replace(":", "_") == "chr22_35444092-40444092"
