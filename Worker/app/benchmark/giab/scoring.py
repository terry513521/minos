"""hap.py scoring — bundled vendor/tuning/giab/calibrate."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.benchmark.giab.tuning_bridge import ensure_tuning_giab


def score_giab(
    truth_vcf: Path,
    truth_bed: Path,
    query_vcf: Path,
    ref: Path,
    region: str,
    chrom: str,
    *,
    use_metrics_cache: bool = True,
) -> Optional[Dict[str, float]]:
    ensure_tuning_giab()
    from tuning.giab.calibrate import _score_giab

    metrics = _score_giab(
        truth_vcf,
        truth_bed,
        query_vcf,
        ref,
        region,
        chrom,
        use_metrics_cache=use_metrics_cache,
    )
    if not metrics:
        return None
    advanced = float(metrics.get("advanced_score") or 0.0)
    f1_snp = float(metrics.get("f1_snp") or 0.0)
    f1_indel = float(metrics.get("f1_indel") or 0.0)
    if advanced <= 0.0 and f1_snp == 0.0 and f1_indel == 0.0:
        return None
    return metrics
