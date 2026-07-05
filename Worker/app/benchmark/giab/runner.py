"""GIAB variant calling + scoring for a single region."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict

from app.benchmark.giab.data import (
    _bam_cache_ready,
    chrom_from_region,
    ensure_bam_for_region,
    ensure_truth_assets,
    reference_for_chrom,
    regional_bam_cache_path,
)
from app.benchmark.giab.paths import giab_vcf_dir
from app.benchmark.giab.scoring import score_giab
from app.config import Settings, get_settings
from app.core.repo import ensure_repo_imports
from app.optimization.param_specs import coerce_param_value

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


def _run_gatk(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    gatk_params: Dict[str, Any],
    *,
    settings: Settings,
    runtime_conf: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    ensure_repo_imports()
    from templates.gatk import variant_call

    gatk_options = {
        key: coerce_param_value("gatk", key, value) for key, value in gatk_params.items()
    }
    runtime = _runtime_cfg(
        runtime_conf,
        settings=settings,
        tool="gatk",
        default_timeout=int(os.getenv("GIAB_GATK_TIMEOUT", "1800")),
    )
    cfg = {
        "gatk_options": gatk_options,
        **runtime,
    }
    return variant_call(bam, ref, out_vcf, region, cfg)


def _run_bcftools(
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
    from templates.bcftools import variant_call

    bcftools_options = {
        key: coerce_param_value("bcftools", key, value) for key, value in params.items()
    }
    default_threads = max(1, (os.cpu_count() or 4) - 1)
    runtime = _runtime_cfg(
        runtime_conf,
        settings=settings,
        tool="bcftools",
        default_timeout=int(os.getenv("GIAB_BCF_TIMEOUT", "1800")),
    )
    if not (runtime_conf or {}).get("threads"):
        runtime["threads"] = int(os.getenv("GIAB_BCF_THREADS", str(default_threads)))
    cfg = {
        "bcftools_options": bcftools_options,
        **runtime,
    }
    return variant_call(bam, ref, out_vcf, region, cfg)


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
    cfg = {
        "deepvariant_options": deepvariant_options,
        **runtime,
    }
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
    settings = settings or get_settings()
    tool_key = tool.lower().strip()
    if tool_key not in _SUPPORTED_TOOLS:
        return {"tool": tool_key, "error": f"unsupported tool {tool_key}"}

    ensure_repo_imports()
    from templates._common import count_variants
    from utils.scoring import AdvancedScorer

    chrom = chrom_from_region(region)
    ref = reference_for_chrom(chrom)
    truth_vcf, truth_bed = ensure_truth_assets()
    bam_path = regional_bam_cache_path(region)
    if skip_bam_download and _bam_cache_ready(bam_path):
        bam = bam_path
    else:
        bam = ensure_bam_for_region(region)

    slug = _vcf_slug(instance_id or settings.name, tool_key, region, vcf_tag)
    out_vcf = giab_vcf_dir() / f"benchmark_{slug}.vcf.gz"
    giab_vcf_dir().mkdir(parents=True, exist_ok=True)

    if reuse_vcf and out_vcf.exists():
        call = {
            "success": True,
            "variant_count": count_variants(out_vcf),
            "metadata": {"reused_vcf": True},
        }
    elif tool_key == "gatk":
        call = _run_gatk(
            bam, ref, region, out_vcf, params, settings=settings, runtime_conf=runtime_conf
        )
    elif tool_key == "deepvariant":
        call = _run_deepvariant(
            bam, ref, region, out_vcf, params, settings=settings, runtime_conf=runtime_conf
        )
    else:
        call = _run_bcftools(
            bam, ref, region, out_vcf, params, settings=settings, runtime_conf=runtime_conf
        )

    if not call.get("success"):
        return {
            "instance": instance_id or settings.name,
            "tool": tool_key,
            "region": region,
            "error": call.get("error"),
            "variant_count": call.get("variant_count"),
        }

    metrics = score_giab(truth_vcf, truth_bed, out_vcf, ref, region, chrom)
    if not metrics:
        return {
            "instance": instance_id or settings.name,
            "tool": tool_key,
            "region": region,
            "error": "hap.py scoring failed",
            "variant_count": call.get("variant_count"),
        }
    numeric = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
    breakdown_fn = getattr(AdvancedScorer, "compute_breakdown", None)
    score_breakdown = breakdown_fn(numeric) if breakdown_fn else None
    return {
        "instance": instance_id or settings.name,
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
