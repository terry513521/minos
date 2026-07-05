"""GIAB grid-search calibration → tuning/private/giab_baseline.conf only."""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tuning.giab.data import prepare_all, reference_for_chrom
from tuning.giab.paths import (
    GIAB_BASELINE_CONF,
    GIAB_CALIBRATION_JSON,
    GIAB_README,
    GIAB_RESULTS_DIR,
    GIAB_VCF_DIR,
    MINING_GATK_CONF,
    MINOS_GIAB_REGIONS,
    PRIVATE_DIR,
)
from tuning.presets import COMPETITIVE_RECALL_BASELINE, MINOS_BASELINE

logger = logging.getLogger(__name__)

# Starting point for search — competitive recall tuned for GIAB/Minos PCR-free BAMs.
GIAB_SEARCH_BASE: Dict[str, Any] = {
    **MINOS_BASELINE,
    **COMPETITIVE_RECALL_BASELINE,
    "pcr_indel_model": "NONE",
    "sample_ploidy": 2,
    "emit_ref_confidence": "NONE",
    "dont_use_soft_clipped_bases": False,
    "min_pruning": 2,
    "max_alternate_alleles": 6,
    "pruning_lod_threshold": 2.302585,
    "max_reads_per_alignment_start": 50,
    "phred_scaled_global_read_mismapping_rate": 45,
    "heterozygosity": 0.001,
    "indel_heterozygosity": 0.000144,
    "base_quality_score_threshold": 18,
    "contamination_fraction_to_filter": 0,
    "min_assembly_region_size": 50,
    "max_assembly_region_size": 300,
}

QUICK_GRID: Dict[str, Tuple[Any, ...]] = {
    "standard_min_confidence_threshold_for_calling": (29.0, 31.0, 32.0),
    "min_mapping_quality_score": (22, 24),
}

FULL_GRID: Dict[str, Tuple[Any, ...]] = {
    "standard_min_confidence_threshold_for_calling": (28.0, 29.0, 30.0, 31.0, 32.0, 33.0),
    "min_mapping_quality_score": (20, 22, 24),
    "active_probability_threshold": (0.0004, 0.0007),
    "max_num_haplotypes_in_population": (128, 256),
}

REFINED_GRID: Dict[str, Tuple[Any, ...]] = {
    "standard_min_confidence_threshold_for_calling": (29.0, 30.0, 31.0, 32.0, 33.0, 34.0),
    "min_mapping_quality_score": (22, 24, 26),
    "active_probability_threshold": (0.0004, 0.0007),
    "max_num_haplotypes_in_population": (256,),
}


def _assert_private_output(path: Path) -> None:
    """Hard guard: never write miner production config."""
    resolved = path.resolve()
    mining = MINING_GATK_CONF.resolve()
    if resolved == mining:
        raise RuntimeError(f"Refusing to write mining config: {mining}")
    private_root = PRIVATE_DIR.resolve()
    if private_root not in resolved.parents and resolved != private_root:
        raise RuntimeError(
            f"GIAB outputs must stay under {private_root}, got {resolved}"
        )


def _format_conf(params: Dict[str, Any]) -> str:
    lines = [
        "# GIAB local calibration baseline (PRIVATE — not used by miner)",
        f"# Generated {datetime.now(timezone.utc).isoformat()}",
        "# Apply manually to configs/gatk.conf only when you choose to.",
        "# Miner continues using configs/gatk.conf until you copy values yourself.",
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


def write_private_baseline(params: Dict[str, Any], path: Path = GIAB_BASELINE_CONF) -> Path:
    _assert_private_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_conf(params), encoding="utf-8")
    return path


def _grid_combos(grid: Dict[str, Tuple[Any, ...]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    combos: List[Dict[str, Any]] = []
    for values in itertools.product(*(grid[k] for k in keys)):
        combo = dict(GIAB_SEARCH_BASE)
        for k, v in zip(keys, values):
            combo[k] = v
        combos.append(combo)
    return combos


def _giab_env(instance_id: str = "") -> Dict[str, str]:
    if instance_id:
        try:
            from tuning.instance import merged_env

            return merged_env(instance_id)
        except Exception:
            pass
    return dict(os.environ)


def _giab_cpu_threads(instance_id: str = "", default: int = 8) -> int:
    import os

    env = _giab_env(instance_id)
    raw = (
        env.get("GIAB_GATK_THREADS")
        or env.get("GIAB_THREADS")
        or env.get("MINER_NUM_THREADS")
        or str(os.cpu_count() or default)
    )
    try:
        requested = int(str(raw).strip())
    except ValueError:
        requested = default
    return max(1, min(requested, os.cpu_count() or requested))


def _giab_gatk_memory_gb(instance_id: str = "", default: int = 8) -> int:
    import os

    env = _giab_env(instance_id)
    mem_raw = (env.get("GIAB_GATK_MEMORY_GB") or env.get("MINER_GATK_MEMORY_GB") or "").strip()
    if mem_raw.isdigit():
        requested = max(2, int(mem_raw))
    else:
        requested = default
        try:
            total_mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            requested = max(default, int(total_mem_bytes / (1024**3)) - 2)
        except (ValueError, OSError, AttributeError):
            pass
    try:
        total_mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        cap = max(2, int(total_mem_bytes / (1024**3)) - 2)
        return min(requested, cap)
    except (ValueError, OSError, AttributeError):
        return requested


def _giab_gatk_java_options(threads: int, memory_gb: int) -> str:
    """Quality-neutral JVM tuning for GIAB GATK (same HC algorithm, faster IO/GC)."""
    import os

    extra = (os.getenv("GIAB_GATK_JAVA_EXTRA") or "").strip()
    if extra:
        return f"-Xmx{memory_gb}g {extra}"
    return (
        f"-Xmx{memory_gb}g "
        f"-XX:+UseParallelGC "
        f"-XX:ParallelGCThreads={threads} "
        f"-Dsamjdk.use_async_io_read=true "
        f"-Dsamjdk.buffer_size=4194304"
    )


def _run_gatk(
    bam: Path,
    ref: Path,
    region: str,
    out_vcf: Path,
    gatk_params: Dict[str, Any],
    *,
    instance_id: str = "",
) -> Dict[str, Any]:
    import os
    from templates.gatk import variant_call
    from tuning.config_manager import coerce_gatk_param_types
    from tuning.portfolio_coordinator import _apply_gatk_speed_caps

    env = _giab_env(instance_id)
    gatk_options = coerce_gatk_param_types(gatk_params)
    speed_cap = (
        env.get("GIAB_GATK_SPEED_CAP") or os.getenv("GIAB_GATK_SPEED_CAP", "0")
    ).strip().lower()
    if speed_cap not in ("0", "false", "no", "off"):
        gatk_options = _apply_gatk_speed_caps(gatk_options, instance_id=instance_id)
    cfg = {
        "gatk_options": gatk_options,
        "threads": _giab_cpu_threads(instance_id),
        "timeout": int(env.get("GIAB_GATK_TIMEOUT") or os.getenv("GIAB_GATK_TIMEOUT", "1800")),
        "memory_gb": _giab_gatk_memory_gb(instance_id),
        "java_options": _giab_gatk_java_options(
            _giab_cpu_threads(instance_id),
            _giab_gatk_memory_gb(instance_id),
        ),
    }
    return variant_call(bam, ref, out_vcf, region, cfg)


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


def _score_giab(
    truth_vcf: Path,
    truth_bed: Path,
    query_vcf: Path,
    ref: Path,
    region: str,
    chrom: str,
    *,
    use_metrics_cache: bool = True,
) -> Dict[str, float]:
    from tuning.giab.scoring_assets import (
        cached_confident_bed_for_region,
        cached_truth_vcf_for_region,
        giab_hap_threads,
    )
    from tuning.giab.data import ensure_sdf
    from utils.scoring import AdvancedScorer, HappyScorer

    if use_metrics_cache:
        cached = _load_hap_metrics_cache(query_vcf, region)
        if cached:
            return dict(cached)

    sdf = ensure_sdf(chrom)
    sliced_truth = cached_truth_vcf_for_region(region)
    sliced_bed = cached_confident_bed_for_region(region)
    metrics = HappyScorer().score_vcf(
        truth_vcf=str(sliced_truth),
        query_vcf=str(query_vcf),
        reference_fasta=str(ref),
        confident_bed=str(sliced_bed),
        region=region,
        reference_sdf=str(sdf),
        threads=giab_hap_threads(),
        skip_truth_slice=True,
        skip_bed_subset=True,
    )
    if not metrics:
        return {"advanced_score": 0.0, "f1_snp": 0.0, "f1_indel": 0.0}
    score = AdvancedScorer.compute_advanced_score(metrics)
    metrics["advanced_score"] = score
    if use_metrics_cache:
        _save_hap_metrics_cache(query_vcf, region, metrics)
    return metrics


def _combo_label(params: Dict[str, Any]) -> str:
    conf = params.get("standard_min_confidence_threshold_for_calling")
    mq = params.get("min_mapping_quality_score")
    apt = params.get("active_probability_threshold")
    hap = params.get("max_num_haplotypes_in_population")
    return f"conf{conf}_mq{mq}_apt{apt}_hap{hap}"


def apply_mining_config(params: Dict[str, Any]) -> Path:
    """Write best GIAB params to configs/gatk.conf (with backup)."""
    from tuning.config_manager import save_gatk_config

    return save_gatk_config(params, backup=True)


def score_config_on_giab(
    params: Dict[str, Any],
    *,
    regions: Iterable[Tuple[str, str]] = MINOS_GIAB_REGIONS,
    skip_download: bool = False,
) -> Dict[str, Any]:
    """Score a single config on GIAB Minos-like windows (no grid search)."""
    region_list = list(regions)
    if skip_download:
        from tuning.giab.data import asset_path, ensure_truth_assets

        truth_vcf, truth_bed = ensure_truth_assets()
        assets = {
            "truth_vcf": truth_vcf,
            "truth_bed": truth_bed,
            "bams": {chrom: asset_path(f"bam_region_{chrom}") for chrom, _ in region_list},
        }
    else:
        assets = prepare_all(tuple(region_list))

    region_details: List[Dict[str, Any]] = []
    scores: List[float] = []
    for chrom, region in region_list:
        bam = assets["bams"][chrom]
        ref = reference_for_chrom(chrom)
        label = _combo_label(params)
        out_vcf = GIAB_VCF_DIR / f"verify_{label}_{chrom}.vcf.gz"
        GIAB_VCF_DIR.mkdir(parents=True, exist_ok=True)
        call = _run_gatk(bam, ref, region, out_vcf, params)
        if not call.get("success"):
            scores.append(0.0)
            region_details.append({"chrom": chrom, "error": call.get("error")})
            continue
        metrics = _score_giab(
            assets["truth_vcf"], assets["truth_bed"], out_vcf, ref, region, chrom
        )
        score = float(metrics.get("advanced_score") or 0.0)
        scores.append(score)
        region_details.append({
            "chrom": chrom,
            "region": region,
            "score": round(score, 2),
            "f1_snp": metrics.get("f1_snp"),
            "f1_indel": metrics.get("f1_indel"),
            "fp_snp": metrics.get("fp_snp"),
            "fn_snp": metrics.get("fn_snp"),
            "variant_count": call.get("variant_count"),
        })
    avg = sum(scores) / max(len(scores), 1)
    return {
        "label": _combo_label(params),
        "params": params,
        "avg_score": round(avg, 3),
        "regions": region_details,
    }


def run_calibration(
    *,
    quick: bool = True,
    full: bool = False,
    refined: bool = False,
    regions: Iterable[Tuple[str, str]] = MINOS_GIAB_REGIONS,
    skip_download: bool = False,
    dry_run: bool = False,
    apply_mining: bool = False,
) -> Dict[str, Any]:
    """
    Grid-search GATK params on GIAB HG002 Minos-like windows.

    Writes ONLY to tuning/private/ — never touches configs/gatk.conf.
    """
    if full:
        grid = FULL_GRID
        mode = "full"
    elif refined:
        grid = REFINED_GRID
        mode = "refined"
    else:
        grid = QUICK_GRID
        mode = "quick"
    combos = _grid_combos(grid)
    region_list = list(regions)

    logger.info(
        "GIAB calibration: %d combos × %d regions (%s)",
        len(combos),
        len(region_list),
        mode,
    )

    if dry_run:
        return {
            "dry_run": True,
            "combos": len(combos),
            "regions": [r[1] for r in region_list],
            "suggested_baseline": dict(GIAB_SEARCH_BASE),
        }

    if not skip_download:
        assets = prepare_all(tuple(region_list))
    else:
        from tuning.giab.data import asset_path, ensure_truth_assets

        truth_vcf, truth_bed = ensure_truth_assets()
        assets = {
            "truth_vcf": truth_vcf,
            "truth_bed": truth_bed,
            "bams": {chrom: asset_path(f"bam_region_{chrom}") for chrom, _ in region_list},
        }

    GIAB_VCF_DIR.mkdir(parents=True, exist_ok=True)
    GIAB_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None

    for combo_idx, params in enumerate(combos):
        label = _combo_label(params)
        region_scores: List[float] = []
        region_details: List[Dict[str, Any]] = []

        for chrom, region in region_list:
            bam = assets["bams"][chrom]
            ref = reference_for_chrom(chrom)
            out_vcf = GIAB_VCF_DIR / f"{label}_{chrom}.vcf.gz"

            if not bam.exists():
                raise FileNotFoundError(
                    f"Regional BAM missing: {bam}. Run without --skip-download first."
                )

            call = _run_gatk(bam, ref, region, out_vcf, params)
            if not call.get("success"):
                logger.warning("GATK failed %s %s: %s", label, chrom, call.get("error"))
                region_scores.append(0.0)
                region_details.append({"chrom": chrom, "error": call.get("error")})
                continue

            metrics = _score_giab(
                assets["truth_vcf"],
                assets["truth_bed"],
                out_vcf,
                ref,
                region,
                chrom,
            )
            score = float(metrics.get("advanced_score") or 0.0)
            region_scores.append(score)
            region_details.append({
                "chrom": chrom,
                "region": region,
                "score": round(score, 2),
                "f1_snp": metrics.get("f1_snp"),
                "f1_indel": metrics.get("f1_indel"),
                "fp_snp": metrics.get("fp_snp"),
                "fn_snp": metrics.get("fn_snp"),
                "variant_count": call.get("variant_count"),
            })
            logger.info(
                "  [%d/%d] %s %s → %.1f (SNP F1=%.3f)",
                combo_idx + 1,
                len(combos),
                label,
                chrom,
                score,
                float(metrics.get("f1_snp") or 0),
            )

        avg_score = sum(region_scores) / max(len(region_scores), 1)
        entry = {
            "label": label,
            "params": params,
            "avg_score": round(avg_score, 3),
            "regions": region_details,
        }
        results.append(entry)
        if best is None or avg_score > float(best["avg_score"]):
            best = entry

    assert best is not None
    best_params = dict(best["params"])
    best_path = write_private_baseline(best_params)
    mining_path: Optional[str] = None
    if apply_mining:
        mining_conf = apply_mining_config(best_params)
        mining_path = str(mining_conf.resolve())
        logger.info("Applied best params to mining config: %s", mining_path)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "regions": [r[1] for r in region_list],
        "combos_tested": len(combos),
        "best": best,
        "all_results": sorted(results, key=lambda r: r["avg_score"], reverse=True),
        "baseline_conf": str(best_path),
        "mining_conf": mining_path,
        "mining_conf_untouched": None if mining_path else str(MINING_GATK_CONF.resolve()),
        "note": (
            f"Applied to configs/gatk.conf: {mining_path}"
            if mining_path
            else "Private GIAB baseline only — pass --apply-mining to update configs/gatk.conf."
        ),
    }

    _assert_private_output(GIAB_CALIBRATION_JSON)
    GIAB_CALIBRATION_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_readme()
    return report


def _write_readme() -> None:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    GIAB_README.write_text(
        """# Private tuning data (not used by miner)

This folder is **isolated** from production mining:

| File | Purpose |
|------|---------|
| `giab_baseline.conf` | Best GATK params from local GIAB calibration (AdvancedScorer) |
| `giab_gt_baseline.conf` | Best params vs **GIAB truth VCF** concordance (min FP/FN) |
| `giab_calibration.json` | Full grid-search results |
| `giab_gt_calibration.json` | GT concordance grid results |
| `giab/` | Downloaded GIAB BAM slices, truth VCF, run outputs |

The miner reads **`configs/gatk.conf`** only. Nothing here is loaded automatically.

### GIAB truth VCF matching (private)

```bash
# Grid-search for config closest to GIAB HG002 truth VCF
python -m tuning.giab --gt-match --refined --skip-download

# Verify a private GT config (does not touch mining)
python -m tuning.giab --gt-verify --config tuning/private/giab_gt_baseline.conf
```

To adopt the GIAB baseline manually:

```bash
# Review diff first
diff configs/gatk.conf tuning/private/giab_baseline.conf

# Copy when ready (stops miner first recommended)
cp tuning/private/giab_baseline.conf configs/gatk.conf
pm2 restart minos-miner
```

Re-run calibration:

```bash
python -m tuning.giab.calibrate --quick    # ~12 GATK runs
python -m tuning.giab.calibrate --full     # larger grid
```
""",
        encoding="utf-8",
    )


def _write_fallback_baseline() -> Path:
    """Write theory-based GIAB start when calibration cannot run yet."""
    params = dict(GIAB_SEARCH_BASE)
    return write_private_baseline(params)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="GIAB local calibration — grid-search GATK params on HG002 Minos windows",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Small grid (6 combos)")
    mode.add_argument("--refined", action="store_true", help="Medium grid around winner (36 combos)")
    mode.add_argument("--full", action="store_true", help="Large grid (72 combos)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    parser.add_argument("--skip-download", action="store_true", help="Use cached GIAB data")
    parser.add_argument(
        "--apply-mining",
        action="store_true",
        help="Write best result to configs/gatk.conf (with backup)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Score current configs/gatk.conf on GIAB (no grid search)",
    )
    parser.add_argument(
        "--region",
        default="",
        help="Genomic region for --verify (e.g. chr21:32534965-37534965); default: both Minos GIAB windows",
    )
    parser.add_argument(
        "--gt-match",
        action="store_true",
        help="Optimize for GIAB truth VCF concordance → tuning/private/giab_gt_baseline.conf (miner untouched)",
    )
    parser.add_argument(
        "--gt-verify",
        action="store_true",
        help="Score a config vs GIAB truth (default: giab_gt_baseline.conf, or --config PATH)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="Config path for --gt-verify (default: tuning/private/giab_gt_baseline.conf)",
    )
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Write competitive GIAB starting baseline without running GATK",
    )
    args = parser.parse_args(argv)

    if args.gt_match:
        from tuning.giab.gt_match import pick_best_from_existing_calibration, run_gt_calibration

        if args.dry_run:
            report = run_gt_calibration(
                quick=not (args.full or args.refined),
                full=args.full,
                refined=args.refined or (not args.full and not args.quick),
                skip_download=args.skip_download,
                dry_run=True,
            )
            print(json.dumps(report, indent=2))
            return 0

        instant = pick_best_from_existing_calibration()
        if instant and not args.full:
            gs = instant["gt_summary"]
            print(f"Re-ranked existing runs: best={instant['label']}")
            print(f"  eval_errors={gs['eval_errors']} concordance={gs['concordance_pct']}%")

        report = run_gt_calibration(
            quick=args.quick and not args.refined and not args.full,
            full=args.full,
            refined=args.refined or (not args.full and not args.quick),
            skip_download=args.skip_download,
        )
        gs = report["best"]["gt_summary"]
        print(f"\nBest GT match: {report['best']['label']}")
        print(f"  eval_errors={gs['eval_errors']} (FP+FN vs GIAB truth)")
        print(f"  concordance={gs['concordance_pct']}%  SNP_F1={gs['f1_snp']}  INDEL_F1={gs['f1_indel']}")
        print(f"  Private config: {report['gt_baseline_conf']}")
        print(f"  Mining config unchanged: {MINING_GATK_CONF}")
        return 0

    if args.gt_verify:
        from tuning.config_manager import _load_from_path
        from tuning.giab.gt_match import GIAB_GT_BASELINE_CONF, score_params_gt_match

        cfg_path = Path(args.config) if args.config else GIAB_GT_BASELINE_CONF
        if not cfg_path.exists():
            print(f"Config not found: {cfg_path}", file=sys.stderr)
            return 1
        result = score_params_gt_match(
            _load_from_path(cfg_path), skip_download=args.skip_download, label_prefix="gtverify"
        )
        print(json.dumps(result, indent=2))
        gs = result["gt_summary"]
        print(f"\nGIAB truth concordance: {gs['concordance_pct']}%  errors={gs['eval_errors']}")
        return 0

    if args.verify:
        from tuning.config_manager import load_gatk_config
        from tuning.giab.data import chrom_from_region
        from tuning.giab.paths import MINOS_GIAB_REGIONS

        if args.region:
            chrom = chrom_from_region(args.region)
            regions = [(chrom, args.region)]
        else:
            regions = MINOS_GIAB_REGIONS

        result = score_config_on_giab(
            load_gatk_config(),
            regions=regions,
            skip_download=args.skip_download,
        )
        print(json.dumps(result, indent=2))
        print(f"\nGIAB avg score @ {args.region or 'default windows'}: {result['avg_score']}")
        return 0

    if args.init_only:
        path = _write_fallback_baseline()
        print(f"Wrote private baseline (no GATK runs): {path}")
        return 0

    try:
        report = run_calibration(
            quick=not (args.full or args.refined),
            full=args.full,
            refined=args.refined,
            skip_download=args.skip_download,
            dry_run=args.dry_run,
            apply_mining=args.apply_mining,
        )
    except Exception as exc:
        logger.error("Calibration failed: %s", exc)
        path = _write_fallback_baseline()
        print(f"\nCalibration failed — wrote fallback baseline to {path}", file=sys.stderr)
        return 1

    if report.get("dry_run"):
        print(json.dumps(report, indent=2))
        return 0

    print(f"\nBest avg score: {report['best']['avg_score']}")
    print(f"Best label: {report['best']['label']}")
    print(f"Private baseline: {report['baseline_conf']}")
    print(f"Full report: {GIAB_CALIBRATION_JSON}")
    if report.get("mining_conf"):
        print(f"Mining config updated: {report['mining_conf']}")
    else:
        print("Mining config unchanged (use --apply-mining to update)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
