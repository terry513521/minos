"""Tests for bundled vendor GIAB bridge wiring."""

from __future__ import annotations

from app.benchmark.giab.tuning_bridge import ensure_tuning_giab, get_tuning_root
from app.paths import get_vendor_root


def test_get_tuning_root_uses_bundled_vendor() -> None:
    root = get_tuning_root()
    assert root == get_vendor_root()
    assert (root / "tuning" / "giab" / "data.py").is_file()


def test_ensure_tuning_giab_maps_worker_dataset_paths() -> None:
    ensure_tuning_giab()
    import tuning.giab.paths as tuning_paths
    from app.benchmark.giab.paths import giab_bam_dir, giab_data_dir, giab_vcf_dir

    assert tuning_paths.GIAB_BAM_DIR == giab_bam_dir()
    assert tuning_paths.GIAB_DATA_DIR == giab_data_dir()
    assert tuning_paths.GIAB_VCF_DIR == giab_vcf_dir()


def test_data_layer_reexports_tuning_samtools_helpers() -> None:
    from app.benchmark.giab.data import _samtools_bin, repair_giab_bam_indexes

    assert callable(_samtools_bin)
    assert callable(repair_giab_bam_indexes)
