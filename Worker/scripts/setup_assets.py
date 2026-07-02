#!/usr/bin/env python3
"""Download benchmark datasets and pull variant-caller Docker images for the worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

REF_BASE = os.getenv("WORKER_REFERENCE_URL", "https://api.theminos.ai/reference").rstrip("/")
PLATFORM_URL = os.getenv("WORKER_PLATFORM_URL", "https://api.theminos.ai").rstrip("/")
DATA_DIR = ROOT / os.getenv("WORKER_DATA_DIR", "datasets")
USER_AGENT = "effortless-worker-setup/0.1 (+https://github.com/minos-protocol/minos_subnet)"

ALL_CHROMS = [f"chr{i}" for i in range(1, 23)]

DOCKER_IMAGES = {
    "gatk": [
        "broadinstitute/gatk:4.5.0.0",
        "quay.io/biocontainers/samtools:1.20--h50ea8bc_0",
        "quay.io/biocontainers/bcftools:1.20--h8b25389_0",
    ],
    "deepvariant": ["google/deepvariant:1.5.0"],
    "bcftools": ["quay.io/biocontainers/bcftools:1.20--h8b25389_0"],
}

SCORING_IMAGES = [
    "genonet/hap-py@sha256:03acabe84bbfba35f5a7234129d524c563f5657e1f21150a2ea2797f8e6d05f2",
]

SDF_FILES = [
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
]


def parse_chromosomes(raw: str) -> list[str]:
    value = (raw or "chr20,chr21").strip().lower()
    if value == "all":
        return list(ALL_CHROMS)
    chroms = [c.strip() for c in value.split(",") if c.strip()]
    for chrom in chroms:
        if chrom not in ALL_CHROMS:
            raise ValueError(f"Unsupported chromosome: {chrom}")
    return chroms


def parse_tools(raw: str) -> list[str]:
    tools = [t.strip().lower() for t in (raw or "gatk,bcftools,deepvariant").split(",") if t.strip()]
    unknown = [t for t in tools if t not in DOCKER_IMAGES]
    if unknown:
        raise ValueError(f"Unknown tools: {', '.join(unknown)}")
    return tools


def human_size(num_bytes: int) -> str:
    num = float(max(0, num_bytes))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if num < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(num)} {unit}"
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{int(num_bytes)} B"


def _bam_index_ok(bam_path: Path) -> bool:
    if not bam_path.exists() or bam_path.stat().st_size <= 0:
        return False
    index = bam_path.parent / f"{bam_path.name}.bai"
    return index.exists() and index.stat().st_size > 0


def find_local_benchmark_bam(chrom: str) -> Path | None:
    """Any indexed HG002 benchmark BAM for this chromosome (canonical name not required)."""
    bams_dir = DATA_DIR / "bams"
    canonical = bams_dir / f"{chrom}.bam"
    if _bam_index_ok(canonical):
        return canonical

    for directory in (bams_dir, DATA_DIR / "bam"):
        minos = directory / f"HG002_{chrom}_minos_window.bam"
        if _bam_index_ok(minos):
            return minos

    if bams_dir.is_dir():
        for candidate in sorted(bams_dir.glob(f"HG002_{chrom}_*.bam")):
            if _bam_index_ok(candidate):
                return candidate
    return None


def benchmark_truth_path() -> Path | None:
    rel = os.getenv("WORKER_BENCHMARK_TRUTH_VCF", "data/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz")
    path = DATA_DIR / rel
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"  wrote {manifest_path.relative_to(ROOT)}")


def print_dataset_inventory(chromosomes: list[str]) -> None:
    print("\n== Dataset inventory ==")
    total = 0
    truth = benchmark_truth_path()
    for chrom in chromosomes:
        ref_paths = [
            DATA_DIR / "reference" / chrom / f"{chrom}.fa",
            DATA_DIR / "reference" / chrom / f"{chrom}.sdf",
        ]
        for path in ref_paths:
            if not path.exists():
                print(f"  missing  {path.relative_to(ROOT)}")
                continue
            size = path.stat().st_size if path.is_file() else sum(
                f.stat().st_size for f in path.rglob("*") if f.is_file()
            )
            total += size
            print(f"  {human_size(size):>8}  {path.relative_to(ROOT)}")

        bam = find_local_benchmark_bam(chrom)
        if bam is not None:
            size = bam.stat().st_size
            total += size
            print(f"  {human_size(size):>8}  {bam.relative_to(ROOT)}  [benchmark BAM]")
            index = bam.parent / f"{bam.name}.bai"
            if index.exists():
                total += index.stat().st_size
        else:
            print(f"  missing  datasets/bams/{chrom}.bam or HG002_{chrom}_*.bam")

        per_chrom_truth = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
        if per_chrom_truth.exists():
            size = per_chrom_truth.stat().st_size
            total += size
            print(f"  {human_size(size):>8}  {per_chrom_truth.relative_to(ROOT)}  [truth]")
        elif truth is not None:
            print(f"  {human_size(truth.stat().st_size):>8}  {truth.relative_to(ROOT)}  [GIAB truth, shared]")
            total += truth.stat().st_size
        else:
            print(f"  missing  datasets/data/ GIAB truth or datasets/truth/{chrom}.vcf.gz")

        mutations = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
        if mutations.exists():
            size = mutations.stat().st_size
            total += size
            print(f"  {human_size(size):>8}  {mutations.relative_to(ROOT)}  [mutations, optional]")
    print(f"  total    {human_size(total)} under {DATA_DIR.relative_to(ROOT)}/")


def download_url(url: str, dest: Path, *, force: bool = False, expected_sha256: str | None = None) -> bool:
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  skip (exists): {dest.relative_to(ROOT)}")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    print(f"  download: {dest.name}")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=600) as response:
        total = int(response.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        chunk_size = 1024 * 1024
        last_report = time.time()
        with tmp.open("wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_report >= 2:
                    if total:
                        pct = downloaded * 100 / total
                        print(f"    {human_size(downloaded)} / {human_size(total)} ({pct:.0f}%)", flush=True)
                    else:
                        print(f"    {human_size(downloaded)}", flush=True)
                    last_report = now

    tmp.rename(dest)
    if expected_sha256:
        actual = compute_sha256(dest)
        if actual.lower() != expected_sha256.lower():
            dest.unlink(missing_ok=True)
            raise ValueError(f"SHA256 mismatch for {dest.name}: expected {expected_sha256}, got {actual}")
    print(f"    done ({human_size(dest.stat().st_size)})")
    return True


def reference_files(chrom: str) -> list[tuple[str, Path, str]]:
    return [
        (f"{chrom} FASTA", DATA_DIR / "reference" / chrom / f"{chrom}.fa", f"{REF_BASE}/{chrom}/{chrom}.fa"),
        (f"{chrom} FAI", DATA_DIR / "reference" / chrom / f"{chrom}.fa.fai", f"{REF_BASE}/{chrom}/{chrom}.fa.fai"),
        (f"{chrom} DICT", DATA_DIR / "reference" / chrom / f"{chrom}.dict", f"{REF_BASE}/{chrom}/{chrom}.dict"),
    ]


def download_reference(chromosomes: list[str], *, force: bool = False) -> bool:
    print("\n== Reference data ==")
    ok = True
    for chrom in chromosomes:
        print(f"[{chrom}]")
        for label, local_path, url in reference_files(chrom):
            try:
                if not download_url(url, local_path, force=force):
                    ok = False
            except Exception as exc:
                print(f"  failed {label}: {exc}")
                ok = False
    return ok


def sign_platform_request(path: str, keypair, extra: dict | None = None) -> dict:
    from bittensor_wallet import Keypair

    if not isinstance(keypair, Keypair):
        raise TypeError("keypair must be a bittensor Keypair")
    timestamp = int(time.time())
    nonce = uuid.uuid4().hex
    body = {"timestamp": timestamp, **(extra or {})}
    canonical_body = {k: v for k, v in sorted(body.items()) if k not in ("signature", "nonce")}
    body_hash = hashlib.sha256(
        json.dumps(canonical_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    canonical = f"POST|{path}|{body_hash}|{timestamp}|{nonce}"
    body["signature"] = keypair.sign(canonical.encode()).hex()
    body["nonce"] = nonce
    return body


def sign_demo_request(path: str, extra: dict | None = None) -> dict:
    from bittensor_wallet import Keypair

    keypair = Keypair.create_from_uri("//worker-asset-setup")
    payload = {"hotkey": keypair.ss58_address, **(extra or {})}
    return sign_platform_request(path, keypair, payload)


def parse_chrom_from_region(region: str | None) -> str | None:
    if not region:
        return None
    match = re.match(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):", region)
    return match.group(1) if match else None


def parse_manual_truth_urls(raw: str | None) -> dict[str, str]:
    """Optional WORKER_TRUTH_URLS=chr20:https://...,chr21:https://..."""
    return parse_manual_bam_urls(raw)


def parse_manual_mutations_urls(raw: str | None) -> dict[str, str]:
    """Optional WORKER_MUTATIONS_URLS=chr20:https://...,chr21:https://..."""
    return parse_manual_bam_urls(raw)


def load_optional_validator_keypair():
    uri = os.getenv("WORKER_VALIDATOR_WALLET_URI", "").strip()
    if uri:
        from bittensor_wallet import Keypair

        return Keypair.create_from_uri(uri)
    name = os.getenv("WORKER_VALIDATOR_WALLET_NAME", "").strip()
    hotkey = os.getenv("WORKER_VALIDATOR_WALLET_HOTKEY", "").strip()
    if name and hotkey:
        from bittensor_wallet import Wallet

        return Wallet(name=name, hotkey=hotkey).hotkey
    return None


def httpx_setup_hint() -> str:
    venv_python = ROOT / ".venv" / "bin" / "python"
    lines = [
        "httpx is required for platform BAM/truth downloads.",
        "  From Worker/:  ./setup.sh",
        "  or:  source .venv/bin/activate && pip install -r requirements.txt",
    ]
    if venv_python.exists():
        lines.append(f"  or:  {venv_python.relative_to(ROOT)} scripts/setup_assets.py --force")
    return "\n".join(lines)


def reexec_with_venv_if_needed() -> None:
    """Use Worker/.venv when the invoking interpreter lacks setup dependencies."""
    try:
        import httpx  # noqa: F401
        return
    except ImportError:
        pass
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    print(f"Re-running with {venv_python.relative_to(ROOT)} (current Python lacks httpx)")
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


def try_fetch_demo_round(*, chromosome: str | None = None) -> dict:
    try:
        return fetch_demo_round(chromosome=chromosome)
    except ImportError as exc:
        if "httpx" in str(exc).lower():
            print(f"  platform API skipped — {httpx_setup_hint()}")
        else:
            print(f"  platform API skipped: {exc}")
        return {}
    except Exception as exc:
        print(f"  failed to query platform demo round: {exc}")
        return {}


def fetch_submissions_round(round_id: str) -> dict:
    """Validator-only API: includes truth_vcf presigned URLs during scoring."""
    keypair = load_optional_validator_keypair()
    if not keypair:
        return {}

    try:
        import httpx
    except ImportError:
        print("  get-submissions skipped (httpx not installed)")
        return {}

    path = "/v2/get-submissions"
    body = sign_platform_request(
        path,
        keypair,
        {"round_id": round_id, "validator_hotkey": keypair.ss58_address},
    )
    with httpx.Client(base_url=PLATFORM_URL, timeout=120.0) as client:
        response = client.post(path, json=body, headers={"X-Minos-Auth-Version": "2"})
        if response.status_code != 200:
            print(
                f"  get-submissions for {round_id[:16]}... failed ({response.status_code}): "
                f"{response.text[:200]}"
            )
            return {}
        return response.json()


def parse_manual_bam_urls(raw: str | None) -> dict[str, str]:
    """Optional WORKER_BAM_URLS=chr20:https://...,chr21:https://..."""
    if not raw:
        return {}
    urls: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        chrom, url = part.split(":", 1)
        chrom = chrom.strip()
        url = url.strip()
        if chrom and url:
            urls[chrom] = url
    return urls


def fetch_demo_round(*, chromosome: str | None = None) -> dict:
    import httpx

    path = "/v2/demo/round-status"
    extra = {"chromosome": chromosome} if chromosome else None
    body = sign_demo_request(path, extra=extra)
    with httpx.Client(base_url=PLATFORM_URL, timeout=120.0) as client:
        response = client.post(path, json=body, headers={"X-Minos-Auth-Version": "2"})
        response.raise_for_status()
        return response.json()


def sdf_files(chrom: str) -> list[tuple[str, Path, str]]:
    rows: list[tuple[str, Path, str]] = []
    for sdf_file in SDF_FILES:
        rows.append(
            (
                f"{chrom} SDF {sdf_file}",
                DATA_DIR / "reference" / chrom / f"{chrom}.sdf" / sdf_file,
                f"{REF_BASE}/{chrom}/{chrom}.sdf/{sdf_file}",
            )
        )
    return rows


def download_sdf(chromosomes: list[str], *, force: bool = False) -> bool:
    print("\n== Reference SDF (hap.py scoring) ==")
    ok = True
    for chrom in chromosomes:
        print(f"[{chrom}]")
        for label, local_path, url in sdf_files(chrom):
            try:
                if not download_url(url, local_path, force=force):
                    ok = False
            except Exception as exc:
                print(f"  failed {label}: {exc}")
                ok = False
    return ok


def _pick_urls(round_data: dict, primary_key: str, backup_key: str) -> tuple[str | None, str | None]:
    prefer_hippius = os.getenv("STORAGE_PRIMARY_BACKEND", "hippius").lower() != "aws_s3"
    primary = round_data.get(primary_key)
    backup = round_data.get(backup_key)
    if prefer_hippius:
        return backup or primary, primary or backup
    return primary or backup, backup or primary


def _download_file_with_backup(
    primary_url: str | None,
    backup_url: str | None,
    dest: Path,
    *,
    force: bool,
    expected_sha256: str | None = None,
) -> None:
    if not primary_url and not backup_url:
        raise ValueError(f"no URL for {dest.name}")
    try:
        if primary_url:
            download_url(primary_url, dest, force=force, expected_sha256=expected_sha256)
            return
    except Exception:
        if backup_url:
            print(f"  retrying {dest.name} from backup URL")
            download_url(backup_url, dest, force=True, expected_sha256=expected_sha256)
            return
        raise
    if backup_url:
        download_url(backup_url, dest, force=True, expected_sha256=expected_sha256)


def download_truth_from_round_data(chrom: str, round_data: dict, *, force: bool = False) -> bool:
    """Download truth + mutations VCFs when presigned URLs exist in a round payload."""
    region = round_data.get("region")
    round_chrom = parse_chrom_from_region(region)
    if round_chrom and round_chrom != chrom:
        return False

    truth_url, truth_url_backup = _pick_urls(round_data, "truth_vcf_presigned_url", "truth_vcf_presigned_url_backup")
    truth_index_url, truth_index_url_backup = _pick_urls(
        round_data, "truth_vcf_index_presigned_url", "truth_vcf_index_presigned_url_backup"
    )
    mutations_url, mutations_url_backup = _pick_urls(
        round_data, "mutations_vcf_presigned_url", "mutations_vcf_presigned_url_backup"
    )
    mutations_index_url, mutations_index_url_backup = _pick_urls(
        round_data, "mutations_vcf_index_presigned_url", "mutations_vcf_index_presigned_url_backup"
    )

    truth_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
    truth_index_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz.tbi"
    mutations_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
    mutations_index_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz.tbi"

    if truth_path.exists() and truth_path.stat().st_size > 0 and not force:
        return True

    if truth_url or truth_url_backup:
        print(f"  truth: {truth_path.relative_to(ROOT)}")
        _download_file_with_backup(
            truth_url,
            truth_url_backup,
            truth_path,
            force=force,
            expected_sha256=round_data.get("truth_vcf_sha256"),
        )
        if truth_index_url or truth_index_url_backup:
            _download_file_with_backup(truth_index_url, truth_index_url_backup, truth_index_path, force=force)

    if mutations_url or mutations_url_backup:
        print(f"  mutations: {mutations_path.relative_to(ROOT)}")
        _download_file_with_backup(
            mutations_url,
            mutations_url_backup,
            mutations_path,
            force=force,
            expected_sha256=round_data.get("mutations_vcf_sha256"),
        )
        if mutations_index_url or mutations_index_url_backup:
            _download_file_with_backup(
                mutations_index_url, mutations_index_url_backup, mutations_index_path, force=force
            )

    return truth_path.exists() and truth_path.stat().st_size > 0


def download_manual_truth(chrom: str, url: str, *, force: bool = False) -> None:
    truth_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
    print(f"[{chrom}] manual truth URL")
    print(f"  truth: {truth_path.relative_to(ROOT)}")
    download_url(url, truth_path, force=force)


def download_manual_mutations(chrom: str, url: str, *, force: bool = False) -> None:
    mutations_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
    print(f"[{chrom}] manual mutations URL")
    print(f"  mutations: {mutations_path.relative_to(ROOT)}")
    download_url(url, mutations_path, force=force)


def ensure_truth_assets(
    chrom: str,
    *,
    round_data: dict,
    round_id: str | None,
    manual_truth: dict[str, str],
    manual_mutations: dict[str, str],
    force: bool = False,
) -> bool:
    truth_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
    if truth_path.exists() and truth_path.stat().st_size > 0 and not force:
        print(f"[{chrom}] skip truth (exists): {truth_path.relative_to(ROOT)}")
        return True

    print(f"[{chrom}] truth VCF missing — trying download sources…")

    sources: list[tuple[str, dict]] = []
    if round_data:
        sources.append(("demo round-status", round_data))
    if round_id:
        submissions = fetch_submissions_round(round_id)
        if submissions:
            sources.append(("validator get-submissions", submissions))
    hinted = try_fetch_demo_round(chromosome=chrom)
    if hinted:
        sources.append((f"demo round-status ({chrom} hint)", hinted))

    for label, payload in sources:
        try:
            if download_truth_from_round_data(chrom, payload, force=force):
                print(f"  truth downloaded via {label}")
                break
        except Exception as exc:
            print(f"  {label} failed: {exc}")

    if chrom in manual_truth and not truth_path.exists():
        try:
            download_manual_truth(chrom, manual_truth[chrom], force=force)
        except Exception as exc:
            print(f"  manual truth URL failed: {exc}")

    if chrom in manual_mutations:
        mutations_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
        if not mutations_path.exists() or force:
            try:
                download_manual_mutations(chrom, manual_mutations[chrom], force=force)
            except Exception as exc:
                print(f"  manual mutations URL failed: {exc}")

    if truth_path.exists() and truth_path.stat().st_size > 0:
        return True

    print(
        "  truth still missing. Miner demo round-status does not ship truth URLs.\n"
        "  Options:\n"
        "    • Set WORKER_VALIDATOR_WALLET_NAME + WORKER_VALIDATOR_WALLET_HOTKEY (registered validator)\n"
        "      and re-run ./setup.sh while a matching round is in scoring phase, or\n"
        "    • Set WORKER_TRUTH_URLS=chr20:https://... (presigned truth VCF URL), or\n"
        "    • Set WORKER_CHROMOSOMES=chr20 if you only benchmark chr20."
    )
    return False


def download_round_assets(chrom: str, round_data: dict, *, force: bool = False) -> dict:
    """Download BAM for one chromosome from a platform round payload."""
    region = round_data.get("region")
    round_chrom = parse_chrom_from_region(region)
    if round_chrom and round_chrom != chrom:
        raise ValueError(f"round region {region!r} is not for {chrom}")

    bam_url, bam_url_backup = _pick_urls(round_data, "bam_presigned_url", "bam_presigned_url_backup")
    index_url, index_url_backup = _pick_urls(round_data, "bam_index_presigned_url", "bam_index_presigned_url_backup")

    if not bam_url and not bam_url_backup:
        raise ValueError("no BAM URL in platform response")

    bam_path = DATA_DIR / "bams" / f"{chrom}.bam"
    index_path = DATA_DIR / "bams" / f"{chrom}.bam.bai"
    truth_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
    mutations_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"

    print(f"[{chrom}] region: {region or 'unknown'}")
    print(f"  BAM: {bam_path.relative_to(ROOT)}")
    _download_file_with_backup(
        bam_url,
        bam_url_backup,
        bam_path,
        force=force,
        expected_sha256=round_data.get("bam_sha256"),
    )
    if index_url or index_url_backup:
        try:
            _download_file_with_backup(index_url, index_url_backup, index_path, force=force)
        except Exception as exc:
            print(f"  warning: BAM index download failed: {exc}")

    return {
        "chromosome": chrom,
        "region": region,
        "downsampled_coverage": round_data.get("downsampled_coverage"),
        "bam_path": str(bam_path.relative_to(ROOT)),
        "bam_size_bytes": bam_path.stat().st_size if bam_path.exists() else 0,
        "bam_size_human": human_size(bam_path.stat().st_size) if bam_path.exists() else None,
        "truth_path": str(truth_path.relative_to(ROOT)) if truth_path.exists() else None,
        "mutations_path": str(mutations_path.relative_to(ROOT)) if mutations_path.exists() else None,
    }


def download_manual_bam(chrom: str, url: str, *, force: bool = False) -> None:
    bam_path = DATA_DIR / "bams" / f"{chrom}.bam"
    print(f"[{chrom}] manual BAM URL")
    print(f"  BAM: {bam_path.relative_to(ROOT)}")
    download_url(url, bam_path, force=force)


def download_benchmark_assets(chromosomes: list[str], *, force: bool = False) -> bool:
    print("\n== Benchmark BAM + truth (platform demo round) ==")
    print("  Note: demo BAM is typically ~100–200 MiB per chromosome.")
    manual_urls = parse_manual_bam_urls(os.getenv("WORKER_BAM_URLS"))

    try:
        round_data = try_fetch_demo_round()
    except Exception as exc:
        print(f"  failed to query platform demo round: {exc}")
        round_data = {}

    active_chrom = parse_chrom_from_region(round_data.get("region"))
    manifest_rows: list[dict] = []
    ok = True

    for chrom in chromosomes:
        bam_path = DATA_DIR / "bams" / f"{chrom}.bam"
        if bam_path.exists() and bam_path.stat().st_size > 0 and not force:
            print(f"[{chrom}] skip BAM (exists): {bam_path.relative_to(ROOT)} ({human_size(bam_path.stat().st_size)})")
            manifest_rows.append(
                {
                    "chromosome": chrom,
                    "bam_path": str(bam_path.relative_to(ROOT)),
                    "bam_size_bytes": bam_path.stat().st_size,
                    "bam_size_human": human_size(bam_path.stat().st_size),
                    "source": "existing",
                }
            )
            continue

        try:
            if active_chrom == chrom and round_data.get("bam_presigned_url"):
                row = download_round_assets(chrom, round_data, force=force)
                row["source"] = "platform_demo"
                manifest_rows.append(row)
                continue

            hinted = try_fetch_demo_round(chromosome=chrom)
            hint_chrom = parse_chrom_from_region(hinted.get("region"))
            if hint_chrom == chrom and hinted.get("bam_presigned_url"):
                row = download_round_assets(chrom, hinted, force=force)
                row["source"] = "platform_demo_hint"
                manifest_rows.append(row)
                continue

            if chrom in manual_urls:
                download_manual_bam(chrom, manual_urls[chrom], force=force)
                manifest_rows.append(
                    {
                        "chromosome": chrom,
                        "bam_path": str(bam_path.relative_to(ROOT)),
                        "bam_size_bytes": bam_path.stat().st_size,
                        "bam_size_human": human_size(bam_path.stat().st_size),
                        "source": "manual_url",
                    }
                )
                continue

            print(
                f"[{chrom}] no BAM available from platform demo "
                f"(active round: {active_chrom or 'unknown'}). "
                f"Set WORKER_BAM_URLS={chrom}:<presigned-url> or re-run when platform serves this chromosome."
            )
            ok = False
        except Exception as exc:
            print(f"[{chrom}] download failed: {exc}")
            ok = False

    print("\n== Benchmark truth VCF (hap.py scoring) ==")
    print(
        "  Miner demo round-status includes BAM URLs only — not truth.\n"
        "  Truth is downloaded via validator get-submissions (wallet env) or WORKER_TRUTH_URLS."
    )
    manual_truth = parse_manual_truth_urls(os.getenv("WORKER_TRUTH_URLS"))
    manual_mutations = parse_manual_mutations_urls(os.getenv("WORKER_MUTATIONS_URLS"))
    round_id = str(round_data.get("round_id") or "") or None

    for chrom in chromosomes:
        if not ensure_truth_assets(
            chrom,
            round_data=round_data,
            round_id=round_id,
            manual_truth=manual_truth,
            manual_mutations=manual_mutations,
            force=force,
        ):
            ok = False

    for row in manifest_rows:
        chrom = row.get("chromosome")
        if not chrom:
            continue
        truth_path = DATA_DIR / "truth" / f"{chrom}.vcf.gz"
        mutations_path = DATA_DIR / "truth" / f"{chrom}.mutations.vcf.gz"
        row["truth_path"] = str(truth_path.relative_to(ROOT)) if truth_path.exists() else None
        row["mutations_path"] = (
            str(mutations_path.relative_to(ROOT)) if mutations_path.exists() else None
        )

    if manifest_rows:
        write_manifest(
            {
                "chromosomes": chromosomes,
                "assets": manifest_rows,
                "note": "Demo/platform benchmark assets for chr20 + chr21 worker windows.",
            }
        )

    missing_bams = [c for c in chromosomes if not (DATA_DIR / "bams" / f"{c}.bam").exists()]
    if missing_bams:
        ok = False
    missing_truth = [
        c
        for c in chromosomes
        if (DATA_DIR / "bams" / f"{c}.bam").exists()
        and not (DATA_DIR / "truth" / f"{c}.vcf.gz").exists()
    ]
    if missing_truth:
        ok = False
    return ok


def download_benchmark_bam(chromosomes: list[str], *, force: bool = False) -> bool:
    return download_benchmark_assets(chromosomes, force=force)


def _hf_dataset_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo.strip().strip('/')}/resolve/main/{path.lstrip('/')}"


def _benchmark_bam_hf_paths(chrom: str) -> tuple[str, str]:
    template = os.getenv(
        "WORKER_BENCHMARK_HF_BAM_TEMPLATE",
        "bam/HG002_{chrom}_minos_window.bam",
    )
    bam_path = template.format(chrom=chrom)
    index_path = f"{bam_path}.bai"
    return bam_path, index_path


def _link_or_copy_bam(source: Path, dest: Path, *, force: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        dest.unlink()
    try:
        dest.symlink_to(source.resolve())
        print(f"  linked {dest.relative_to(ROOT)} -> {source.relative_to(ROOT)}")
    except OSError:
        shutil.copy2(source, dest)
        print(f"  copied {dest.relative_to(ROOT)}")


def ensure_benchmark_bams(chromosomes: list[str], *, force: bool = False) -> bool:
    """
    Populate datasets/bams/{chrom}.bam from local legacy paths, URLs, or HuggingFace.
    These are fixed HG002 benchmark BAMs — not live platform round BAMs.
    Local HG002_* region BAMs already on disk are accepted without canonical names.
    """
    print("\n== Benchmark BAMs (HG002/minos — both chr20 & chr21) ==")
    manual = parse_manual_bam_urls(os.getenv("WORKER_BENCHMARK_BAM_URLS"))
    hf_repo = os.getenv("WORKER_BENCHMARK_HF_REPO", "").strip()
    ok = True

    for chrom in chromosomes:
        dest = DATA_DIR / "bams" / f"{chrom}.bam"
        index_dest = DATA_DIR / "bams" / f"{chrom}.bam.bai"
        if dest.exists() and dest.stat().st_size > 0 and not force:
            print(f"[{chrom}] skip (exists): {dest.relative_to(ROOT)} ({human_size(dest.stat().st_size)})")
            continue

        local_bam = find_local_benchmark_bam(chrom)
        if local_bam is not None and not force:
            print(
                f"[{chrom}] local benchmark BAM: {local_bam.relative_to(ROOT)} "
                f"({human_size(local_bam.stat().st_size)})"
            )
            if local_bam.resolve() != dest.resolve() and not dest.exists():
                print(f"  note: canonical {dest.relative_to(ROOT)} not required — worker resolves HG002_* BAMs")
            continue

        legacy = DATA_DIR / "bam" / f"HG002_{chrom}_minos_window.bam"
        legacy_index = DATA_DIR / "bam" / f"HG002_{chrom}_minos_window.bam.bai"
        if legacy.exists():
            print(f"[{chrom}] legacy benchmark BAM")
            _link_or_copy_bam(legacy, dest, force=force)
            if legacy_index.exists():
                _link_or_copy_bam(legacy_index, index_dest, force=force)
            elif not index_dest.exists():
                print(f"  warning: missing index {legacy_index.relative_to(ROOT)}")
            continue

        try:
            if chrom in manual:
                print(f"[{chrom}] download benchmark BAM (URL)")
                download_url(manual[chrom], dest, force=force)
                index_url = manual.get(f"{chrom}_bai") or f"{manual[chrom]}.bai"
                try:
                    download_url(index_url, index_dest, force=force)
                except Exception as exc:
                    print(f"  warning: BAM index download failed: {exc}")
                continue

            if hf_repo:
                bam_rel, index_rel = _benchmark_bam_hf_paths(chrom)
                print(f"[{chrom}] HuggingFace {hf_repo}: {bam_rel}")
                try:
                    download_url(_hf_dataset_url(hf_repo, bam_rel), dest, force=force)
                    try:
                        download_url(_hf_dataset_url(hf_repo, index_rel), index_dest, force=force)
                    except Exception as exc:
                        print(f"  warning: BAM index download failed: {exc}")
                    continue
                except HTTPError as exc:
                    if exc.code in (401, 403):
                        print(
                            f"  warning: HuggingFace returned HTTP {exc.code} "
                            f"(private repo or auth required)."
                        )
                    else:
                        raise

            print(
                f"[{chrom}] benchmark BAM missing.\n"
                f"  Place datasets/bams/HG002_{chrom}_*.bam (+ .bai), "
                f"{legacy.relative_to(ROOT)}, or set one of:\n"
                f"    WORKER_BENCHMARK_BAM_URLS={chrom}:https://...\n"
                f"    WORKER_BENCHMARK_HF_REPO=your-org/minos  (public or HF_TOKEN)"
            )
            ok = False
        except (HTTPError, URLError, OSError, ValueError) as exc:
            print(f"[{chrom}] benchmark BAM setup failed: {exc}")
            ok = False

    return ok


def docker_image_exists(image: str) -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def pull_docker_images(tools: list[str], *, force: bool = False) -> bool:
    print("\n== Docker images ==")
    if shutil.which("docker") is None:
        print("  error: docker not found in PATH")
        return False

    seen: set[str] = set()
    images: list[str] = []
    for tool in tools:
        for image in DOCKER_IMAGES[tool]:
            if image not in seen:
                seen.add(image)
                images.append(image)
    for image in SCORING_IMAGES:
        if image not in seen:
            seen.add(image)
            images.append(image)

    ok = True
    for image in images:
        if docker_image_exists(image) and not force:
            print(f"  skip (exists): {image}")
            continue
        print(f"  pulling: {image}")
        result = subprocess.run(["docker", "pull", image], check=False)
        if result.returncode != 0:
            print(f"  failed: {image}")
            ok = False
    return ok


def main() -> int:
    reexec_with_venv_if_needed()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-reference", action="store_true")
    parser.add_argument("--skip-bam", action="store_true")
    parser.add_argument("--skip-docker", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-download / re-pull even if present")
    args = parser.parse_args()

    chromosomes = parse_chromosomes(os.getenv("WORKER_CHROMOSOMES", "chr20,chr21"))
    tools = parse_tools(os.getenv("WORKER_TOOLS", "gatk,bcftools,deepvariant"))
    benchmark_mode = os.getenv("WORKER_BENCHMARK_MODE", "true").lower() in {"1", "true", "yes", "on"}
    download_bam = os.getenv("WORKER_DOWNLOAD_BAM", "false" if benchmark_mode else "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    download_sdf_flag = os.getenv("WORKER_DOWNLOAD_SDF", "true").lower() in {"1", "true", "yes", "on"}

    print("Effortless worker asset setup")
    print(f"  data dir: {DATA_DIR.relative_to(ROOT)}")
    print(f"  chromosomes: {', '.join(chromosomes)}")
    print(f"  tools: {', '.join(tools)}")
    if benchmark_mode:
        print(
            "  mode: benchmark — fixed BAM + GIAB truth in datasets/data/; "
            "job window comes from the round region only"
        )

    if download_bam and not args.skip_bam:
        try:
            import httpx  # noqa: F401
        except ImportError:
            print(f"\n{httpx_setup_hint()}\n")

    success = True
    if not args.skip_reference:
        success = download_reference(chromosomes, force=args.force) and success
    if benchmark_mode and not args.skip_bam:
        success = ensure_benchmark_bams(chromosomes, force=args.force) and success
    if download_bam and not args.skip_bam:
        success = download_benchmark_assets(chromosomes, force=args.force) and success
    elif not download_bam and not benchmark_mode and not args.skip_bam:
        print("\n== Platform BAM/truth ==\n  skipped (WORKER_DOWNLOAD_BAM=false)")
    if download_sdf_flag and not args.skip_reference:
        success = download_sdf(chromosomes, force=args.force) and success
    elif not download_sdf_flag:
        print("\n== Reference SDF ==\n  skipped")
    if not args.skip_docker:
        success = pull_docker_images(tools, force=args.force) and success

    print_dataset_inventory(chromosomes)

    if success:
        print("\nAsset setup complete.")
        print("Verify anytime: python scripts/verify_datasets.py")
        return 0

    print("\nAsset setup finished with errors.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
