"""Calibrate GATK config for maximum concordance with GIAB HG002 truth VCF.

Private only — outputs tuning/private/giab_gt_baseline.conf.
Never touches configs/gatk.conf unless explicitly requested elsewhere.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tuning.giab.calibrate import (
    GIAB_SEARCH_BASE,
    QUICK_GRID,
    REFINED_GRID,
    FULL_GRID,
    _combo_label,
    _grid_combos,
    _run_gatk,
    _score_giab,
    write_private_baseline,
)
from tuning.giab.data import asset_path, ensure_truth_assets, prepare_all, reference_for_chrom
from tuning.giab.paths import (
    GIAB_CALIBRATION_JSON,
    GIAB_VCF_DIR,
    MINING_GATK_CONF,
    MINOS_GIAB_REGIONS,
    PRIVATE_DIR,
)
from tuning.giab.paths import GIAB_DIR

logger = logging.getLogger(__name__)

GIAB_GT_BASELINE_CONF = PRIVATE_DIR / "giab_gt_baseline.conf"
GIAB_GT_CALIBRATION_JSON = PRIVATE_DIR / "giab_gt_calibration.json"


def gt_concordance_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize hap.py metrics as GIAB truth concordance."""
    fp_snp = float(metrics.get("fp_snp") or 0)
    fn_snp = float(metrics.get("fn_snp") or 0)
    fp_indel = float(metrics.get("fp_indel") or 0)
    fn_indel = float(metrics.get("fn_indel") or 0)
    tp_snp = float(metrics.get("tp_snp") or metrics.get("snp_tp") or 0)
    tp_indel = float(metrics.get("tp_indel") or metrics.get("indel_tp") or 0)
    f1_snp = float(metrics.get("f1_snp") or 0)
    f1_indel = float(metrics.get("f1_indel") or 0)

    eval_errors = fp_snp + fn_snp + fp_indel + fn_indel
    truth_eval = tp_snp + fn_snp + tp_indel + fn_indel
    concordance = 1.0 - (eval_errors / truth_eval) if truth_eval > 0 else 0.0

    return {
        "fp_snp": fp_snp,
        "fn_snp": fn_snp,
        "fp_indel": fp_indel,
        "fn_indel": fn_indel,
        "eval_errors": eval_errors,
        "truth_eval_variants": truth_eval,
        "concordance_pct": round(concordance * 100, 3),
        "f1_snp": f1_snp,
        "f1_indel": f1_indel,
        "weighted_f1": float(metrics.get("weighted_f1") or (f1_snp + f1_indel) / 2),
    }


def gt_rank_key(summary: Dict[str, Any]) -> Tuple[float, float, float]:
    """Sort key: fewer eval errors, higher concordance, higher weighted F1."""
    return (
        -float(summary.get("eval_errors") or 9999),
        float(summary.get("concordance_pct") or 0),
        float(summary.get("weighted_f1") or 0),
    )


def _aggregate_gt_summaries(region_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not region_rows:
        return {"eval_errors": 9999, "concordance_pct": 0.0, "weighted_f1": 0.0}
    normalized: List[Dict[str, Any]] = []
    for r in region_rows:
        if "error" in r:
            continue
        row = dict(r)
        if "eval_errors" not in row:
            row = gt_concordance_metrics(row)
        normalized.append(row)
    if not normalized:
        return {"eval_errors": 9999, "concordance_pct": 0.0, "weighted_f1": 0.0}
    n = len(normalized)
    return {
        "fp_snp": sum(r.get("fp_snp", 0) for r in normalized),
        "fn_snp": sum(r.get("fn_snp", 0) for r in normalized),
        "fp_indel": sum(r.get("fp_indel", 0) for r in normalized),
        "fn_indel": sum(r.get("fn_indel", 0) for r in normalized),
        "eval_errors": sum(r.get("eval_errors", 0) for r in normalized),
        "truth_eval_variants": sum(r.get("truth_eval_variants", 0) for r in normalized),
        "concordance_pct": round(sum(r.get("concordance_pct", 0) for r in normalized) / n, 3),
        "f1_snp": round(sum(r.get("f1_snp", 0) for r in normalized) / n, 5),
        "f1_indel": round(sum(r.get("f1_indel", 0) for r in normalized) / n, 5),
        "weighted_f1": round(sum(r.get("weighted_f1", 0) for r in normalized) / n, 5),
    }


def _format_gt_conf(params: Dict[str, Any]) -> str:
    lines = [
        "# GIAB HG002 ground-truth concordance config (PRIVATE — miner does NOT use this)",
        f"# Generated {datetime.now(timezone.utc).isoformat()}",
        "# Optimized to minimize FP/FN vs NIST v4.2.1 truth VCF on HG002 BAM windows.",
        "# Mining uses configs/gatk.conf — copy values manually only when you choose.",
        "",
    ]
    for key in sorted(params.keys()):
        val = params[key]
        if isinstance(val, bool):
            lines.append(f"{key}={'true' if val else 'false'}")
        else:
            lines.append(f"{key}={val}")
    lines.append("")
    return "\n".join(lines)


def write_gt_baseline(params: Dict[str, Any]) -> Path:
    resolved = GIAB_GT_BASELINE_CONF.resolve()
    mining = MINING_GATK_CONF.resolve()
    if resolved == mining:
        raise RuntimeError("Refusing to write GIAB GT config over mining config")
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    GIAB_GT_BASELINE_CONF.write_text(_format_gt_conf(params), encoding="utf-8")
    return GIAB_GT_BASELINE_CONF


def score_params_gt_match(
    params: Dict[str, Any],
    *,
    regions: Iterable[Tuple[str, str]] = MINOS_GIAB_REGIONS,
    skip_download: bool = False,
    label_prefix: str = "gt",
) -> Dict[str, Any]:
    """Call + hap.py vs GIAB truth; return concordance summary."""
    region_list = list(regions)
    if skip_download:
        truth_vcf, truth_bed = ensure_truth_assets()
        assets = {
            "truth_vcf": truth_vcf,
            "truth_bed": truth_bed,
            "bams": {chrom: asset_path(f"bam_region_{chrom}") for chrom, _ in region_list},
        }
    else:
        assets = prepare_all(tuple(region_list))

    GIAB_VCF_DIR.mkdir(parents=True, exist_ok=True)
    label = _combo_label(params)
    region_rows: List[Dict[str, Any]] = []

    for chrom, region in region_list:
        bam = assets["bams"][chrom]
        ref = reference_for_chrom(chrom)
        out_vcf = GIAB_VCF_DIR / f"{label_prefix}_{label}_{chrom}.vcf.gz"
        call = _run_gatk(bam, ref, region, out_vcf, params)
        if not call.get("success"):
            region_rows.append({"chrom": chrom, "error": call.get("error")})
            continue
        raw = _score_giab(assets["truth_vcf"], assets["truth_bed"], out_vcf, ref, region, chrom)
        summary = gt_concordance_metrics(raw)
        summary["chrom"] = chrom
        summary["region"] = region
        summary["variant_count"] = call.get("variant_count")
        region_rows.append(summary)

    agg = _aggregate_gt_summaries([r for r in region_rows if "error" not in r])
    return {
        "label": label,
        "params": params,
        "gt_summary": agg,
        "regions": region_rows,
    }


def run_gt_calibration(
    *,
    quick: bool = False,
    refined: bool = True,
    full: bool = False,
    skip_download: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Grid-search for config that best matches GIAB truth VCF (min eval errors)."""
    if full:
        grid, mode = FULL_GRID, "full"
    elif refined:
        grid, mode = REFINED_GRID, "refined"
    else:
        grid, mode = QUICK_GRID, "quick"
    combos = _grid_combos(grid)

    if dry_run:
        return {
            "dry_run": True,
            "mode": mode,
            "objective": "giab_truth_concordance",
            "combos": len(combos),
            "output_conf": str(GIAB_GT_BASELINE_CONF),
            "mining_conf": str(MINING_GATK_CONF),
        }

    region_list = list(MINOS_GIAB_REGIONS)
    if skip_download:
        truth_vcf, truth_bed = ensure_truth_assets()
        assets = {
            "truth_vcf": truth_vcf,
            "truth_bed": truth_bed,
            "bams": {chrom: asset_path(f"bam_region_{chrom}") for chrom, _ in region_list},
        }
    else:
        assets = prepare_all(tuple(region_list))

    results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    best_key: Optional[Tuple[float, float, float]] = None

    for idx, params in enumerate(combos):
        label = _combo_label(params)
        region_rows: List[Dict[str, Any]] = []

        for chrom, region in region_list:
            bam = assets["bams"][chrom]
            ref = reference_for_chrom(chrom)
            out_vcf = GIAB_VCF_DIR / f"gt_{label}_{chrom}.vcf.gz"
            call = _run_gatk(bam, ref, region, out_vcf, params)
            if not call.get("success"):
                region_rows.append({"chrom": chrom, "error": call.get("error")})
                continue
            raw = _score_giab(assets["truth_vcf"], assets["truth_bed"], out_vcf, ref, region, chrom)
            summary = gt_concordance_metrics(raw)
            summary.update({"chrom": chrom, "region": region, "variant_count": call.get("variant_count")})
            region_rows.append(summary)
            logger.info(
                "  [%d/%d] %s %s → errors=%d conc=%.2f%% SNP_F1=%.4f",
                idx + 1,
                len(combos),
                label,
                chrom,
                int(summary["eval_errors"]),
                summary["concordance_pct"],
                summary["f1_snp"],
            )

        agg = _aggregate_gt_summaries([r for r in region_rows if "error" not in r])
        entry = {"label": label, "params": params, "gt_summary": agg, "regions": region_rows}
        results.append(entry)
        key = gt_rank_key(agg)
        if best is None or key > best_key:
            best, best_key = entry, key

    assert best is not None
    conf_path = write_gt_baseline(dict(best["params"]))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "giab_truth_concordance",
        "mode": mode,
        "combos_tested": len(combos),
        "best": best,
        "all_results": sorted(results, key=lambda r: gt_rank_key(r["gt_summary"]), reverse=True),
        "gt_baseline_conf": str(conf_path),
        "mining_conf": str(MINING_GATK_CONF.resolve()),
        "note": "Private GT config only. Miner unchanged.",
    }
    GIAB_GT_CALIBRATION_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def pick_best_from_existing_calibration(path: Path = GIAB_CALIBRATION_JSON) -> Optional[Dict[str, Any]]:
    """Re-rank a prior AdvancedScorer calibration by GIAB truth errors (no GATK re-run)."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    reranked: List[Dict[str, Any]] = []
    for entry in data.get("all_results") or []:
        rows = []
        for r in entry.get("regions") or []:
            if r.get("fp_snp") is None and r.get("fn_snp") is None:
                continue
            rows.append({
                "fp_snp": r.get("fp_snp", 0),
                "fn_snp": r.get("fn_snp", 0),
                "fp_indel": r.get("fp_indel", 0),
                "fn_indel": r.get("fn_indel", 0),
                "f1_snp": r.get("f1_snp", 0),
                "f1_indel": r.get("f1_indel", 0),
                "weighted_f1": (float(r.get("f1_snp") or 0) + float(r.get("f1_indel") or 0)) / 2,
            })
        if not rows:
            continue
        agg = _aggregate_gt_summaries(rows)
        reranked.append({**entry, "gt_summary": agg})
    if not reranked:
        return None
    reranked.sort(key=lambda r: gt_rank_key(r["gt_summary"]), reverse=True)
    best = reranked[0]
    write_gt_baseline(dict(best["params"]))
    return best
