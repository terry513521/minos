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

from app.benchmark.giab.paths import reference_dir
from app.benchmark.giab.paths import giab_bam_dir, giab_data_dir, giab_vcf_dir
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
        for path, label in (
            (truth_vcf, "GIAB truth VCF (auto-download on first run)"),
            (truth_bed, "GIAB confident BED"),
        ):
            if path.exists() and path.stat().st_size > 0:
                total += path.stat().st_size
                print(f"  OK  {path.relative_to(WORKER_ROOT)}  ({human_size(path.stat().st_size)})  [{label}]")
            else:
                print(f"  ..  {path.relative_to(WORKER_ROOT)}  (not yet — downloaded on first benchmark) [{label}]")

        bam_dir = giab_bam_dir()
        bam_count = len(list(bam_dir.glob("HG002_*.bam"))) if bam_dir.is_dir() else 0
        print(f"  ..  {bam_dir.relative_to(WORKER_ROOT)}/  ({bam_count} cached BAM slice(s))")
        print(f"  ..  {giab_vcf_dir().relative_to(WORKER_ROOT)}/  (scored VCF reuse cache)")
        print()

    print(f"Reference total (listed): {human_size(total)}")
    if exit_code == 0:
        print("\nGIAB benchmark ready. First trial may download truth/BAM slices.")
    else:
        print("\nFix missing reference under datasets/reference/{chr}/ — run Worker setup.sh")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
