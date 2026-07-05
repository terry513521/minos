#!/usr/bin/env python3
"""List GIAB benchmark prerequisites under Worker/datasets/."""

from __future__ import annotations

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

from app.benchmark.giab.paths import reference_dir, giab_data_dir, giab_vcf_dir, minos_region_for_chrom
from app.benchmark.giab.data import regional_bam_cache_path
from app.config import Settings
from app.paths import WORKER_ROOT, data_root


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


def main() -> int:
    settings = Settings()
    chromosomes = parse_chromosomes(os.getenv("WORKER_CHROMOSOMES", settings.chromosomes))
    datasets = data_root(settings.data_dir)

    print("Benchmark: GIAB (self-contained under Worker/datasets/)")
    print(f"Worker root:   {WORKER_ROOT}")
    print(f"Datasets:      {datasets.relative_to(WORKER_ROOT)}/")
    print(f"Chromosomes:   {', '.join(chromosomes)}\n")

    exit_code = 0
    total = 0

    for chrom in chromosomes:
        print(f"[{chrom}]")
        ref = reference_dir(chrom) / f"{chrom}.fa"
        ref_fai = ref.parent / f"{ref.name}.fai"
        sdf = ref.parent / f"{chrom}.sdf"
        for path, label in (
            (ref, "reference FASTA"),
            (ref_fai, "reference index"),
            (sdf, "reference SDF (hap.py)"),
        ):
            if path.exists():
                size = path.stat().st_size if path.is_file() else sum(
                    f.stat().st_size for f in path.rglob("*") if f.is_file()
                )
                total += size
                print(f"  OK  {path.relative_to(WORKER_ROOT)}  ({human_size(size)})  [{label}]")
            else:
                print(f"  --  {path.relative_to(WORKER_ROOT)}  (missing) [{label}]")
                exit_code = 1

        truth_vcf = giab_data_dir() / "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
        truth_bed = giab_data_dir() / "HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"
        remote_bai = giab_data_dir() / "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"
        for path, label in (
            (truth_vcf, "GIAB truth VCF"),
            (truth_bed, "GIAB confident BED"),
            (remote_bai, "HG002 BAM index (NCBI FTP)"),
        ):
            if path.exists() and path.stat().st_size > 0:
                total += path.stat().st_size
                print(f"  OK  {path.relative_to(WORKER_ROOT)}  ({human_size(path.stat().st_size)})  [{label}]")
            elif label.endswith("BAM index"):
                print(
                    f"  ..  {path.relative_to(WORKER_ROOT)}  "
                    f"(not yet — downloaded before first regional slice) [{label}]"
                )
            else:
                print(
                    f"  ..  {path.relative_to(WORKER_ROOT)}  "
                    f"(not yet — downloaded on first benchmark) [{label}]"
                )

        bam_dir = giab_data_dir().parent / "bam"
        region = minos_region_for_chrom(chrom)
        expected_bam = regional_bam_cache_path(region) if region else None
        if expected_bam and expected_bam.exists() and expected_bam.stat().st_size > 0:
            bai = Path(f"{expected_bam}.bai")
            total += expected_bam.stat().st_size
            label = f"GIAB HG002 slice ({region})"
            if bai.exists():
                total += bai.stat().st_size
                print(
                    f"  OK  {expected_bam.relative_to(WORKER_ROOT)}  "
                    f"({human_size(expected_bam.stat().st_size)})  [{label}]"
                )
            else:
                print(
                    f"  --  {expected_bam.relative_to(WORKER_ROOT)}  "
                    f"(missing .bai) [{label}]"
                )
                exit_code = 1
        else:
            bam_count = len(list(bam_dir.glob("HG002_*.bam"))) if bam_dir.is_dir() else 0
            if region:
                print(
                    f"  --  datasets/giab/bam/HG002_{chrom}_*.bam  "
                    f"(missing — run setup_assets.py to slice from NCBI FTP) "
                    f"[expected {region}]"
                )
                exit_code = 1
            else:
                print(f"  ..  {bam_dir.relative_to(WORKER_ROOT)}/  ({bam_count} cached BAM slice(s))")
        print(f"  ..  {giab_vcf_dir().relative_to(WORKER_ROOT)}/  (scored VCF reuse cache)")
        print()

    print(f"Reference total (listed): {human_size(total)}")
    if exit_code == 0:
        print("\nGIAB benchmark ready under datasets/giab/.")
    else:
        print(
            "\nFix missing files — from Worker/ run:\n"
            "  python scripts/setup_assets.py\n"
            "GIAB BAMs are sliced from https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
