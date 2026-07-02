from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.assets import WORKER_ROOT, resolve_assets
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkResult:
    success: bool
    score: float
    raw_score: float
    conf: dict[str, Any]
    variant_count: int
    error: str | None = None
    cached: bool = False


def get_repo_root() -> Path:
    env_root = os.getenv("WORKER_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return WORKER_ROOT.parent


def ensure_repo_imports() -> Path:
    root = get_repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    templates_dir = root / "templates"
    if not templates_dir.exists():
        raise RuntimeError(
            f"Minos templates not found at {templates_dir}. "
            "Set WORKER_REPO_ROOT to the minos_subnet checkout."
        )
    return root


def _conf_key(conf: dict[str, Any]) -> str:
    return json.dumps(conf, sort_keys=True, default=str)


def _coerce_tool_options(conf: dict[str, Any], tool: str) -> None:
    from app.param_specs import coerce_param_value

    key = f"{tool.lower().strip()}_options"
    options = conf.get(key)
    if not isinstance(options, dict):
        return
    for name, value in list(options.items()):
        options[name] = coerce_param_value(tool, name, value)


def _prepare_run_config(
    conf: dict[str, Any],
    *,
    settings: Settings,
    tool: str,
    gatk_pool: Any | None = None,
) -> dict[str, Any]:
    run_conf = deepcopy(conf)
    run_conf.setdefault("threads", settings.trial_threads)
    run_conf.setdefault("memory_gb", settings.trial_memory_gb)
    run_conf.setdefault("timeout", 800)
    if settings.gatk_persistent_container and tool.lower() == "gatk" and gatk_pool is not None:
        run_conf["persistent_container"] = True
        run_conf["_gatk_persistent_runner"] = gatk_pool.run_haplotype_caller
    return run_conf


def _score_vcf(
    *,
    output_vcf: Path,
    assets: Any,
    settings: Settings,
    conf: dict[str, Any],
    variant_count: int,
) -> BenchmarkResult:
    if assets.truth_vcf is None:
        truth_hint = (
            f"{settings.benchmark_truth_vcf} or datasets/truth/{assets.chromosome}.vcf.gz"
            if settings.benchmark_mode
            else f"datasets/truth/{assets.chromosome}.vcf.gz"
        )
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=variant_count,
            error=f"Truth VCF missing: {truth_hint}.",
        )

    mutations_vcf = assets.truth_vcf.parent / f"{assets.chromosome}.mutations.vcf.gz"
    mutations_path = str(mutations_vcf) if mutations_vcf.exists() else None

    if not assets.reference_sdf.exists():
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=variant_count,
            error=(
                f"Reference SDF missing: datasets/reference/{assets.chromosome}/{assets.chromosome}.sdf. "
                "Re-run ./setup.sh with WORKER_DOWNLOAD_SDF=true."
            ),
        )

    from utils.scoring import AdvancedScorer, HappyScorer

    scorer = HappyScorer()
    metrics = scorer.score_vcf(
        truth_vcf=str(assets.truth_vcf),
        query_vcf=str(output_vcf),
        reference_fasta=str(assets.reference_fasta),
        reference_sdf=str(assets.reference_sdf),
        region=assets.window,
        mutations_vcf=mutations_path,
    )
    if not metrics:
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=variant_count,
            error="hap.py scoring returned no metrics",
        )

    raw_score = float(AdvancedScorer.compute_advanced_score(metrics))
    normalized = max(0.0, min(1.0, raw_score / 100.0))
    return BenchmarkResult(
        success=True,
        score=normalized,
        raw_score=raw_score,
        conf=deepcopy(conf),
        variant_count=variant_count,
    )


def run_benchmark(
    *,
    window: str,
    tool: str,
    conf: dict[str, Any],
    work_dir: Path,
    settings: Settings | None = None,
    gatk_pool: Any | None = None,
) -> BenchmarkResult:
    settings = settings or get_settings()
    ensure_repo_imports()
    assets = resolve_assets(window, settings)

    from templates import load_template

    work_dir.mkdir(parents=True, exist_ok=True)
    output_vcf = work_dir / f"query_{uuid.uuid4().hex[:8]}.vcf.gz"
    run_conf = _prepare_run_config(conf, settings=settings, tool=tool, gatk_pool=gatk_pool)
    _coerce_tool_options(run_conf, tool)
    bam_key = str(assets.bam_path.resolve())

    cache = None
    if settings.vcf_cache_enabled:
        from app.vcf_cache import VcfCache

        cache = VcfCache(settings)
        hit = cache.lookup(window=window, tool=tool, bam_path=bam_key, conf=conf)
        if hit is not None:
            logger.info("VCF cache hit (%s) score=%.4f", hit.key[:12], hit.score)
            return BenchmarkResult(
                success=True,
                score=hit.score,
                raw_score=hit.raw_score,
                conf=deepcopy(conf),
                variant_count=hit.variant_count,
                cached=True,
            )

    template = load_template(tool.lower())
    call_result = template.variant_call(
        bam_path=assets.bam_path,
        reference_path=assets.reference_fasta,
        output_vcf_path=output_vcf,
        region=assets.window,
        config=run_conf,
    )

    if not call_result.get("success"):
        return BenchmarkResult(
            success=False,
            score=0.0,
            raw_score=0.0,
            conf=deepcopy(conf),
            variant_count=int(call_result.get("variant_count") or 0),
            error=str(call_result.get("error") or "Variant calling failed"),
        )

    variant_count = int(call_result.get("variant_count") or 0)
    result = _score_vcf(
        output_vcf=output_vcf,
        assets=assets,
        settings=settings,
        conf=conf,
        variant_count=variant_count,
    )

    if cache is not None and result.success and output_vcf.exists():
        cache.store(
            window=window,
            tool=tool,
            bam_path=bam_key,
            conf=conf,
            source_vcf=output_vcf,
            score=result.score,
            raw_score=result.raw_score,
            variant_count=result.variant_count,
        )

    return result


def conf_equals(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _conf_key(a) == _conf_key(b)
