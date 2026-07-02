from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings

WINDOW_RE = re.compile(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$", re.IGNORECASE)
BAM_REGION_RE = re.compile(
    r"^HG002_(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M))_(\d+)-(\d+)\.bam$",
    re.IGNORECASE,
)

WORKER_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BenchmarkAssets:
    window: str
    chromosome: str
    reference_fasta: Path
    reference_sdf: Path
    bam_path: Path
    truth_vcf: Path | None


def parse_window(window: str) -> tuple[str, int, int]:
    match = WINDOW_RE.match(window.strip())
    if not match:
        raise ValueError(f"Invalid window format: {window}")
    chrom = match.group(1)
    start = int(match.group(2))
    end = int(match.group(3))
    if start >= end:
        raise ValueError(f"Invalid window coordinates: {window}")
    return chrom, start, end


def _data_root(settings: Settings) -> Path:
    return WORKER_ROOT / settings.data_dir


def _bam_index_path(bam_path: Path) -> Path:
    return bam_path.parent / f"{bam_path.name}.bai"


def _parse_bam_region_from_name(name: str) -> tuple[str, int, int] | None:
    match = BAM_REGION_RE.match(name)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def _region_overlap(start: int, end: int, bstart: int, bend: int) -> int:
    return max(0, min(end, bend) - max(start, bstart))


def _find_region_bam(bams_dir: Path, chrom: str, start: int, end: int) -> Path | None:
    if not bams_dir.is_dir():
        return None

    exact = bams_dir / f"HG002_{chrom}_{start}-{end}.bam"
    if exact.exists():
        return exact

    chrom_lower = chrom.lower()
    best_path: Path | None = None
    best_overlap = -1
    for path in sorted(bams_dir.glob(f"HG002_{chrom}_*.bam")):
        parsed = _parse_bam_region_from_name(path.name)
        if not parsed:
            continue
        bchrom, bstart, bend = parsed
        if bchrom.lower() != chrom_lower:
            continue
        overlap = _region_overlap(start, end, bstart, bend)
        if overlap > best_overlap:
            best_overlap = overlap
            best_path = path

    if best_path is not None and best_overlap > 0:
        return best_path
    return None


def _list_chrom_bam_candidates(bams_dir: Path, chrom: str) -> list[str]:
    if not bams_dir.is_dir():
        return []
    names = sorted(
        p.name
        for p in bams_dir.glob(f"HG002_{chrom}_*.bam")
        if p.is_file() and p.stat().st_size > 0
    )
    canonical = bams_dir / f"{chrom}.bam"
    if canonical.exists():
        names.insert(0, canonical.name)
    return names


def resolve_benchmark_bam(
    chrom: str,
    settings: Settings,
    *,
    window: str | None = None,
) -> Path:
    """
    Resolve benchmark BAM for a chromosome.

    Lookup order:
    1. datasets/bams/{chrom}.bam
    2. Region-exact or best-overlap HG002_{chrom}_{start}-{end}.bam for job window
    3. datasets/bams/HG002_{chrom}_minos_window.bam
    4. datasets/bam/HG002_{chrom}_minos_window.bam (legacy)
    """
    data_dir = _data_root(settings)
    bams_dir = data_dir / "bams"

    canonical = bams_dir / f"{chrom}.bam"
    if canonical.exists() and canonical.stat().st_size > 0:
        return canonical

    if window:
        try:
            wchrom, start, end = parse_window(window)
            if wchrom.lower() == chrom.lower():
                region_bam = _find_region_bam(bams_dir, chrom, start, end)
                if region_bam is not None:
                    return region_bam
        except ValueError:
            pass

    for directory in (bams_dir, data_dir / "bam"):
        minos = directory / f"HG002_{chrom}_minos_window.bam"
        if minos.exists() and minos.stat().st_size > 0:
            return minos

    return canonical


def resolve_truth_vcf(chrom: str, settings: Settings) -> Path | None:
    """Per-chrom truth first, then genome-wide GIAB benchmark in datasets/data/."""
    data_dir = _data_root(settings)
    per_chrom = data_dir / "truth" / f"{chrom}.vcf.gz"
    if per_chrom.exists() and per_chrom.stat().st_size > 0:
        return per_chrom

    if settings.benchmark_mode:
        bench = data_dir / settings.benchmark_truth_vcf
        if bench.exists() and bench.stat().st_size > 0:
            return bench
    return None


def resolve_assets(window: str, settings: Settings | None = None) -> BenchmarkAssets:
    settings = settings or get_settings()
    data_dir = _data_root(settings)
    chrom, _, _ = parse_window(window)

    reference_fasta = data_dir / "reference" / chrom / f"{chrom}.fa"
    reference_sdf = data_dir / "reference" / chrom / f"{chrom}.sdf"
    bam_path = resolve_benchmark_bam(chrom, settings, window=window)
    truth_vcf = resolve_truth_vcf(chrom, settings)

    missing: list[str] = []
    if not reference_fasta.exists():
        missing.append(str(reference_fasta.relative_to(WORKER_ROOT)))
    if not bam_path.exists() or bam_path.stat().st_size == 0:
        bams_dir = data_dir / "bams"
        available = _list_chrom_bam_candidates(bams_dir, chrom)
        hint = (
            f"Place datasets/bams/{chrom}.bam, HG002_{chrom}_minos_window.bam, "
            f"or HG002_{chrom}_<start>-<end>.bam matching the job region."
        )
        if available:
            hint += f" Found for {chrom}: {', '.join(available[:5])}"
            if len(available) > 5:
                hint += f", ... ({len(available)} total)"
        missing.append(f"{bams_dir.relative_to(WORKER_ROOT)}/{chrom}.bam (no matching benchmark BAM)")
        raise FileNotFoundError("Missing benchmark assets: " + "; ".join(missing) + f". {hint}")

    if missing:
        raise FileNotFoundError("Missing benchmark assets: " + ", ".join(missing))

    return BenchmarkAssets(
        window=window.strip(),
        chromosome=chrom,
        reference_fasta=reference_fasta,
        reference_sdf=reference_sdf,
        bam_path=bam_path,
        truth_vcf=truth_vcf,
    )


def validate_benchmark_assets(window: str, settings: Settings | None = None) -> None:
    """Fail fast before starting optimization if scoring prerequisites are missing."""
    settings = settings or get_settings()
    assets = resolve_assets(window, settings)
    missing: list[str] = []

    bam_index = _bam_index_path(assets.bam_path)
    if not bam_index.exists():
        missing.append(str(bam_index.relative_to(WORKER_ROOT)))

    ref_index = assets.reference_fasta.parent / f"{assets.reference_fasta.name}.fai"
    if not ref_index.exists():
        missing.append(str(ref_index.relative_to(WORKER_ROOT)))

    if assets.truth_vcf is None:
        if settings.benchmark_mode:
            bench = _data_root(settings) / settings.benchmark_truth_vcf
            missing.append(
                f"{bench.relative_to(WORKER_ROOT)} "
                f"(or datasets/truth/{assets.chromosome}.vcf.gz)"
            )
        else:
            missing.append(f"datasets/truth/{assets.chromosome}.vcf.gz")

    if not assets.reference_sdf.exists():
        missing.append(f"datasets/reference/{assets.chromosome}/{assets.chromosome}.sdf")

    if missing:
        mode = "benchmark GIAB truth" if settings.benchmark_mode else "truth VCF"
        raise FileNotFoundError(
            "Benchmark not ready for local scoring: "
            + ", ".join(missing)
            + f". Ensure reference SDF and {mode} are present."
        )
