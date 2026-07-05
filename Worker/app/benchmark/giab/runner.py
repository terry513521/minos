"""GIAB variant calling + scoring — tuning giab backend, Worker API surface."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict

from app.benchmark.giab.data import (
    bam_cache_ready,
    chrom_from_region,
    ensure_bam_for_region,
    ensure_truth_assets,
    reference_for_chrom,
    regional_bam_cache_path,
)
from app.benchmark.giab.paths import giab_vcf_dir
from app.benchmark.giab.scoring import score_giab
from app.benchmark.giab.tuning_bridge import ensure_tuning_giab
from app.config import Settings, get_settings
from app.core.repo import ensure_repo_imports
from app.optimization.param_specs import coerce_param_value

logger = logging.getLogger(__name__)

_SUPPORTED_TOOLS = frozenset({"gatk", "bcftools", "deepvariant"})
_DEEPVARIANT_MIN_MEMORY_GB = 16


def _region_slug(region: str) -> str:
    return region.replace(":", "_")


def _vcf_slug(instance_id: str, tool: str, region: str, vcf_tag: str) -> str:
    base = f"{instance_id}_{tool}_{_region_slug(region)}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
    slug = f"worker_{digest}"
    if vcf_tag:
        slug = f"{slug}_{vcf_tag}"
    return slug


def _runtime_cfg(
    runtime_conf: Dict[str, Any] | None,
    *,
    settings: Settings,
    tool: str,
    default_timeout: int,
) -> Dict[str, int]:
    runtime_conf = runtime_conf or {}
    threads = max(1, int(runtime_conf.get("threads") or settings.trial_threads))
    memory_gb = max(1, int(runtime_conf.get("memory_gb") or settings.trial_memory_gb))
    if tool == "deepvariant":
        floor = int(os.getenv("GIAB_DV_MEMORY_GB", str(_DEEPVARIANT_MIN_MEMORY_GB)))
        memory_gb = max(memory_gb, floor)
    timeout = int(runtime_conf.get("timeout") or default_timeout)
    return {"threads": threads, "memory_gb": memory_gb, "timeout": timeout}


def _try_reuse_cached_vcf(out_vcf: Path) -> Dict[str, Any] | None:
    if not out_vcf.exists():
        return None
    ensure_repo_imports()
    from templates._common import count_variants, is_valid_vcf_gz

    if not is_valid_vcf_gz(out_vcf):
        logger.warning("Cached VCF is corrupt or incomplete, regenerating: %s", out_vcf)
        out_vcf.unlink(missing_ok=True)
        return None
    return {
        "success": True,
        "variant_count": count_variants(out_vcf),
        "metadata": {"reused_vcf": True},
    }


def _run_gatk_tuning(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    gatk_params: Dict[str, Any],
    *,
    instance_id: str,
) -> Dict[str, Any]:
    ensure_tuning_giab()
    from tuning.giab.calibrate import _run_gatk

    return _run_gatk(bam, ref, region, out_vcf, gatk_params, instance_id=instance_id)


def _run_bcftools_tuning(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    ensure_tuning_giab()
    from tuning.giab.round_verify import _run_bcftools

    return _run_bcftools(bam, ref, region, out_vcf, params)


def _run_deepvariant(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    params: Dict[str, Any],
    *,
    settings: Settings,
    runtime_conf: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    ensure_repo_imports()
    from templates.deepvariant import variant_call

    deepvariant_options = {
        key: coerce_param_value("deepvariant", key, value) for key, value in params.items()
    }
    runtime = _runtime_cfg(
        runtime_conf,
        settings=settings,
        tool="deepvariant",
        default_timeout=int(os.getenv("GIAB_DV_TIMEOUT", "3600")),
    )
    cfg = {"deepvariant_options": deepvariant_options, **runtime}
    return variant_call(bam, ref, out_vcf, region, cfg)


def score_tool_on_region(
    tool: str,
    params: Dict[str, Any],
    region: str,
    *,
    instance_id: str = "",
    skip_bam_download: bool = False,
    vcf_tag: str = "",
    reuse_vcf: bool = True,
    settings: Settings | None = None,
    runtime_conf: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Call + hap.py score one tool config on a GIAB regional BAM."""
    ensure_tuning_giab()
    settings = settings or get_settings()
    tool_key = tool.lower().strip()
    if tool_key not in _SUPPORTED_TOOLS:
        return {"tool": tool_key, "error": f"unsupported tool {tool_key}"}

    ensure_repo_imports()
    from utils.scoring import AdvancedScorer

    chrom = chrom_from_region(region)
    ref = reference_for_chrom(chrom)
    truth_vcf, truth_bed = ensure_truth_assets()
    bam_path = regional_bam_cache_path(region)
    if skip_bam_download and bam_cache_ready(bam_path):
        bam = bam_path
    else:
        bam = ensure_bam_for_region(region)

    slug = _vcf_slug(instance_id or settings.name, tool_key, region, vcf_tag)
    out_vcf = giab_vcf_dir() / f"benchmark_{slug}.vcf.gz"
    giab_vcf_dir().mkdir(parents=True, exist_ok=True)

    call = _try_reuse_cached_vcf(out_vcf) if reuse_vcf else None
    worker_id = instance_id or settings.name
    if call is None and tool_key == "gatk":
        call = _run_gatk_tuning(
            bam, ref, region, out_vcf, params, instance_id=worker_id
        )
    elif call is None and tool_key == "deepvariant":
        call = _run_deepvariant(
            bam, ref, region, out_vcf, params, settings=settings, runtime_conf=runtime_conf
        )
    elif call is None:
        call = _run_bcftools_tuning(bam, ref, region, out_vcf, params)

    if not call.get("success"):
        return {
            "instance": worker_id,
            "tool": tool_key,
            "region": region,
            "error": call.get("error"),
            "variant_count": call.get("variant_count"),
        }

    metrics = score_giab(truth_vcf, truth_bed, out_vcf, ref, region, chrom)
    if not metrics:
        return {
            "instance": worker_id,
            "tool": tool_key,
            "region": region,
            "error": "hap.py scoring failed",
            "variant_count": call.get("variant_count"),
        }
    numeric = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
    breakdown_fn = getattr(AdvancedScorer, "compute_breakdown", None)
    score_breakdown = breakdown_fn(numeric) if breakdown_fn else None
    return {
        "instance": worker_id,
        "tool": tool_key,
        "region": region,
        "score": round(float(metrics.get("advanced_score") or 0.0), 2),
        "f1_snp": metrics.get("f1_snp"),
        "f1_indel": metrics.get("f1_indel"),
        "fp_snp": metrics.get("fp_snp"),
        "fn_snp": metrics.get("fn_snp"),
        "fp_indel": metrics.get("fp_indel"),
        "fn_indel": metrics.get("fn_indel"),
        "variant_count": call.get("variant_count"),
        "score_breakdown": score_breakdown,
        "proxy": True,
        "note": "GIAB HG002 proxy — not challenge truth",
        "cached": bool(call.get("metadata", {}).get("reused_vcf")),
    }
