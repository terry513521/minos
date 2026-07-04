"""Benchmark orchestration — GIAB scoring under Worker/datasets/."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.benchmark.conf import conf_equals, tool_params_from_conf
from app.benchmark.giab.data import chrom_from_region, reference_for_chrom, regional_bam_cache_path
from app.benchmark.giab.paths import giab_bam_dir, giab_data_dir, giab_vcf_dir
from app.benchmark.giab.runner import score_tool_on_region
from app.config import Settings, get_settings
from app.core.conf_hash import conf_fingerprint
from app.core.repo import ensure_repo_imports
from app.domain.result import BenchmarkResult
from app.paths import WORKER_ROOT, data_root

logger = logging.getLogger(__name__)

_GIAB_SUPPORTED_TOOLS = frozenset({"gatk", "bcftools", "deepvariant"})


def validate_tool_supported(tool: str) -> None:
    tool_key = tool.lower().strip()
    if tool_key not in _GIAB_SUPPORTED_TOOLS:
        raise ValueError(
            f"Tool {tool!r} is not supported by the Worker GIAB benchmark. "
            f"Supported tools: {sorted(_GIAB_SUPPORTED_TOOLS)}."
        )


def validate_benchmark_assets(window: str, settings: Settings | None = None) -> None:
    """Preflight before optimization."""
    settings = settings or get_settings()
    ensure_repo_imports()
    chrom = chrom_from_region(window.strip())
    ref = reference_for_chrom(chrom)
    if not ref.exists():
        raise FileNotFoundError(
            f"GIAB benchmark reference missing: {ref}. "
            f"Run Worker setup or place datasets/reference/{chrom}/{chrom}.fa."
        )


def benchmark_status(settings: Settings | None = None) -> dict[str, Any]:
    """Preflight summary for /health."""
    settings = settings or get_settings()
    datasets = data_root(settings.data_dir)
    out: dict[str, Any] = {
        "data_dir": str(datasets),
        "ready": False,
        "message": "",
    }
    try:
        ensure_repo_imports()
        out["giab_data_dir"] = str(giab_data_dir())
        out["giab_bam_dir"] = str(giab_bam_dir())
        out["giab_vcf_dir"] = str(giab_vcf_dir())

        chromosomes = [c.strip() for c in settings.chromosomes.split(",") if c.strip()]
        missing_refs: list[str] = []
        for chrom in chromosomes:
            ref = reference_for_chrom(chrom)
            if not ref.exists():
                missing_refs.append(str(ref))
        if missing_refs:
            out["message"] = f"Missing reference: {missing_refs[0]}"
            return out
        out["ready"] = True
        out["message"] = (
            "GIAB benchmark ready under Worker/datasets/; "
            "truth/BAM slices download on first trial if needed"
        )
    except Exception as exc:
        out["message"] = str(exc)
    return out


def _giab_result_to_benchmark(
    raw: dict[str, Any],
    *,
    conf: dict[str, Any],
    cached: bool,
) -> BenchmarkResult:
    if raw.get("error"):
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=int(raw.get("variant_count") or 0),
            error=str(raw["error"]),
            cached=cached,
        )
    if raw.get("score") is None:
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=int(raw.get("variant_count") or 0),
            error="GIAB benchmark returned no score",
            cached=cached,
        )

    raw_score = float(raw["score"])
    normalized = max(0.0, min(1.0, raw_score / 100.0))
    return BenchmarkResult(
        success=True,
        score=normalized,
        raw_score=raw_score,
        conf=deepcopy(conf),
        variant_count=int(raw.get("variant_count") or 0),
        cached=cached or bool(raw.get("cached")),
    )


def run_benchmark(
    *,
    window: str,
    tool: str,
    conf: dict[str, Any],
    work_dir: Path | None = None,
    settings: Settings | None = None,
    gatk_pool: Any | None = None,
) -> BenchmarkResult:
    """Score one config on a GIAB regional BAM (Worker-local datasets)."""
    settings = settings or get_settings()
    if gatk_pool is not None:
        logger.debug("GIAB benchmark ignores GATK persistent container pool")
    if work_dir is None:
        work_dir = WORKER_ROOT / "runs" / "_scratch"
    work_dir.mkdir(parents=True, exist_ok=True)

    tool_key = tool.lower().strip()
    if tool_key not in _GIAB_SUPPORTED_TOOLS:
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=0,
            error=f"GIAB benchmark does not support tool {tool!r}. Supported: {sorted(_GIAB_SUPPORTED_TOOLS)}",
        )

    params = tool_params_from_conf(conf, tool_key)
    vcf_tag = conf_fingerprint(window=window, tool=tool_key, conf=conf)
    skip_bam = regional_bam_cache_path(window).exists()

    try:
        raw = score_tool_on_region(
            tool_key,
            params,
            window,
            instance_id=settings.name,
            skip_bam_download=skip_bam,
            vcf_tag=vcf_tag,
            reuse_vcf=True,
            settings=settings,
            runtime_conf=conf,
        )
    except Exception as exc:
        logger.exception("GIAB benchmark failed for window=%s tool=%s", window, tool_key)
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=0,
            error=str(exc),
        )

    return _giab_result_to_benchmark(raw, conf=conf, cached=bool(raw.get("cached")))
