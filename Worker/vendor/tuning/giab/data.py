"""Download and cache GIAB HG002 assets under tuning/private/giab/."""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import subprocess
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from tuning.giab.paths import GIAB_BAM_DIR, GIAB_DATA_DIR, MINOS_GIAB_REGIONS

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
}


def _local_name(key: str) -> str:
    return Path(ASSETS[key]).name


def asset_path(key: str) -> Path:
    if key.startswith("bam_region_"):
        chrom = key.replace("bam_region_", "")
        return GIAB_BAM_DIR / f"HG002_{chrom}_minos_window.bam"
    return GIAB_DATA_DIR / _local_name(key)


def regional_bam_cache_path(region: str) -> Path:
    """Cached HG002 slice for an arbitrary Minos-style region string."""
    slug = region.replace(":", "_")
    return GIAB_BAM_DIR / f"HG002_{slug}.bam"


def bam_index_path(bam: Path) -> Path:
    return Path(f"{bam}.bai")


def bam_cache_ready(bam: Path) -> bool:
    """True when a cached regional BAM and its index both exist."""
    return bam.is_file() and bam_index_path(bam).is_file()


def bam_cache_ready_for_region(region: str) -> bool:
    return regional_bam_valid(regional_bam_cache_path(region), region)


def _bam_has_valid_header(bam: Path) -> Optional[bool]:
    """True/False when readable; None if the file could not be opened."""
    try:
        with bam.open("rb") as handle:
            head = handle.read(4)
    except OSError:
        return None
    if head == b"BAM\x01":
        return True
    # Production BAMs are BGZF-compressed (gzip wrapper).
    if len(head) >= 2 and head[:2] == b"\x1f\x8b":
        return True
    return False


def _docker_user_args() -> List[str]:
    """Write BAM outputs as the current user (avoid root-owned cache files)."""
    if os.name != "posix":
        return []
    return ["-u", f"{os.getuid()}:{os.getgid()}"]


def regional_bam_valid(bam: Path, region: str, *, require_index: bool = True) -> bool:
    """True when BAM looks complete; optionally require .bai (set False pre-index)."""
    if not bam.is_file():
        return False
    size = bam.stat().st_size
    if size == 0:
        logger.warning("Regional BAM empty: %s", bam.name)
        return False
    if size >= 4:
        header_ok = _bam_has_valid_header(bam)
        if header_ok is False:
            logger.warning("Regional BAM is not valid BAM format: %s", bam.name)
            return False
        if header_ok is None:
            logger.warning("Regional BAM unreadable (skipping validation): %s", bam.name)
            return False
    if require_index and not bam_index_path(bam).is_file():
        return False
    try:
        _, start, end = parse_region_bounds(region)
    except ValueError:
        return True
    width = end - start
    if width <= 0:
        return False
    size = bam.stat().st_size
    # HG002 ~80x GRCh38: healthy slices are ~38–45 bytes/bp; truncated FTP pulls dip below ~32.
    min_bytes = max(8_000_000, int(width * 32))
    if size < min_bytes:
        logger.warning(
            "Regional BAM undersized for %s: %s (%d bytes, expected >= %d)",
            region,
            bam.name,
            size,
            min_bytes,
        )
        return False
    return True


def _remove_regional_bam(bam: Path) -> None:
    bam.unlink(missing_ok=True)
    bam_index_path(bam).unlink(missing_ok=True)
    part = bam.with_suffix(bam.suffix + ".part")
    part.unlink(missing_ok=True)


def _regional_bam_corrupt(bam: Path, region: str) -> bool:
    """True when a cached BAM is clearly broken and should be deleted."""
    if not bam.is_file():
        return False
    size = bam.stat().st_size
    if size == 0:
        return True
    header_ok = _bam_has_valid_header(bam)
    if header_ok is False:
        return True
    if header_ok is None:
        return False
    try:
        _, start, end = parse_region_bounds(region)
    except ValueError:
        return False
    width = end - start
    if width <= 0:
        return True
    min_bytes = max(8_000_000, int(width * 32))
    return size < min_bytes


def _finalize_bam_extract(tmp: Path, dest: Path, region: str) -> None:
    """Validate a freshly extracted BAM, then atomically promote + index."""
    if not regional_bam_valid(tmp, region, require_index=False):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"extracted BAM failed validation for {region}")
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
    _ensure_bam_index(dest)
    if not regional_bam_valid(dest, region):
        _remove_regional_bam(dest)
        raise RuntimeError(f"indexed BAM failed validation for {region}")


def region_contains(outer: str, inner: str) -> bool:
    """True when *outer* fully spans *inner* on the same chromosome."""
    try:
        o_chrom, o_start, o_end = parse_region_bounds(outer)
        i_chrom, i_start, i_end = parse_region_bounds(inner)
    except ValueError:
        return False
    return o_chrom == i_chrom and o_start <= i_start and o_end >= i_end


def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


@contextmanager
def _bam_extract_lock(region: str):
    """Serialize extract/index for one region (avoid duplicate FTP pulls)."""
    GIAB_BAM_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = GIAB_BAM_DIR / f".lock_{region.replace(':', '_')}"
    with open(lock_path, "w", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _samtools_threads() -> int:
    raw = os.getenv("GIAB_SAMTOOLS_THREADS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return max(1, min(8, os.cpu_count() or 4))


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


def _near_parent_expanded_region(region: str, *, max_slop_bp: int = 2_000_000) -> Optional[str]:
    """When a cached BAM almost contains *region*, return a minimal expanded superset to fetch once."""
    try:
        chrom, need_start, need_end = parse_region_bounds(region)
    except ValueError:
        return None
    if not GIAB_BAM_DIR.exists():
        return None

    best: Optional[Tuple[int, int, int]] = None  # (total_slop, b_start, b_end)
    for path in GIAB_BAM_DIR.glob("HG002_*.bam"):
        bounds = _bam_path_region_bounds(path)
        if not bounds:
            continue
        b_chrom, b_start, b_end = bounds
        if b_chrom != chrom:
            continue
        if not bam_index_path(path).exists():
            continue
        parent_region = f"{b_chrom}:{b_start}-{b_end}"
        if not regional_bam_valid(path, parent_region):
            continue
        if b_start <= need_start and b_end >= need_end:
            return None
        start_slop = max(0, b_start - need_start)
        end_slop = max(0, need_end - b_end)
        if start_slop == 0 and end_slop == 0:
            continue
        if start_slop > max_slop_bp or end_slop > max_slop_bp:
            continue
        if b_end <= need_start or b_start >= need_end:
            continue
        total_slop = start_slop + end_slop
        if best is None or total_slop < best[0]:
            best = (total_slop, b_start, b_end)

    if best is None:
        return None
    _, b_start, b_end = best
    expanded = f"{chrom}:{min(need_start, b_start)}-{max(need_end, b_end)}"
    return expanded if expanded != region else None


def containing_cached_bam(region: str) -> Optional[Path]:
    """Smallest cached BAM that fully contains *region*, if any."""
    try:
        chrom, need_start, need_end = parse_region_bounds(region)
    except ValueError:
        return None
    if not GIAB_BAM_DIR.exists():
        return None

    best: Optional[Path] = None
    best_width: Optional[int] = None
    for path in GIAB_BAM_DIR.glob("HG002_*.bam"):
        bounds = _bam_path_region_bounds(path)
        if not bounds:
            continue
        b_chrom, b_start, b_end = bounds
        if b_chrom != chrom or b_start > need_start or b_end < need_end:
            continue
        if not bam_index_path(path).exists():
            continue
        if not regional_bam_valid(path, f"{b_chrom}:{b_start}-{b_end}"):
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
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    samtools = _samtools_bin()

    if samtools:
        threads = str(_samtools_threads())
        cmd = [samtools, "view", "-@", threads, "-b", str(src), region, "-o", str(tmp)]
        logger.info("samtools local slice: %s from %s", region, src.name)
        _run_checked(cmd, label="samtools view (local)")
        _finalize_bam_extract(tmp, dest, region)
        return

    inner = (
        f"samtools view -b /data/{src.name} {region} -o /out/{tmp.name}"
    )
    cmd = [
        "docker", "run", "--rm",
        *_docker_user_args(),
        "-v", f"{src.parent}:/data:ro",
        f"-v{dest.parent}:/out",
        "staphb/samtools:1.20",
        "sh", "-c", inner,
    ]
    logger.info("docker samtools local slice: %s from %s", region, src.name)
    try:
        _run_checked(cmd, label="docker samtools view (local)")
        _finalize_bam_extract(tmp, dest, region)
    except RuntimeError:
        tmp.unlink(missing_ok=True)
        if dest.exists() and not regional_bam_valid(dest, region, require_index=False):
            _remove_regional_bam(dest)
        raise


def _ensure_bam_index(bam: Path) -> None:
    """Create a .bai index for an existing local BAM."""
    if bam_index_path(bam).exists():
        return
    if not bam.is_file() or bam.stat().st_size == 0:
        raise RuntimeError(f"BAM missing or empty: {bam}")
    if not _bam_has_valid_header(bam):
        raise RuntimeError(f"not a valid BAM file: {bam}")
    samtools = _samtools_bin()
    if samtools:
        threads = str(_samtools_threads())
        _run_checked([samtools, "index", "-@", threads, str(bam)], label="samtools index")
        return
    inner = f"samtools index /data/{bam.name}"
    cmd = [
        "docker",
        "run",
        "--rm",
        *_docker_user_args(),
        "-v",
        f"{bam.parent}:/data",
        "staphb/samtools:1.20",
        "sh",
        "-c",
        inner,
    ]
    logger.info("docker samtools index: %s", bam.name)
    _run_checked(cmd, label="docker samtools index")


def repair_giab_bam_indexes(*, dry_run: bool = False) -> List[Path]:
    """Index any cached GIAB BAMs that are missing a .bai file."""
    repaired: List[Path] = []
    if not GIAB_BAM_DIR.is_dir():
        return repaired
    for bam in sorted(GIAB_BAM_DIR.glob("HG002_*.bam")):
        bounds = _bam_path_region_bounds(bam)
        region = f"{bounds[0]}:{bounds[1]}-{bounds[2]}" if bounds else ""
        if bounds and _regional_bam_corrupt(bam, region):
            if dry_run:
                repaired.append(bam)
                continue
            logger.warning("Removing corrupt regional BAM %s", bam.name)
            _remove_regional_bam(bam)
            repaired.append(bam)
            continue
        if not bam_index_path(bam).exists() or (
            bam_index_path(bam).exists() and bam_index_path(bam).stat().st_mtime < bam.stat().st_mtime
        ):
            if dry_run:
                repaired.append(bam)
                continue
            try:
                _ensure_bam_index(bam)
            except RuntimeError as exc:
                logger.warning("Index failed for %s (%s) — removing", bam.name, exc)
                _remove_regional_bam(bam)
                continue
            repaired.append(bam)
            continue
    return repaired


def ensure_bam_for_region(region: str, *, parent_region: Optional[str] = None) -> Path:
    """Cache HG002 BAM slice for the given region (exact coordinates)."""
    dest = regional_bam_cache_path(region)
    if dest.exists():
        if not regional_bam_valid(dest, region, require_index=False):
            logger.warning("Removing invalid regional BAM %s — re-extracting", dest.name)
            _remove_regional_bam(dest)
        elif not bam_index_path(dest).exists() or bam_index_path(dest).stat().st_mtime < dest.stat().st_mtime:
            try:
                _ensure_bam_index(dest)
            except RuntimeError as exc:
                logger.warning("Index failed for %s (%s) — re-extracting", dest.name, exc)
                _remove_regional_bam(dest)
            else:
                if regional_bam_valid(dest, region):
                    return dest
                _remove_regional_bam(dest)
        elif regional_bam_valid(dest, region):
            return dest
        else:
            _remove_regional_bam(dest)

    with _bam_extract_lock(region):
        if regional_bam_valid(dest, region):
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

        expanded = _near_parent_expanded_region(region)
        if expanded and expanded != region:
            expanded_dest = regional_bam_cache_path(expanded)
            if not regional_bam_valid(expanded_dest, expanded, require_index=False):
                logger.info(
                    "Near-parent expanded fetch: %s (then slice %s)",
                    expanded,
                    region,
                )
                _samtools_view_region(expanded, expanded_dest)
            if regional_bam_valid(expanded_dest, expanded):
                _samtools_view_local_bam(expanded_dest, region, dest)
                return dest

        if (
            parent_region
            and parent_region != region
            and region_contains(parent_region, region)
            and _env_flag("GIAB_BAM_PARENT_FIRST", "1")
        ):
            logger.info("Parent-first BAM fetch: %s → slice %s", parent_region, region)
            ensure_bam_for_region(parent_region)
            parent = containing_cached_bam(region)
            if parent:
                _samtools_view_local_bam(parent, region, dest)
                return dest

        _samtools_view_region(region, dest)
    return dest


def prefetch_bams_for_windows(
    parent_region: Optional[str],
    windows: Iterable[str],
) -> None:
    """Warm BAM cache: one parent FTP pull, then fast local slices for sub-windows."""
    wins = [str(w).strip() for w in windows if str(w).strip()]
    if not wins:
        return

    if (
        parent_region
        and _env_flag("GIAB_BAM_PARENT_FIRST", "1")
        and any(w != parent_region and region_contains(parent_region, w) for w in wins)
    ):
        ensure_bam_for_region(parent_region)

    for win in wins:
        if bam_cache_ready_for_region(win):
            continue
        ensure_bam_for_region(win, parent_region=parent_region)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    logger.info("Downloading %s → %s", url, dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
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
    explicit = os.getenv("GIAB_SAMTOOLS_PATH", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    if shutil.which("samtools"):
        return "samtools"
    return None


def _run_checked(cmd: list[str], *, label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if result.returncode == 130:
            raise RuntimeError(
                f"{label} interrupted (exit 130) — server shutdown or Ctrl+C while extracting BAM"
            )
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {detail[:800]}")


def _remote_bam_url() -> str:
    return ASSETS["bam_remote"]


def _url_needs_docker_samtools(url: str) -> bool:
    """Host apt samtools often lacks HTTPS/FTP — use docker for remote URLs."""
    return url.startswith(("http://", "https://", "ftp://", "s3://"))


def _docker_samtools_view_remote(region: str, tmp: Path, remote: str) -> None:
    threads = _samtools_threads()
    # Remote indexed BAM: samtools writes a sidecar .bai in cwd — must be writable.
    inner = (
        f"cd /out && samtools view -@ {threads} -b '{remote}' {region} -o {tmp.name}"
    )
    cmd = [
        "docker", "run", "--rm",
        *_docker_user_args(),
        "-v", "/etc/ssl/certs:/etc/ssl/certs:ro",
        "-e", "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
        f"-v{tmp.parent}:/out",
        "staphb/samtools:1.20",
        "sh", "-c", inner,
    ]
    logger.info("docker samtools regional extract: %s", region)
    _run_checked(cmd, label="docker samtools regional extract")


def _samtools_view_region(region: str, dest: Path) -> None:
    """Extract a genomic window from remote indexed HG002 BAM."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    remote = _remote_bam_url()

    if _url_needs_docker_samtools(remote):
        try:
            _docker_samtools_view_remote(region, tmp, remote)
            _finalize_bam_extract(tmp, dest, region)
        except RuntimeError:
            tmp.unlink(missing_ok=True)
            raise
        return

    samtools = _samtools_bin()
    if samtools:
        threads = str(_samtools_threads())
        cmd = [samtools, "view", "-@", threads, "-b", remote, region, "-o", str(tmp)]
        logger.info("samtools regional extract: %s → %s", region, dest.name)
        try:
            _run_checked(cmd, label="samtools view")
            _finalize_bam_extract(tmp, dest, region)
        except RuntimeError as exc:
            tmp.unlink(missing_ok=True)
            detail = str(exc)
            if "Protocol not supported" in detail:
                logger.warning("host samtools lacks remote protocol support — retrying via docker")
                _docker_samtools_view_remote(region, tmp, remote)
                _finalize_bam_extract(tmp, dest, region)
            else:
                raise
        return

    _docker_samtools_view_remote(region, tmp, remote)
    _finalize_bam_extract(tmp, dest, region)


def ensure_regional_bam(chrom: str, region: str) -> Path:
    """Cache HG002 BAM slice for a Minos-like window."""
    dest = asset_path(f"bam_region_{chrom}")
    if dest.exists() and bam_index_path(dest).exists():
        return dest
    _samtools_view_region(region, dest)
    return dest


REF_S3_BASE = "https://api.theminos.ai/reference"

_SDF_FILES = (
    "done", "mainIndex",
    "nameIndex0", "namedata0", "namepointer0",
    "progress", "seqdata0", "seqpointer0",
    "sequenceIndex0", "summary.txt",
)


def ensure_sdf(chrom: str) -> Path:
    """Ensure RTG SDF exists for hap.py (builds locally if needed; does not touch miner config)."""
    ref_dir = Path(__file__).resolve().parents[2] / "datasets" / "reference" / chrom
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

            # Prefer local build — Minos CDN may block unattended downloads.
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
        import shutil
        shutil.rmtree(sdf_dir)
    chrom_dir = fasta.parent
    from base.genomics_config import GENOMICS_CONFIG

    image = GENOMICS_CONFIG["happy_docker_image"]
    cmd = [
        "docker", "run", "--rm",
        f"-v{chrom_dir}:/data",
        "--entrypoint", "/opt/rtg-tools-3.12.1/rtg",
        image,
        "format", "-o", f"/data/{sdf_dir.name}", f"/data/{fasta.name}",
    ]
    logger.info("Building RTG SDF for %s", fasta.name)
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def reference_for_chrom(chrom: str) -> Path:
    ref = Path(__file__).resolve().parents[2] / "datasets" / "reference" / chrom / f"{chrom}.fa"
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
