"""Wire Worker GIAB benchmarks to bundled vendor/tuning/giab."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.core.repo import ensure_repo_imports
from app.paths import get_vendor_root

_CONFIGURED = False


def get_tuning_root() -> Path:
    """Root directory containing the bundled tuning/ package."""
    root = get_vendor_root()
    if not (root / "tuning" / "giab" / "data.py").is_file():
        raise RuntimeError(
            f"Bundled tuning.giab missing under {root}. "
            "Worker vendor bundle may be incomplete."
        )
    return root


def ensure_tuning_giab() -> Path:
    """Import tuning.giab with Worker dataset paths and reference layout."""
    global _CONFIGURED

    tuning_root = get_tuning_root()
    ensure_repo_imports()

    from app.benchmark.giab import paths as worker_paths
    import tuning.giab.paths as tuning_paths

    giab_root = worker_paths.giab_root()
    tuning_paths.GIAB_DIR = giab_root
    tuning_paths.GIAB_DATA_DIR = worker_paths.giab_data_dir()
    tuning_paths.GIAB_BAM_DIR = worker_paths.giab_bam_dir()
    tuning_paths.GIAB_VCF_DIR = worker_paths.giab_vcf_dir()
    tuning_paths.GIAB_RESULTS_DIR = giab_root / "results"
    tuning_paths.MINOS_GIAB_REGIONS = worker_paths.MINOS_GIAB_REGIONS

    import tuning.giab.data as tuning_data

    tuning_data = importlib.reload(tuning_data)

    import tuning.giab.scoring_assets as scoring_assets

    scoring_assets = importlib.reload(scoring_assets)
    scoring_assets.REGION_CACHE_DIR = worker_paths.giab_data_dir() / "region_cache"

    def _worker_reference_for_chrom(chrom: str) -> Path:
        ref = worker_paths.reference_dir(chrom) / f"{chrom}.fa"
        if not ref.exists():
            raise FileNotFoundError(f"Reference not found: {ref}")
        return ref

    tuning_data.reference_for_chrom = _worker_reference_for_chrom  # type: ignore[assignment]

    def _patched_ensure_sdf(chrom: str) -> Path:
        import fcntl

        ref_dir = worker_paths.reference_dir(chrom)
        sdf_dir = ref_dir / f"{chrom}.sdf"
        fasta = ref_dir / f"{chrom}.fa"
        if sdf_dir.exists() and (sdf_dir / "seqdata0").exists():
            return sdf_dir

        lock_path = ref_dir / f".{chrom}.sdf.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                if sdf_dir.exists() and (sdf_dir / "seqdata0").exists():
                    return sdf_dir
                if sdf_dir.exists() and not any(sdf_dir.iterdir()):
                    sdf_dir.rmdir()
                if fasta.exists():
                    tuning_data._build_sdf_with_rtg(fasta, sdf_dir)
                    return sdf_dir
                sdf_dir.mkdir(parents=True, exist_ok=True)
                for fname in tuning_data._SDF_FILES:
                    dest = sdf_dir / fname
                    if dest.exists() and dest.stat().st_size > 0:
                        continue
                    url = f"{tuning_data.REF_S3_BASE}/{chrom}/{chrom}.sdf/{fname}"
                    try:
                        tuning_data._download(url, dest)
                    except Exception as exc:
                        tuning_data.logger.warning(
                            "SDF download failed for %s (%s), building locally",
                            chrom,
                            exc,
                        )
                        if fasta.exists():
                            tuning_data._build_sdf_with_rtg(fasta, sdf_dir)
                        break
                return sdf_dir
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    tuning_data.ensure_sdf = _patched_ensure_sdf  # type: ignore[assignment]
    tuning_data.GIAB_BAM_DIR = tuning_paths.GIAB_BAM_DIR
    tuning_data.GIAB_DATA_DIR = tuning_paths.GIAB_DATA_DIR

    get_settings()
    _CONFIGURED = True
    return tuning_root
