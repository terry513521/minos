"""Fast cached GIAB proxy scoring for config-editor draft params."""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tuning.giab.paths import GIAB_RESULTS_DIR, MINOS_GIAB_REGIONS
from tuning.giab.round_verify import score_tool_on_region

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
QUICK_CACHE_DIR = GIAB_RESULTS_DIR / "quick_cache"
LAST_RESULT_DIR = GIAB_RESULTS_DIR / "quick_last"
JOBS_DIR = GIAB_RESULTS_DIR / "quick_jobs"
_MEM_CACHE_TTL = int(float(os.getenv("GIAB_QUICK_MEM_CACHE_SECONDS", "3600")))
_MEM_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_QUICK_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_ACTIVE_JOB_FUTURES: Dict[str, concurrent.futures.Future] = {}


def _normalize_param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 6)
    if isinstance(value, str):
        stripped = value.strip()
        lower = stripped.lower()
        if lower in ("true", "false"):
            return lower == "true"
        try:
            if "." in stripped or "e" in lower:
                parsed = float(stripped)
                return int(parsed) if parsed.is_integer() else round(parsed, 6)
            return int(stripped)
        except ValueError:
            return value
    return value


def normalize_giab_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Stable param dict for cache keys (27 vs 27.0, key order)."""
    return {k: _normalize_param_value(v) for k, v in sorted(params.items())}


def _cache_scope(
    *,
    quick_max_bp: Optional[int] = None,
    test_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """GIAB cache identity includes test tier — light/medium/full are separate runs."""
    from tuning.giab.test_suite import SUITE_VERSION

    max_bp = 0 if quick_max_bp is None else max(0, int(quick_max_bp))
    tier = (test_tier or "").strip().lower()
    if not tier:
        for name, bp in GIAB_QUICK_TIER_BP.items():
            if bp == max_bp:
                tier = name
                break
    return {"quick_max_bp": max_bp, "test_tier": tier, "suite_version": SUITE_VERSION}


def _params_fingerprint(
    tool: str,
    region: str,
    params: Dict[str, Any],
    *,
    quick_max_bp: Optional[int] = None,
    test_tier: Optional[str] = None,
) -> str:
    payload = {
        "tool": tool,
        "region": region,
        "params": normalize_giab_params(params),
        **_cache_scope(quick_max_bp=quick_max_bp, test_tier=test_tier),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _cache_key(
    instance_id: str,
    tool: str,
    region: str,
    params: Dict[str, Any],
    *,
    quick_max_bp: Optional[int] = None,
    test_tier: Optional[str] = None,
) -> str:
    fp = _params_fingerprint(
        tool,
        region,
        params,
        quick_max_bp=quick_max_bp,
        test_tier=test_tier,
    )
    return f"{instance_id}_{tool}_{fp}"


def _cache_path(cache_key: str) -> Path:
    return QUICK_CACHE_DIR / f"{cache_key}.json"


def _last_result_path(instance_id: str) -> Path:
    return LAST_RESULT_DIR / f"{instance_id}.json"


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _update_job(job_id: str, **fields: Any) -> Dict[str, Any]:
    path = _job_path(job_id)
    job = _read_json(path) or {"job_id": job_id}
    job.update(fields)
    job["updated_at"] = _utc_now()
    _write_json(path, job)
    instance_id = job.get("instance")
    if instance_id:
        _save_last_result(str(instance_id), job)
    return job


def resolve_test_region(region: Optional[str] = None) -> str:
    if region and str(region).strip():
        return str(region).strip()
    try:
        from tuning.fleet_status import fetch_current_round_public

        live = fetch_current_round_public()
        if live.get("region"):
            return str(live["region"])
    except Exception:
        pass
    try:
        from tuning.overnight_autotune import _pending_target_region

        pending = _pending_target_region()
        if pending:
            return pending
    except Exception:
        pass
    return MINOS_GIAB_REGIONS[0][1]


GIAB_QUICK_TIER_BP: Dict[str, int] = {
    "light": 1_000_000,
    "medium": 2_000_000,
    "full": 0,
}


def resolve_quick_max_bp(
    *,
    instance_id: str = "",
    test_tier: Optional[str] = None,
    quick_max_bp: Optional[int] = None,
) -> tuple[int, Optional[str]]:
    """Resolve slice width: explicit bp > named tier > instance/root env."""
    if quick_max_bp is not None:
        return max(0, int(quick_max_bp)), test_tier
    tier = (test_tier or "").strip().lower()
    if tier in GIAB_QUICK_TIER_BP:
        return GIAB_QUICK_TIER_BP[tier], tier
    return _quick_max_bp(instance_id), None


def _quick_max_bp(instance_id: str = "") -> int:
    raw = os.getenv("GIAB_QUICK_MAX_BP", "0")
    try:
        from tuning.instance import merged_env

        raw = merged_env(instance_id or None).get("GIAB_QUICK_MAX_BP", raw)
    except Exception:
        pass
    try:
        return max(0, int(str(raw).strip() or "0"))
    except ValueError:
        return 0


def _infer_tier_from_max_bp(max_bp: int, tier: Optional[str]) -> str:
    explicit = (tier or "").strip().lower()
    if explicit:
        return explicit
    if max_bp <= 0:
        return "full"
    for name, bp in GIAB_QUICK_TIER_BP.items():
        if bp == max_bp:
            return name
    return "light"


def resolve_quick_test_plan(
    region: str,
    instance_id: str = "",
    *,
    test_tier: Optional[str] = None,
    quick_max_bp: Optional[int] = None,
    round_id: str = "",
) -> Dict[str, Any]:
    """Build stratified GIAB quick-test windows for a round region + tier."""
    from tuning.giab.test_suite import load_or_create_suite

    full = str(region).strip()
    max_bp, tier = resolve_quick_max_bp(
        instance_id=instance_id,
        test_tier=test_tier,
        quick_max_bp=quick_max_bp,
    )
    effective_tier = _infer_tier_from_max_bp(max_bp, tier)

    if effective_tier == "full":
        suite = load_or_create_suite(full, "full", round_id)
        return {
            "regions": [full],
            "region": full,
            "region_canonical": full,
            "region_full": None,
            "quick_max_bp": max_bp,
            "test_tier": effective_tier,
            "suite": suite,
        }

    suite = load_or_create_suite(full, effective_tier, round_id)
    regions = [str(w["region"]) for w in suite["windows"]]
    canonical = str(suite["region_canonical"])
    primary = regions[0] if len(regions) == 1 else canonical
    return {
        "regions": regions,
        "region": primary,
        "region_canonical": canonical,
        "region_full": full,
        "quick_max_bp": max_bp,
        "test_tier": effective_tier,
        "suite": suite,
    }


def apply_quick_region_shrink(
    region: str,
    instance_id: str = "",
    *,
    test_tier: Optional[str] = None,
    quick_max_bp: Optional[int] = None,
    round_id: str = "",
) -> tuple[str, Optional[str], int, Optional[str]]:
    """Return canonical test region(s), full round region, and tier metadata."""
    plan = resolve_quick_test_plan(
        region,
        instance_id,
        test_tier=test_tier,
        quick_max_bp=quick_max_bp,
        round_id=round_id,
    )
    return (
        plan["region_canonical"],
        plan["region_full"],
        plan["quick_max_bp"],
        plan["test_tier"],
    )


_HAP_SUM_KEYS = (
    "tp_snp",
    "fp_snp",
    "fn_snp",
    "tp_indel",
    "fp_indel",
    "fn_indel",
    "truth_total_snp",
    "truth_total_indel",
    "query_total_snp",
    "query_total_indel",
    "overcall_penalty",
)

_HAP_WEIGHTED_KEYS = (
    ("titv_query_snp", "query_total_snp"),
    ("titv_truth_snp", "truth_total_snp"),
    ("hethom_query_snp", "query_total_snp"),
    ("hethom_truth_snp", "truth_total_snp"),
    ("hethom_query_indel", "query_total_indel"),
    ("hethom_truth_indel", "truth_total_indel"),
    ("frac_na_snp", "truth_total_snp"),
    ("frac_na_indel", "truth_total_indel"),
)


def _f1_from_counts(tp: float, fp: float, fn: float) -> float:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _metrics_from_window_row(row: Dict[str, Any]) -> Dict[str, float]:
    """Rebuild hap.py-style metrics for one GIAB window."""
    raw = row.get("hap_metrics")
    if isinstance(raw, dict) and raw:
        return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}

    breakdown = row.get("score_breakdown") or {}
    counts = breakdown.get("counts") or {}
    snp = counts.get("snp") or {}
    indel = counts.get("indel") or {}
    tp_s = float(snp.get("tp") or 0)
    fp_s = float(snp.get("fp") or 0)
    fn_s = float(snp.get("fn") or 0)
    tp_i = float(indel.get("tp") or 0)
    fp_i = float(indel.get("fp") or 0)
    fn_i = float(indel.get("fn") or 0)
    truth_s = float(snp.get("truth") or tp_s + fn_s)
    truth_i = float(indel.get("truth") or tp_i + fn_i)
    query_s = float(snp.get("called") or tp_s + fp_s)
    query_i = float(indel.get("called") or tp_i + fp_i)
    f1 = breakdown.get("f1") or {}
    precision = breakdown.get("precision") or {}
    recall = breakdown.get("recall") or {}
    return {
        "tp_snp": tp_s,
        "fp_snp": fp_s,
        "fn_snp": fn_s,
        "tp_indel": tp_i,
        "fp_indel": fp_i,
        "fn_indel": fn_i,
        "truth_total_snp": truth_s,
        "truth_total_indel": truth_i,
        "query_total_snp": query_s,
        "query_total_indel": query_i,
        "f1_snp": float(f1.get("snp") or _f1_from_counts(tp_s, fp_s, fn_s)),
        "f1_indel": float(f1.get("indel") or _f1_from_counts(tp_i, fp_i, fn_i)),
        "precision_snp": float(precision.get("snp") or 0),
        "precision_indel": float(precision.get("indel") or 0),
        "recall_snp": float(recall.get("snp") or 0),
        "recall_indel": float(recall.get("indel") or 0),
        "overcall_penalty": float(breakdown.get("overcall_penalty") or 0),
    }


def _merge_hap_metrics(rows: List[Dict[str, float]]) -> Dict[str, float]:
    """Sum hap.py counts across GIAB windows and recompute AdvancedScorer inputs."""
    from utils.scoring import AdvancedScorer

    if not rows:
        return {}
    if len(rows) == 1:
        return dict(rows[0])

    merged: Dict[str, float] = {}
    for key in _HAP_SUM_KEYS:
        merged[key] = sum(float(row.get(key) or 0) for row in rows)

    for kind in ("snp", "indel"):
        tp = merged[f"tp_{kind}"]
        fp = merged[f"fp_{kind}"]
        fn = merged[f"fn_{kind}"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        merged[f"precision_{kind}"] = precision
        merged[f"recall_{kind}"] = recall
        merged[f"f1_{kind}"] = _f1_from_counts(tp, fp, fn)

    for metric_key, weight_key in _HAP_WEIGHTED_KEYS:
        num = 0.0
        den = 0.0
        for row in rows:
            weight = float(row.get(weight_key) or 0)
            if weight <= 0:
                continue
            num += float(row.get(metric_key) or 0) * weight
            den += weight
        if den > 0:
            merged[metric_key] = num / den

    merged["advanced_score"] = AdvancedScorer.compute_advanced_score(merged)
    return merged


def _combined_score_breakdown(
    ok: List[Dict[str, Any]],
    *,
    windows_scored: int,
) -> Optional[Dict[str, Any]]:
    """AdvancedScorer breakdown from summed hap.py metrics across windows."""
    if not ok:
        return None
    from utils.scoring import AdvancedScorer

    metric_rows = [_metrics_from_window_row(row) for row in ok]
    if len(metric_rows) == 1:
        return ok[0].get("score_breakdown")

    combined = _merge_hap_metrics(metric_rows)
    if not combined:
        return None
    breakdown = AdvancedScorer.compute_breakdown(combined)
    breakdown["multi_window"] = {
        "windows_scored": windows_scored,
        "label": f"Combined sum across {windows_scored} windows",
    }
    return breakdown


def _aggregate_window_scores(
    window_results: List[Dict[str, Any]],
    *,
    expected_windows: int = 0,
) -> Dict[str, Any]:
    ok = [row for row in window_results if row.get("score") is not None and not row.get("error")]
    failed = [row for row in window_results if row.get("error") or row.get("score") is None]
    if not ok:
        err = next((row.get("error") for row in window_results if row.get("error")), "GIAB scoring failed")
        return {
            "error": err,
            "suite_windows": window_results,
            "windows_expected": expected_windows or len(window_results),
            "windows_scored": 0,
            "windows_failed": len(failed) or len(window_results),
        }

    def _avg(key: str) -> Optional[float]:
        vals = [row[key] for row in ok if row.get(key) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    def _sum_int(key: str) -> int:
        return sum(int(row.get(key) or 0) for row in ok)

    windows_expected = expected_windows or len(window_results)
    windows_scored = len(ok)
    windows_failed = len(failed)
    combined_breakdown = _combined_score_breakdown(ok, windows_scored=windows_scored)
    combined_score = None
    if combined_breakdown and combined_breakdown.get("final_score") is not None:
        combined_score = float(combined_breakdown["final_score"])
    elif len(ok) == 1:
        combined_score = float(ok[0]["score"])

    out: Dict[str, Any] = {
        "score": round(combined_score if combined_score is not None else sum(float(row["score"]) for row in ok) / len(ok), 2),
        "f1_snp": _avg("f1_snp"),
        "f1_indel": _avg("f1_indel"),
        "fp_snp": _sum_int("fp_snp"),
        "fn_snp": _sum_int("fn_snp"),
        "fp_indel": _sum_int("fp_indel"),
        "fn_indel": _sum_int("fn_indel"),
        "variant_count": _sum_int("variant_count"),
        "variant_count_per_window": [int(row.get("variant_count") or 0) for row in ok],
        "windows_expected": windows_expected,
        "windows_scored": windows_scored,
        "windows_failed": windows_failed,
        "suite_windows": window_results,
    }
    if combined_breakdown:
        out["score_breakdown"] = combined_breakdown
        if combined_breakdown.get("f1"):
            out["f1_snp"] = combined_breakdown["f1"].get("snp")
            out["f1_indel"] = combined_breakdown["f1"].get("indel")
        counts = combined_breakdown.get("counts") or {}
        if counts.get("snp"):
            out["fp_snp"] = counts["snp"].get("fp")
            out["fn_snp"] = counts["snp"].get("fn")
        if counts.get("indel"):
            out["fp_indel"] = counts["indel"].get("fp")
            out["fn_indel"] = counts["indel"].get("fn")
    if windows_expected > 1 and windows_scored < windows_expected:
        missed = [
            str(row.get("region") or "?")
            for row in failed
        ]
        out["warning"] = (
            f"Only {windows_scored}/{windows_expected} GIAB windows scored"
            + (f" — failed: {', '.join(missed)}" if missed else "")
        )
        logger.warning("GIAB partial suite: %s", out["warning"])
    return out


def giab_quick_settings(instance_id: str = "", region: Optional[str] = None) -> Dict[str, Any]:
    """Expose quick-test speed settings for UI / ops."""
    full = resolve_test_region(region)
    current = resolve_quick_test_plan(full, instance_id)
    tier_blocks: Dict[str, Any] = {}
    for name, bp in GIAB_QUICK_TIER_BP.items():
        plan = resolve_quick_test_plan(full, instance_id, test_tier=name)
        suite = plan["suite"]
        tier_blocks[name] = {
            "label": name.capitalize(),
            "quick_max_bp": bp,
            "hint": {
                "light": "~1–3 min",
                "medium": "~4–8 min",
                "full": "~10–20 min",
            }.get(name, ""),
            "region_effective": plan["region_canonical"],
            "window_count": suite.get("window_count", len(plan["regions"])),
            "windows": suite.get("windows", []),
        }
    return {
        "quick_max_bp": current["quick_max_bp"],
        "region_full": current["region_full"] or full,
        "region_effective": current["region_canonical"],
        "fast_slice": bool(current["region_full"]),
        "suite": current["suite"],
        "tiers": tier_blocks,
        "in_process_jobs": os.getenv("GIAB_QUICK_SUBPROCESS", "").strip().lower()
        not in ("1", "true", "yes", "subprocess"),
    }


def _load_disk_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    data = _read_json(_cache_path(cache_key))
    if data and data.get("status") == "done" and data.get("score") is not None:
        return data
    return None


def _save_disk_cache(cache_key: str, payload: Dict[str, Any]) -> None:
    _write_json(_cache_path(cache_key), payload)


def _save_last_result(instance_id: str, payload: Dict[str, Any]) -> None:
    _write_json(_last_result_path(instance_id), payload)


def load_last_result(instance_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(_last_result_path(instance_id))


def _lookup_cache(
    instance_id: str,
    tool: str,
    region: str,
    params: Dict[str, Any],
    *,
    quick_max_bp: Optional[int] = None,
    test_tier: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    cache_key = _cache_key(
        instance_id,
        tool,
        region,
        params,
        quick_max_bp=quick_max_bp,
        test_tier=test_tier,
    )
    now = time.time()
    mem = _MEM_CACHE.get(cache_key)
    if mem and now - mem[0] < _MEM_CACHE_TTL:
        out = dict(mem[1])
        out["cache_hit"] = True
        out["cache_layer"] = "memory"
        return out
    cached = _load_disk_cache(cache_key)
    if cached:
        _MEM_CACHE[cache_key] = (now, cached)
        out = dict(cached)
        out["cache_hit"] = True
        out["cache_layer"] = "disk"
        return out
    return None


def run_quick_test(
    instance_id: str,
    tool: str,
    region: str,
    params: Dict[str, Any],
    *,
    round_id: str = "",
    force: bool = False,
    job_id: str = "",
    region_full: str = "",
    test_tier: Optional[str] = None,
    quick_max_bp: Optional[int] = None,
) -> Dict[str, Any]:
    """Score draft params on GIAB regional BAM with disk + memory cache."""
    params = normalize_giab_params(params)
    plan = resolve_quick_test_plan(
        region_full or region,
        instance_id,
        test_tier=test_tier,
        quick_max_bp=quick_max_bp,
        round_id=round_id,
    )
    region_canonical = str(plan["region_canonical"])
    region_full = plan["region_full"] or region_full or None
    effective_max_bp = plan["quick_max_bp"]
    effective_tier = plan["test_tier"]
    regions = list(plan["regions"])
    suite = plan["suite"]

    cache_key = _cache_key(
        instance_id,
        tool,
        region_canonical,
        params,
        quick_max_bp=effective_max_bp,
        test_tier=effective_tier,
    )
    vcf_tag = _params_fingerprint(
        tool,
        region_canonical,
        params,
        quick_max_bp=effective_max_bp,
        test_tier=effective_tier,
    )

    if not force:
        cached = _lookup_cache(
            instance_id,
            tool,
            region_canonical,
            params,
            quick_max_bp=effective_max_bp,
            test_tier=effective_tier,
        )
        if cached:
            out = dict(cached)
            out["cache_hit"] = True
            if job_id:
                out["job_id"] = job_id
                out["status"] = "done"
                fields = {k: v for k, v in out.items() if k != "job_id"}
                _update_job(job_id, **fields)
                _save_last_result(instance_id, out)
            return out

    started = time.time()
    from tuning.giab.data import bam_cache_ready_for_region, prefetch_bams_for_windows

    prefetch_bams_for_windows(region_full, regions)

    if effective_tier == "full" and regions:
        try:
            from tuning.giab.scoring_assets import prepare_region_scoring_assets

            for win in regions:
                prepare_region_scoring_assets(win)
        except Exception:
            logger.debug("GIAB scoring asset prep skipped", exc_info=True)

    window_results: List[Dict[str, Any]] = []

    def _score_window(idx: int, win_region: str) -> Dict[str, Any]:
        skip_bam = bam_cache_ready_for_region(win_region)
        win_vcf_tag = f"{vcf_tag}_w{idx}" if len(regions) > 1 else vcf_tag
        try:
            return score_tool_on_region(
                tool,
                params,
                win_region,
                instance_id=instance_id,
                skip_bam_download=skip_bam,
                vcf_tag=win_vcf_tag,
                reuse_vcf=not force,
            )
        except Exception as exc:
            return {
                "instance": instance_id,
                "tool": tool,
                "region": win_region,
                "error": str(exc),
            }

    parallel_windows = (
        len(regions) > 1
        and os.getenv("GIAB_QUICK_WINDOW_PARALLEL", "1").strip().lower()
        not in ("0", "false", "no", "off")
    )
    if parallel_windows:
        workers = min(len(regions), max(1, int(os.getenv("GIAB_QUICK_WORKERS", "2"))))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_score_window, idx, win_region): idx
                for idx, win_region in enumerate(regions)
            }
            ordered: List[Optional[Dict[str, Any]]] = [None] * len(regions)
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                ordered[idx] = future.result()
            window_results = [row for row in ordered if row is not None]
    else:
        for idx, win_region in enumerate(regions):
            window_results.append(_score_window(idx, win_region))

    aggregated = _aggregate_window_scores(window_results, expected_windows=len(regions))
    elapsed_ms = int((time.time() - started) * 1000)
    payload: Dict[str, Any] = {
        "job_id": job_id or None,
        "instance": instance_id,
        "tool": tool,
        "region": region_canonical,
        "region_canonical": region_canonical,
        "test_tier": effective_tier,
        "quick_max_bp": effective_max_bp,
        "round_id": round_id or None,
        "params": params,
        "config_fingerprint": vcf_tag,
        "cache_key": cache_key,
        "suite_id": suite.get("suite_id"),
        "suite_windows": aggregated.get("suite_windows", window_results),
        "window_count": len(regions),
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "finished_at": _utc_now(),
        "elapsed_ms": elapsed_ms,
        "status": "done" if aggregated.get("score") is not None else "failed",
        "cache_hit": False,
        "proxy": True,
        "note": "GIAB HG002 proxy — not challenge truth",
    }
    if region_full:
        payload["region_full"] = region_full
    payload.update({k: v for k, v in aggregated.items() if k != "suite_windows"})
    if aggregated.get("suite_windows"):
        payload["suite_windows"] = aggregated["suite_windows"]
    if aggregated.get("error"):
        payload["status"] = "failed"
        payload["error"] = aggregated["error"]
    if aggregated.get("warning"):
        payload["warning"] = aggregated["warning"]

    if payload["status"] == "done":
        _save_disk_cache(cache_key, payload)
        _MEM_CACHE[cache_key] = (time.time(), payload)
    _save_last_result(instance_id, payload)
    if job_id:
        fields = {k: v for k, v in payload.items() if k != "job_id"}
        _update_job(job_id, **fields)
    return payload


def _list_jobs_for_instance(instance_id: str) -> List[Dict[str, Any]]:
    if not JOBS_DIR.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for path in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if row.get("instance") == instance_id:
            rows.append(row)
    return rows


def _job_process_running(job_id: str) -> bool:
    future = _ACTIVE_JOB_FUTURES.get(job_id)
    if future is not None and not future.done():
        return True
    try:
        out = subprocess.run(
            ["pgrep", "-f", f"tuning.giab.quick_test --run-job {job_id}"],
            capture_output=True,
            text=True,
        )
        return out.returncode == 0
    except Exception:
        return False


def _stale_running_job(row: Dict[str, Any]) -> bool:
    if row.get("status") not in ("queued", "running"):
        return False
    job_id = str(row.get("job_id") or "")
    if job_id and _job_process_running(job_id):
        return False
    updated = row.get("updated_at") or row.get("started_at") or ""
    if not updated:
        return True
    try:
        ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        return age.total_seconds() > 120
    except ValueError:
        return True


def active_job_for_instance(instance_id: str) -> Optional[Dict[str, Any]]:
    for row in _list_jobs_for_instance(instance_id):
        if row.get("status") in ("queued", "running"):
            if _stale_running_job(row):
                job_id = str(row.get("job_id") or "")
                if job_id:
                    _update_job(
                        job_id,
                        status="failed",
                        error="GIAB test process ended unexpectedly — retry Test GIAB",
                        finished_at=_utc_now(),
                    )
                continue
            return row
    last = load_last_result(instance_id)
    if last and last.get("status") in ("queued", "running") and last.get("job_id"):
        job = get_quick_test_job(str(last["job_id"]))
        if job and job.get("status") in ("queued", "running"):
            return job
    return None


def get_quick_test_job(job_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(_job_path(job_id))


def giab_test_config_for_download(
    instance_id: str,
    *,
    job_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return (tool, params, metadata) for a GIAB local test config download."""
    row: Optional[Dict[str, Any]]
    if job_id:
        row = get_quick_test_job(job_id)
        if not row:
            raise ValueError("Unknown GIAB test job")
        if row.get("instance") and str(row["instance"]) != instance_id:
            raise ValueError("Job belongs to another instance")
    else:
        row = load_last_result(instance_id)
        if not row:
            raise ValueError("No GIAB test result for this instance")

    params = row.get("params")
    if not isinstance(params, dict) or not params:
        raise ValueError("No config params stored for this test")
    tool = str(row.get("tool") or "gatk")
    return tool, dict(params), dict(row)


def shutdown_quick_executor() -> None:
    """Stop in-process GIAB worker threads so systemd restart is fast."""
    global _QUICK_EXECUTOR
    if _QUICK_EXECUTOR is None:
        return
    try:
        _QUICK_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    _QUICK_EXECUTOR = None


def _quick_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _QUICK_EXECUTOR
    if _QUICK_EXECUTOR is None:
        workers = max(1, int(os.getenv("GIAB_QUICK_WORKERS", "2")))
        _QUICK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="giab-quick",
        )
        atexit.register(_QUICK_EXECUTOR.shutdown, wait=False)
    return _QUICK_EXECUTOR


def _spawn_job_subprocess(job_id: str, instance_id: str) -> None:
    log_path = GIAB_RESULTS_DIR / f"quick_{instance_id}.log"
    log_f = open(log_path, "a", encoding="utf-8")
    cmd = [sys.executable, "-m", "tuning.giab.quick_test", "--run-job", job_id]
    subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _spawn_job_process(job_id: str, instance_id: str) -> None:
    """Run GIAB quick jobs in-process by default (faster cache + GPU probe reuse)."""
    mode = os.getenv("GIAB_QUICK_SUBPROCESS", "").strip().lower()
    if mode in ("1", "true", "yes", "subprocess"):
        _spawn_job_subprocess(job_id, instance_id)
        return

    def _run() -> None:
        try:
            run_job_by_id(job_id)
        except Exception:
            logger.exception("GIAB quick test thread failed for job %s", job_id)

    future = _quick_executor().submit(_run)
    _ACTIVE_JOB_FUTURES[job_id] = future

    def _clear(_f: concurrent.futures.Future) -> None:
        _ACTIVE_JOB_FUTURES.pop(job_id, None)

    future.add_done_callback(_clear)


def start_quick_test_job(
    instance_id: str,
    tool: str,
    region: str,
    params: Dict[str, Any],
    *,
    round_id: str = "",
    force: bool = False,
    test_tier: Optional[str] = None,
    quick_max_bp: Optional[int] = None,
) -> Dict[str, Any]:
    """Queue async GIAB test; return immediately (or cached result)."""
    params = normalize_giab_params(params)
    plan = resolve_quick_test_plan(
        region,
        instance_id,
        test_tier=test_tier,
        quick_max_bp=quick_max_bp,
        round_id=round_id,
    )
    region_canonical = str(plan["region_canonical"])
    region_full = plan["region_full"]
    effective_max_bp = plan["quick_max_bp"]
    effective_tier = plan["test_tier"]
    suite = plan["suite"]
    active = active_job_for_instance(instance_id)
    if active and active.get("job_id") and active.get("status") in ("queued", "running"):
        active_region = str(active.get("region_canonical") or active.get("region") or "")
        active_params = normalize_giab_params(dict(active.get("params") or {}))
        active_max_bp = active.get("quick_max_bp")
        active_tier = active.get("test_tier")
        if (
            active_region == region_canonical
            and active_params == params
            and active_max_bp == effective_max_bp
            and active_tier == effective_tier
        ):
            return dict(active)

    cache_key = _cache_key(
        instance_id,
        tool,
        region_canonical,
        params,
        quick_max_bp=effective_max_bp,
        test_tier=effective_tier,
    )
    if not force:
        cached = _lookup_cache(
            instance_id,
            tool,
            region_canonical,
            params,
            quick_max_bp=effective_max_bp,
            test_tier=effective_tier,
        )
        if cached:
            cached["job_id"] = None
            cached["status"] = "done"
            cached["params"] = params
            if region_full:
                cached["region_full"] = region_full
            cached["test_tier"] = effective_tier
            cached["quick_max_bp"] = effective_max_bp
            cached["region_canonical"] = region_canonical
            cached["suite_id"] = suite.get("suite_id")
            cached["suite_windows"] = suite.get("windows")
            return cached

    job_id = uuid.uuid4().hex[:12]
    job: Dict[str, Any] = {
        "job_id": job_id,
        "instance": instance_id,
        "tool": tool,
        "region": region_canonical,
        "region_canonical": region_canonical,
        "region_full": region_full,
        "test_tier": effective_tier,
        "quick_max_bp": effective_max_bp,
        "round_id": round_id or None,
        "suite_id": suite.get("suite_id"),
        "suite_windows": suite.get("windows"),
        "window_count": suite.get("window_count", len(plan["regions"])),
        "params": params,
        "force": force,
        "status": "queued",
        "cache_key": cache_key,
        "started_at": _utc_now(),
        "proxy": True,
        "note": "GIAB HG002 proxy — not challenge truth",
    }
    _write_json(_job_path(job_id), job)
    _save_last_result(instance_id, {**job, "status": "queued"})
    prefetch_target = region_full or str(region).strip()
    if prefetch_target:
        schedule_round_bam_prefetch(prefetch_target, round_id=round_id or "")
    _spawn_job_process(job_id, instance_id)
    return {"job_id": job_id, **job}


def run_job_by_id(job_id: str) -> int:
    job = get_quick_test_job(job_id)
    if not job:
        logger.error("GIAB quick job not found: %s", job_id)
        return 1
    _update_job(job_id, status="running", error=None, finished_at=None)
    try:
        result = run_quick_test(
            str(job["instance"]),
            str(job["tool"]),
            str(job["region"]),
            dict(job.get("params") or {}),
            round_id=str(job.get("round_id") or ""),
            force=bool(job.get("force")),
            job_id=job_id,
            region_full=str(job.get("region_full") or ""),
            test_tier=job.get("test_tier"),
            quick_max_bp=job.get("quick_max_bp"),
        )
        if result.get("status") not in ("done", "failed"):
            _update_job(job_id, status="done", **{k: v for k, v in result.items() if k != "job_id"})
    except Exception as exc:
        logger.exception("GIAB quick test failed for job %s", job_id)
        _update_job(job_id, status="failed", error=str(exc), finished_at=_utc_now())
    return 0


_prefetch_lock = threading.Lock()
_prefetch_inflight: Optional[str] = None
_prefetch_session_ready: set[str] = set()


def prefetch_round_bam(region: str, *, round_id: str = "") -> bool:
    """Download/cache the GIAB BAM slice for a round region (blocking)."""
    global _prefetch_inflight
    region = str(region or "").strip()
    if not region:
        return False

    from tuning.giab.data import bam_cache_ready_for_region, ensure_bam_for_region

    if bam_cache_ready_for_region(region):
        _prefetch_session_ready.add(region)
        return True

    with _prefetch_lock:
        if region in _prefetch_session_ready:
            return True
        if _prefetch_inflight == region:
            return True
        _prefetch_inflight = region

    try:
        logger.info(
            "GIAB BAM prefetch: %s (round=%s)",
            region,
            (round_id or "")[:19] or "—",
        )
        ensure_bam_for_region(region)
        from tuning.giab.scoring_assets import prepare_region_scoring_assets

        prepare_region_scoring_assets(region)
        with _prefetch_lock:
            _prefetch_session_ready.add(region)
        return True
    except Exception:
        logger.warning("GIAB BAM prefetch failed for %s", region, exc_info=True)
        return False
    finally:
        with _prefetch_lock:
            if _prefetch_inflight == region:
                _prefetch_inflight = None


def schedule_round_bam_prefetch(region: str, *, round_id: str = "") -> None:
    """Start a background GIAB BAM download for *region* (no-op if cached/in-flight)."""
    global _prefetch_inflight
    region = str(region or "").strip()
    if not region:
        return
    if os.getenv("GIAB_PREWARM_BAM", "1").strip().lower() in ("0", "false", "no", "off"):
        return

    from tuning.giab.data import bam_cache_ready_for_region

    if bam_cache_ready_for_region(region):
        _prefetch_session_ready.add(region)
        return

    with _prefetch_lock:
        if region in _prefetch_session_ready or _prefetch_inflight == region:
            return

    threading.Thread(
        target=prefetch_round_bam,
        args=(region,),
        kwargs={"round_id": round_id},
        name=f"giab-bam-prefetch-{region.replace(':', '_')[:28]}",
        daemon=True,
    ).start()


def _resolve_prefetch_region() -> tuple[str, str]:
    """Best-effort round region for startup BAM prefetch."""
    try:
        from tuning.fleet_status import fetch_current_round_public

        live = fetch_current_round_public()
        region = str(live.get("region") or "").strip()
        if region and live.get("status") == "open":
            return region, str(live.get("round_id") or "")
    except Exception:
        pass
    try:
        from tuning.submit_control import load_control

        pending = load_control().get("pending") or {}
        region = str(pending.get("region") or "").strip()
        if region:
            return region, str(pending.get("round_id") or "")
    except Exception:
        pass
    return "", ""


def _prefetch_round_bam() -> None:
    """Background-fetch the current round region BAM so the first GIAB test skips FTP wait."""
    region, round_id = _resolve_prefetch_region()
    if region:
        schedule_round_bam_prefetch(region, round_id=round_id)


def prewarm_giab_runtime() -> None:
    """Warm Docker images (and optional GPU probe) so the first GIAB test starts faster."""
    try:
        from tuning.giab.data import _samtools_bin, repair_giab_bam_indexes

        samtools = _samtools_bin()
        if samtools:
            logger.info("GIAB prewarm: host samtools at %s (local slice/index)", samtools)
        else:
            logger.warning(
                "GIAB prewarm: no host samtools — local BAM slices use slower docker path"
            )

        repaired = repair_giab_bam_indexes()
        if repaired:
            logger.info("GIAB prewarm: indexed %d cached BAM(s)", len(repaired))
    except Exception:
        logger.debug("GIAB BAM index repair skipped", exc_info=True)

    if os.getenv("GIAB_PREWARM_BAM", "1").strip().lower() not in ("0", "false", "no", "off"):
        try:
            import threading

            threading.Thread(target=_prefetch_round_bam, name="giab-bam-prefetch", daemon=True).start()
        except Exception:
            logger.debug("GIAB BAM prefetch skipped", exc_info=True)

    if os.getenv("GIAB_SKIP_GPU_PREWARM", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        pass
    else:
        try:
            from templates.deepvariant import _gpu_runtime

            _gpu_runtime()
        except Exception:
            logger.debug("GIAB GPU prewarm skipped", exc_info=True)

    for image in ("broadinstitute/gatk:4.5.0.0",):
        try:
            subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if os.getenv("GIAB_PREWARM_GATK_JVM", "1").strip().lower() not in (
                "0", "false", "no", "off",
            ):
                subprocess.run(
                    ["docker", "run", "--rm", image, "gatk", "--version"],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                logger.info("GIAB prewarm: GATK JVM warmed")
        except Exception:
            logger.debug("GIAB docker prewarm skipped for %s", image, exc_info=True)

    hap_image = "genonet/hap-py@sha256:03acabe84bbfba35f5a7234129d524c563f5657e1f21150a2ea2797f8e6d05f2"
    try:
        subprocess.run(
            ["docker", "image", "inspect", hap_image],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        logger.debug("GIAB hap.py prewarm skipped", exc_info=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GIAB config-editor quick test")
    parser.add_argument("--run-job", metavar="JOB_ID", help="Run a queued quick-test job")
    args = parser.parse_args(argv)
    if args.run_job:
        return run_job_by_id(args.run_job)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
