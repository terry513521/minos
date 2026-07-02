#!/usr/bin/env python3
"""List worker benchmark datasets, sizes, and missing files."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from app.assets import resolve_benchmark_bam, resolve_truth_vcf
from app.config import Settings

DATA_DIR = ROOT / os.getenv("WORKER_DATA_DIR", "datasets")
MANIFEST = DATA_DIR / "manifest.json"


def human_size(num_bytes: int) -> str:
    num = float(max(0, num_bytes))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if num < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(num)} {unit}"
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{int(num_bytes)} B"


def parse_chromosomes(raw: str) -> list[str]:
    return [c.strip() for c in (raw or "chr20,chr21").split(",") if c.strip()]


def _bam_ok(chrom: str, settings: Settings) -> tuple[bool, Path | None]:
    path = resolve_benchmark_bam(chrom, settings)
    if path.exists() and path.stat().st_size > 0:
        index = path.parent / f"{path.name}.bai"
        if index.exists():
            return True, path
    bams_dir = DATA_DIR / "bams"
    if bams_dir.is_dir():
        for candidate in sorted(bams_dir.glob(f"HG002_{chrom}_*.bam")):
            index = candidate.parent / f"{candidate.name}.bai"
            if candidate.stat().st_size > 0 and index.exists():
                return True, candidate
    return False, None


def _truth_ok(chrom: str, settings: Settings) -> tuple[bool, Path | None]:
    path = resolve_truth_vcf(chrom, settings)
    return path is not None, path


def main() -> int:
    settings = Settings()
    chromosomes = parse_chromosomes(os.getenv("WORKER_CHROMOSOMES", "chr20,chr21"))
    print(f"Worker datasets root: {DATA_DIR.relative_to(ROOT)}/")
    print(f"Chromosomes: {', '.join(chromosomes)}")
    print(
        f"Mode: {'benchmark (fixed BAM + GIAB truth; region from job only)' if settings.benchmark_mode else 'platform BAM'}"
    )
    if settings.benchmark_mode:
        print(f"Benchmark truth: {settings.benchmark_truth_vcf}\n")
    else:
        print()

    total = 0
    missing_bams: list[str] = []
    missing_truth: list[str] = []
    exit_code = 0

    for chrom in chromosomes:
        print(f"[{chrom}]")
        bam_ok, bam_path = _bam_ok(chrom, settings)
        truth_ok, truth_path = _truth_ok(chrom, settings)
        paths = [
            DATA_DIR / "reference" / chrom / f"{chrom}.fa",
            DATA_DIR / "reference" / chrom / f"{chrom}.fa.fai",
            DATA_DIR / "reference" / chrom / f"{chrom}.dict",
            DATA_DIR / "reference" / chrom / f"{chrom}.sdf",
        ]
        for path in paths:
            if not path.exists():
                print(f"  --  {path.relative_to(ROOT)}  (missing)")
                continue
            size = path.stat().st_size if path.is_file() else sum(
                f.stat().st_size for f in path.rglob("*") if f.is_file()
            )
            total += size
            print(f"  OK  {path.relative_to(ROOT)}  ({human_size(size)})")

        if bam_ok and bam_path is not None:
            size = bam_path.stat().st_size
            total += size
            print(f"  OK  {bam_path.relative_to(ROOT)}  ({human_size(size)})  [benchmark BAM]")
            index = bam_path.parent / f"{bam_path.name}.bai"
            if index.exists():
                total += index.stat().st_size
        else:
            print(f"  --  datasets/bams/{chrom}.bam  (missing)")
            print(f"  --  datasets/bams/HG002_{chrom}_*.bam  (missing)")
            missing_bams.append(chrom)

        if truth_ok and truth_path is not None:
            size = truth_path.stat().st_size
            total += size
            print(f"  OK  {truth_path.relative_to(ROOT)}  ({human_size(size)})  [truth]")
        else:
            print(f"  --  {settings.benchmark_truth_vcf}  (missing)")
            print(f"  --  datasets/truth/{chrom}.vcf.gz  (missing)")
            missing_truth.append(chrom)

        mutations = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
        if mutations.exists():
            size = mutations.stat().st_size
            total += size
            print(f"  OK  {mutations.relative_to(ROOT)}  ({human_size(size)})  [mutations, optional]")
        else:
            print(f"  --  {mutations.relative_to(ROOT)}  (optional)")
        print()

    print(f"Total on disk: {human_size(total)}")

    if MANIFEST.exists():
        print(f"\nPlatform manifest: {MANIFEST.relative_to(ROOT)}")
        data = json.loads(MANIFEST.read_text())
        for row in data.get("assets", []):
            chrom = row.get("chromosome")
            size = row.get("bam_size_human")
            source = row.get("source")
            print(f"  {chrom}: {size or '?'} ({source or 'unknown'})")

    if missing_bams:
        exit_code = 1
        print(
            "\nMissing benchmark BAM(s) for: "
            + ", ".join(sorted(set(missing_bams)))
            + ".\n"
            "  Need datasets/bams/{chrom}.bam, HG002_{chrom}_minos_window.bam, "
            "or HG002_{chrom}_<start>-<end>.bam with matching .bai."
        )

    if missing_truth:
        exit_code = 1
        print(
            "\nMissing truth for: "
            + ", ".join(sorted(set(missing_truth)))
            + f".\n"
            f"  Expected GIAB file: {settings.benchmark_truth_vcf}"
        )

    if exit_code == 0:
        print("\nBenchmark datasets ready. Optimization uses job region only; platform round BAM not required.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
