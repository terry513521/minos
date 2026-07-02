"""hap.py scoring and metrics cache for GIAB benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from app.benchmark.giab.data import ensure_sdf
from app.core.repo import ensure_repo_imports


def _hap_metrics_cache_path(query_vcf: Path, region: str) -> Path:
    slug = region.replace(":", "_").replace("-", "_")
    return query_vcf.with_name(f"{query_vcf.name}.{slug}.hap_metrics.json")


def _load_hap_metrics_cache(query_vcf: Path, region: str) -> Optional[Dict[str, float]]:
    path = _hap_metrics_cache_path(query_vcf, region)
    if not path.exists() or not query_vcf.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("region") != region:
        return None
    if payload.get("query_vcf_mtime") != query_vcf.stat().st_mtime:
        return None
    metrics = payload.get("metrics")
    return metrics if isinstance(metrics, dict) else None


def _save_hap_metrics_cache(query_vcf: Path, region: str, metrics: Dict[str, float]) -> None:
    path = _hap_metrics_cache_path(query_vcf, region)
    path.write_text(
        json.dumps(
            {
                "region": region,
                "query_vcf_mtime": query_vcf.stat().st_mtime,
                "metrics": metrics,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def score_giab(
    truth_vcf: Path,
    truth_bed: Path,
    query_vcf: Path,
    ref: Path,
    region: str,
    chrom: str,
    *,
    use_metrics_cache: bool = True,
) -> Dict[str, float]:
    ensure_repo_imports()
    from utils.scoring import AdvancedScorer, HappyScorer

    if use_metrics_cache:
        cached = _load_hap_metrics_cache(query_vcf, region)
        if cached:
            return dict(cached)

    sdf = ensure_sdf(chrom)
    metrics = HappyScorer().score_vcf(
        truth_vcf=str(truth_vcf),
        query_vcf=str(query_vcf),
        reference_fasta=str(ref),
        confident_bed=str(truth_bed),
        region=region,
        reference_sdf=str(sdf),
    )
    if not metrics:
        return {"advanced_score": 0.0, "f1_snp": 0.0, "f1_indel": 0.0}
    score = AdvancedScorer.compute_advanced_score(metrics)
    metrics["advanced_score"] = score
    if use_metrics_cache:
        _save_hap_metrics_cache(query_vcf, region, metrics)
    return metrics
