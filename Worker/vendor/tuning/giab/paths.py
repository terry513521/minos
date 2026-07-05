"""Private paths for GIAB calibration (isolated from mining)."""

from __future__ import annotations

from pathlib import Path

TUNING_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = TUNING_DIR.parent

# Miner reads this — NEVER write here from GIAB tooling.
MINING_GATK_CONF = ROOT_DIR / "configs" / "gatk.conf"

PRIVATE_DIR = TUNING_DIR / "private"
GIAB_DIR = PRIVATE_DIR / "giab"
GIAB_DATA_DIR = GIAB_DIR / "data"
GIAB_BAM_DIR = GIAB_DIR / "bam"
GIAB_VCF_DIR = GIAB_DIR / "vcf"
GIAB_RESULTS_DIR = GIAB_DIR / "results"

GIAB_BASELINE_CONF = PRIVATE_DIR / "giab_baseline.conf"
GIAB_GT_BASELINE_CONF = PRIVATE_DIR / "giab_gt_baseline.conf"
GIAB_CALIBRATION_JSON = PRIVATE_DIR / "giab_calibration.json"
GIAB_GT_CALIBRATION_JSON = PRIVATE_DIR / "giab_gt_calibration.json"
GIAB_README = PRIVATE_DIR / "README.md"

# Minos-like 5 Mb windows (from recent round history).
MINOS_GIAB_REGIONS = (
    ("chr20", "chr20:39669962-44669962"),
    ("chr21", "chr21:35444092-40444092"),
)
