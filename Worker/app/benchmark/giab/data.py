"""Download and cache GIAB HG002 assets under Worker/datasets/giab/."""

from __future__ import annotations

import fcntl
import logging
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from app.benchmark.giab.paths import (
    MINOS_GIAB_REGIONS,
    giab_bam_dir,
    giab_data_dir,
    reference_dir,
)
from app.core.repo import ensure_repo_imports

logger = logging.getLogger(__name__)

GIAB_BASE = "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab"

ASSETS = {
    "truth_vcf": (
        f"{GIAB_BASE}/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/"
        "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
    ),
    "truth_vcf_tbi": (
        f"{GIAB_BASE}/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/"
        "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz.tbi"
    ),
    "truth_bed": (
        f"{GIAB_BASE}/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/"
        "HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"
    ),
    "bam_remote": (
        f"{GIAB_BASE}/data/AshkenazimTrio/HG002_NA24385_son/Element_AVITI_20240920/"
        "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam"
    ),
    "bam_remote_bai": (
        f"{GIAB_BASE}/data/AshkenazimTrio/HG002_NA24385_son/Element_AVITI_20240920/"
        "HG002_Element-StdInsert_80x_GRCh38-GIABv3.bam.bai"
    ),
}

_SAMTOOLS_DOCKER_IMAGE = "quay.io/biocontainers/samtools:1.20--h50ea8bc_0"
_INDEX_FMT_OPTION_KEYS = ("index", "load_index")
_USER_AGENT = "minos-worker-giab/1.0 (+https://github.com/minos-protocol/minos_subnet)"

REF_S3_BASE = "https://api.theminos.ai/reference"

_SDF_FILES = (
    "done",
    "mainIndex",
    "nameIndex0",
    "namedata0",
    "namepointer0",
    "progress",
    "seqdata0",
    "seqpointer0",
    "sequenceIndex0",
    "summary.txt",
)


def remote_hg002_bam_index_path() -> Path:
    """Local cache for the HG002 whole-genome BAM index (required for FTP/HTTP slices)."""
    return giab_data_dir() / f"{Path(ASSETS['bam_remote']).name}.bai"


def ensure_remote_bam_index() -> Path:
    """Download HG002 .bai once; samtools needs it for random access on the remote BAM."""
    dest = remote_hg002_bam_index_path()
    _download(ASSETS["bam_remote_bai"], dest)
    return dest


def _samtools_remote_view_cmd(
    *,
    remote_bam: str,
    local_bai: Path,
    region: str,
    dest: Path,
    samtools: str,
    index_option_key: str,
) -> list[str]:
    """Build samtools view args with a locally cached .bai for a remote BAM."""
    return [
        samtools,
        "view",
        "-b",
        "-o",
        str(dest),
        "--input-fmt-option",
        f"{index_option_key}={local_bai}",
        remote_bam,
        region,
    ]


def _docker_samtools_remote_view_script(
    *,
    remote_bam: str,
    local_bai: Path,
    region: str,
    dest_name: str,
) -> str:
    index_in_container = f"/idx/{local_bai.name}"
    option_attempts = " ".join(
        f'if samtools view -b -o "/out/{dest_name}" '
        f'--input-fmt-option {key}={index_in_container} '
        f'"{remote_bam}" {region} 2>/dev/null; then '
        f'samtools index "/out/{dest_name}"; exit 0; fi;'
        for key in _INDEX_FMT_OPTION_KEYS
    )
    return (
        f"{option_attempts} "
        f'samtools view -b -o "/out/{dest_name}" "{remote_bam}" {region} '
        f'&& samtools index "/out/{dest_name}"'
    )


def _run_samtools_remote_view(
    *,
    remote_bam: str,
    local_bai: Path,
    region: str,
    dest: Path,
    samtools: str,
) -> None:
    last_error: str | None = None
    for index_option_key in _INDEX_FMT_OPTION_KEYS:
        cmd = _samtools_remote_view_cmd(
            remote_bam=remote_bam,
            local_bai=local_bai,
            region=region,
            dest=dest,
            samtools=samtools,
            index_option_key=index_option_key,
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            _run_checked([samtools, "index", str(dest)], label="samtools index")
            logger.info(
                "samtools regional extract: %s → %s (index %s via %s)",
                region,
                dest.name,
                local_bai.name,
                index_option_key,
            )
            return
        last_error = (result.stderr or result.stdout or "").strip()

    raise RuntimeError(
        f"samtools remote view failed for {region}: {(last_error or 'unknown error')[:800]}"
    )


def _local_name(key: str) -> str:
    return Path(ASSETS[key]).name


def asset_path(key: str) -> Path:
    if key.startswith("bam_region_"):
        chrom = key.replace("bam_region_", "")
        return giab_bam_dir() / f"HG002_{chrom}_minos_window.bam"
    return giab_data_dir() / _local_name(key)


def regional_bam_cache_path(region: str) -> Path:
    """Cached HG002 slice for an arbitrary Minos-style region string."""
    slug = region.replace(":", "_")
    return giab_bam_dir() / f"HG002_{slug}.bam"


def parse_region_bounds(region: str) -> Tuple[str, int, int]:
    """Parse ``chr20:1-1000000`` → (chrom, start, end)."""
    chrom, rest = (region or "").split(":", 1)
    chrom = chrom.strip()
    if not chrom or "-" not in rest:
        raise ValueError(f"invalid region: {region!r}")
    start_s, end_s = rest.split("-", 1)
    start, end = int(start_s), int(end_s)
    if end <= start:
        raise ValueError(f"invalid region bounds: {region!r}")
    return chrom, start, end


def shrink_region(region: str, max_bp: int) -> str:
    """Return the first *max_bp* of *region* (for faster local GIAB smoke tests)."""
    if max_bp <= 0:
        return region
    chrom, start, end = parse_region_bounds(region)
    width = end - start
    if width <= max_bp:
        return region
    return f"{chrom}:{start}-{start + max_bp}"


def _bam_path_region_bounds(path: Path) -> Optional[Tuple[str, int, int]]:
    """Parse ``HG002_chr20_35774944-40774944.bam`` bounds."""
    stem = path.name
    if not stem.startswith("HG002_") or not stem.endswith(".bam"):
        return None
    slug = stem[len("HG002_") : -len(".bam")]
    if "_" not in slug:
        return None
    chrom, coords = slug.split("_", 1)
    if "-" not in coords:
        return None
    try:
        start_s, end_s = coords.split("-", 1)
        return chrom, int(start_s), int(end_s)
    except ValueError:
        return None


def containing_cached_bam(region: str) -> Optional[Path]:
    """Smallest cached BAM that fully contains *region*, if any."""
    try:
        chrom, need_start, need_end = parse_region_bounds(region)
    except ValueError:
        return None
    bam_dir = giab_bam_dir()
    if not bam_dir.exists():
        return None

    best: Optional[Path] = None
    best_width: Optional[int] = None
    for path in bam_dir.glob("HG002_*.bam"):
        bounds = _bam_path_region_bounds(path)
        if not bounds:
            continue
        b_chrom, b_start, b_end = bounds
        if b_chrom != chrom or b_start > need_start or b_end < need_end:
            continue
        if not Path(f"{path}.bai").exists():
            continue
        width = b_end - b_start
        if best is None or (best_width is not None and width < best_width):
            best = path
            best_width = width
    return best


def chrom_from_region(region: str) -> str:
    chrom = (region or "").split(":", 1)[0].strip()
    if not chrom:
        raise ValueError(f"invalid region: {region!r}")
    return chrom


def _samtools_view_local_bam(src: Path, region: str, dest: Path) -> None:
    """Extract *region* from a local indexed BAM (fast vs remote FTP)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    samtools = _samtools_bin()

    if samtools:
        cmd = [samtools, "view", "-b", str(src), region, "-o", str(dest)]
        logger.info("samtools local slice: %s from %s", region, src.name)
        _run_checked(cmd, label="samtools view (local)")
        _run_checked([samtools, "index", str(dest)], label="samtools index (local)")
        return

    inner = (
        f"samtools view -b /data/{src.name} {region} -o /out/{dest.name} "
        f"&& samtools index /out/{dest.name}"
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{src.parent}:/data:ro",
        f"-v{dest.parent}:/out",
        _SAMTOOLS_DOCKER_IMAGE,
        "sh",
        "-c",
        inner,
    ]
    logger.info("docker samtools local slice: %s from %s", region, src.name)
    _run_checked(cmd, label="docker samtools view (local)")


def ensure_bam_for_region(region: str) -> Path:
    """Cache HG002 BAM slice for the given region (exact coordinates)."""
    dest = regional_bam_cache_path(region)
    if dest.exists() and Path(f"{dest}.bai").exists():
        return dest
    parent = containing_cached_bam(region)
    if parent:
        try:
            _samtools_view_local_bam(parent, region, dest)
            return dest
        except Exception as exc:
            logger.warning(
                "Local BAM slice from %s failed (%s); falling back to remote extract",
                parent.name,
                exc,
            )
    _samtools_view_region(region, dest)
    return dest


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    logger.info("Downloading %s → %s", url, dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response:
        with tmp.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    tmp.rename(dest)


def ensure_truth_assets() -> Tuple[Path, Path]:
    """Download truth VCF + confident BED if missing."""
    vcf = asset_path("truth_vcf")
    tbi = asset_path("truth_vcf_tbi")
    bed = asset_path("truth_bed")
    _download(ASSETS["truth_vcf"], vcf)
    _download(ASSETS["truth_vcf_tbi"], tbi)
    _download(ASSETS["truth_bed"], bed)
    return vcf, bed


def _samtools_bin() -> Optional[str]:
    if shutil.which("samtools"):
        return "samtools"
    return None


def _run_checked(cmd: list[str], *, label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {detail[:800]}")


def _samtools_view_region(region: str, dest: Path) -> None:
    """Extract a genomic window from remote indexed HG002 BAM via samtools."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    remote = ASSETS["bam_remote"]
    local_bai = ensure_remote_bam_index()

    samtools = _samtools_bin()
    if samtools:
        _run_samtools_remote_view(
            remote_bam=remote,
            local_bai=local_bai,
            region=region,
            dest=dest,
            samtools=samtools,
        )
        return

    inner = _docker_samtools_remote_view_script(
        remote_bam=remote,
        local_bai=local_bai,
        region=region,
        dest_name=dest.name,
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network=host",
        "-v",
        "/etc/ssl/certs:/etc/ssl/certs:ro",
        "-e",
        "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
        f"-v{local_bai.parent}:/idx:ro",
        f"-v{dest.parent}:/out",
        _SAMTOOLS_DOCKER_IMAGE,
        "sh",
        "-c",
        inner,
    ]
    logger.info(
        "docker samtools regional extract: %s (index %s)",
        region,
        local_bai.name,
    )
    _run_checked(cmd, label="docker samtools regional extract")


def ensure_regional_bam(chrom: str, region: str) -> Path:
    """Cache HG002 BAM slice for a Minos-like window."""
    dest = asset_path(f"bam_region_{chrom}")
    if dest.exists() and Path(f"{dest}.bai").exists():
        return dest
    _samtools_view_region(region, dest)
    return dest


def ensure_sdf(chrom: str) -> Path:
    """Ensure RTG SDF exists for hap.py (builds locally if needed)."""
    ref_dir = reference_dir(chrom)
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
                _build_sdf_with_rtg(fasta, sdf_dir)
                return sdf_dir

            sdf_dir.mkdir(parents=True, exist_ok=True)
            for fname in _SDF_FILES:
                dest = sdf_dir / fname
                if dest.exists() and dest.stat().st_size > 0:
                    continue
                url = f"{REF_S3_BASE}/{chrom}/{chrom}.sdf/{fname}"
                try:
                    _download(url, dest)
                except Exception as exc:
                    logger.warning("SDF download failed for %s (%s), building locally", chrom, exc)
                    if fasta.exists():
                        _build_sdf_with_rtg(fasta, sdf_dir)
                    break
            return sdf_dir
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _build_sdf_with_rtg(fasta: Path, sdf_dir: Path) -> None:
    if sdf_dir.exists():
        shutil.rmtree(sdf_dir)
    chrom_dir = fasta.parent
    ensure_repo_imports()
    from base.genomics_config import GENOMICS_CONFIG

    image = GENOMICS_CONFIG["happy_docker_image"]
    cmd = [
        "docker",
        "run",
        "--rm",
        f"-v{chrom_dir}:/data",
        "--entrypoint",
        "/opt/rtg-tools-3.12.1/rtg",
        image,
        "format",
        "-o",
        f"/data/{sdf_dir.name}",
        f"/data/{fasta.name}",
    ]
    logger.info("Building RTG SDF for %s", fasta.name)
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def reference_for_chrom(chrom: str) -> Path:
    ref = reference_dir(chrom) / f"{chrom}.fa"
    if not ref.exists():
        raise FileNotFoundError(f"Reference not found: {ref}")
    return ref


def prepare_all(regions: Tuple[Tuple[str, str], ...] = MINOS_GIAB_REGIONS) -> dict:
    """Ensure truth + regional BAMs exist."""
    truth_vcf, truth_bed = ensure_truth_assets()
    bams = {}
    for chrom, region in regions:
        bams[chrom] = ensure_regional_bam(chrom, region)
    return {"truth_vcf": truth_vcf, "truth_bed": truth_bed, "bams": bams}
