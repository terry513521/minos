"""Wire Worker GIAB benchmarks to minos/tuning/giab (samtools + scoring)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.core.repo import ensure_repo_imports
from app.paths import WORKER_ROOT

_TUNING_ROOT: Optional[Path] = None
_CONFIGURED = False


def get_tuning_root() -> Path:
    """Locate the minos checkout that contains the tuning/ package."""
    global _TUNING_ROOT
    if _TUNING_ROOT is not None:
        return _TUNING_ROOT

    env_root = os.getenv("WORKER_TUNING_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).resolve()
    else:
        parent = WORKER_ROOT.parent
        candidate = parent / "minos"
        if not (candidate / "tuning" / "giab" / "data.py").exists():
            if (parent / "tuning" / "giab" / "data.py").exists():
                candidate = parent
            else:
                raise RuntimeError(
                    "Minos tuning package not found. Set WORKER_TUNING_ROOT to the "
                    "minos_subnet checkout that contains tuning/giab/ "
                    f"(tried {parent / 'minos'} and {parent})."
                )

    if not (candidate / "tuning" / "giab" / "data.py").exists():
        raise RuntimeError(
            f"tuning/giab/data.py missing under {candidate}. "
            "Set WORKER_TUNING_ROOT to a full minos_subnet tree."
        )

    _TUNING_ROOT = candidate
    return _TUNING_ROOT


def ensure_tuning_giab() -> Path:
    """Import tuning.giab with Worker dataset paths and reference layout."""
    global _CONFIGURED

    tuning_root = get_tuning_root()
    tuning_str = str(tuning_root)
    if tuning_str not in sys.path:
        sys.path.insert(0, tuning_str)

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

    # Patch paths before loading data — data binds GIAB_*_DIR at import time.
    import importlib
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

    # Keep module-level aliases in sync (asset_path, locks, etc.).
    tuning_data.GIAB_BAM_DIR = tuning_paths.GIAB_BAM_DIR
    tuning_data.GIAB_DATA_DIR = tuning_paths.GIAB_DATA_DIR

    get_settings()
    _CONFIGURED = True
    return tuning_root
