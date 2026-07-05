"""Shared helpers for variant-calling templates."""
import gzip
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_VCF_READ_ERRORS = (OSError, EOFError, gzip.BadGzipFile)


def is_valid_vcf_gz(vcf_path: Path) -> bool:
    """Return True when a gzip VCF exists and has a complete gzip stream."""
    path = Path(vcf_path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if not str(path).endswith(".gz"):
        return True
    try:
        with gzip.open(path, "rb") as handle:
            while handle.read(1024 * 1024):
                pass
        return True
    except _VCF_READ_ERRORS:
        return False


def count_variants(vcf_path: Path) -> int:
    """Count non-header lines in a VCF file."""
    count = 0
    try:
        opener = gzip.open if str(vcf_path).endswith(".gz") else open
        with opener(vcf_path, "rt") as f:
            for line in f:
                if not line.startswith("#"):
                    count += 1
    except _VCF_READ_ERRORS:
        logger.warning("Failed to count variants in %s", vcf_path)
    return count
