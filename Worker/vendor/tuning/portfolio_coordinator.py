"""Portfolio coordinator — shared autotune ledger + sequential GATK compute queue."""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from tuning.config_manager import diff_config
from tuning.instance import (
    PORTFOLIO_PROFILES,
    current_instance_id,
    discover_instances,
    list_portfolio_instances,
    wallet_credentials,
)

PORTFOLIO_DIR = Path(__file__).resolve().parent.parent / "instances" / "portfolio"
COORD_FILE = PORTFOLIO_DIR / "coordinator.json"
COMPUTE_LOCK = PORTFOLIO_DIR / "compute.lock"

STRATEGY_PARAM_OWNERSHIP: Dict[str, Tuple[str, ...]] = {
    # Balanced model — each rival explores different param dimensions (not recall/precision strategies).
    "gatk": (
        "standard_min_confidence_threshold_for_calling",
        "recover_all_dangling_branches",
        "min_dangling_branch_length",
        "assembly_region_padding",
        "active_probability_threshold",
        "adaptive_pruning_initial_error_rate",
    ),
    "newgatk": (
        "heterozygosity",
        "indel_heterozygosity",
        "active_probability_threshold",
        "adaptive_pruning_initial_error_rate",
        "pruning_lod_threshold",
        "assembly_region_padding",
        "max_num_haplotypes_in_population",
    ),
    "oldgatk": (
        "min_mapping_quality_score",
        "min_base_quality_score",
        "base_quality_score_threshold",
        "pair_hmm_gap_continuation_penalty",
        "phred_scaled_global_read_mismapping_rate",
        "max_reads_per_alignment_start",
        "max_alternate_alleles",
    ),
    "precision": (
        "min_base_quality_score",
        "min_mapping_quality_score",
        "base_quality_score_threshold",
        "contamination_fraction_to_filter",
        "min_pruning",
        "dont_use_soft_clipped_bases",
    ),
}


# Auto-submit / compute serialization order for the 20-min safety net: when
# neither hotkey was submitted manually, fencer1 tunes + submits first, then
# sliger1. Lower number = earlier in the queue. Manual submits ignore ordering.
COMPUTE_QUEUE_PRIORITY: Dict[str, int] = {"newgatk": 0, "gatk": 1, "oldgatk": 2}

RIVAL_DIVERGENCE_SCALE = float(os.getenv("RIVAL_DIVERGENCE_SCALE", "2.5"))
MIN_RIVAL_CONFIG_DISTANCE = float(os.getenv("MIN_RIVAL_CONFIG_DISTANCE", "0.08"))
# Score-adaptive divergence: strong regional baseline → gentler nudges; weak → bolder.
RIVAL_SCALE_SCORE_LO = float(os.getenv("RIVAL_SCALE_SCORE_LO", "65"))
RIVAL_SCALE_SCORE_HI = float(os.getenv("RIVAL_SCALE_SCORE_HI", "88"))
RIVAL_SCALE_AT_LO = float(os.getenv("RIVAL_SCALE_AT_LO", "1.35"))
RIVAL_SCALE_AT_HI = float(os.getenv("RIVAL_SCALE_AT_HI", "0.72"))

# Base style deltas per instance (before score / role / history weighting).
RIVAL_BASE_NUDGES: Dict[str, Dict[str, Tuple[float, int, str]]] = {
    "newgatk": {
        "heterozygosity": (0.0003, 4, "het"),
        "indel_heterozygosity": (0.00003, 6, "ihet"),
        "pruning_lod_threshold": (0.12, 3, "plod"),
        "assembly_region_padding": (20.0, 0, "pad"),
        "active_probability_threshold": (0.00025, 4, "apt"),
    },
    "gatk": {
        "standard_min_confidence_threshold_for_calling": (-0.8, 1, "conf"),
        "assembly_region_padding": (22.0, 0, "pad"),
        "active_probability_threshold": (0.00025, 4, "apt"),
        "adaptive_pruning_initial_error_rate": (-0.0003, 4, "aper"),
        "phred_scaled_global_read_mismapping_rate": (8.0, 0, "mmr"),
    },
    "oldgatk": {
        "min_base_quality_score": (1.0, 0, "mbq"),
        "min_mapping_quality_score": (1.0, 0, "mmq"),
        "base_quality_score_threshold": (1.5, 0, "bqt"),
        "pair_hmm_gap_continuation_penalty": (0.8, 0, "hmm"),
        "phred_scaled_global_read_mismapping_rate": (-4.0, 0, "mmr"),
        "max_reads_per_alignment_start": (2.0, 0, "mras"),
    },
}

TUNE_LOCK = PORTFOLIO_DIR / "tune.lock"


def _gatk_ndig(key: str) -> int:
    if key in (
        "heterozygosity",
        "indel_heterozygosity",
        "active_probability_threshold",
        "adaptive_pruning_initial_error_rate",
    ):
        return 4
    if "confidence" in key:
        return 1
    return 0


def _clamp_to_gatk_schema(key: str, value: Any) -> Any:
    """Clamp a single param to GATK whitelist min/max (not just autotune GUARD)."""
    from templates.tool_params import GATK_QUALITY_PARAMS
    from tuning.overnight_autotune import _clamp_param

    spec = GATK_QUALITY_PARAMS.get(key)
    if not spec or value is None:
        return value
    ptype = spec.get("type")
    if ptype not in ("int", "float"):
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    if ptype == "int":
        return int(round(v))
    return v


def _divergence_locked_keys() -> frozenset:
    from tuning.overnight_autotune import INVARIANTS

    return frozenset(INVARIANTS)


def _apply_guard_clamps(config: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp tunable params to empirical GUARD ranges (stricter than GATK schema)."""
    from tuning.overnight_autotune import GUARD, GUARD_KEY_MAP, _clamp, _clamp_param

    out = dict(config)
    for key, (lo_k, hi_k) in GUARD_KEY_MAP.items():
        if key not in out or key in _divergence_locked_keys():
            continue
        try:
            cur = float(out[key])
        except (TypeError, ValueError):
            continue
        ndig = _gatk_ndig(key)
        out[key] = _clamp_param(key, _clamp(cur, GUARD[lo_k], GUARD[hi_k]), ndig)
    return out


def _speed_cap_env(instance_id: str = "") -> Dict[str, str]:
    """Root + instance .env for speed-cap flags (instance wins)."""
    if instance_id:
        try:
            from tuning.instance import merged_env

            return merged_env(instance_id)
        except Exception:
            pass
    return dict(os.environ)


def _env_flag(env: Dict[str, str], key: str, default: str = "0") -> bool:
    raw = (env.get(key) or os.getenv(key) or default).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _env_int(env: Dict[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or os.getenv(key) or str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _apply_gatk_speed_caps(config: Dict[str, Any], instance_id: str = "") -> Dict[str, Any]:
    """Cap heavy assembly params so deadline autotune cannot blow GATK runtime budget."""
    env = _speed_cap_env(instance_id)
    flag = (env.get("GATK_SPEED_CAP") or os.getenv("GATK_SPEED_CAP", "1")).strip().lower()
    if flag in ("0", "false", "no", "off"):
        return config
    out = dict(config)
    hap_max = _env_int(env, "GATK_SPEED_CAP_HAP_MAX", 288)
    hap = int(out.get("max_num_haplotypes_in_population", hap_max))
    out["max_num_haplotypes_in_population"] = min(hap, hap_max)
    if _env_flag(env, "GATK_SPEED_CAP_RECOVER", "0"):
        out["recover_all_dangling_branches"] = False
    mrs_max = _env_int(env, "GATK_SPEED_CAP_READS_MAX", 36)
    mrs = int(out.get("max_reads_per_alignment_start", mrs_max))
    out["max_reads_per_alignment_start"] = min(mrs, mrs_max)
    pad_max = _env_int(env, "GATK_SPEED_CAP_PAD_MAX", 120)
    pad = int(out.get("assembly_region_padding", pad_max))
    out["assembly_region_padding"] = min(pad, pad_max)
    ars_max = _env_int(env, "GATK_SPEED_CAP_ASSEMBLY_MAX", 400)
    ars = int(out.get("max_assembly_region_size", ars_max))
    out["max_assembly_region_size"] = min(ars, ars_max)
    return out


def _config_truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def gatk_speed_limits(instance_id: str = "") -> Dict[str, Any]:
    """Expose GATK speed caps / soft targets for the tuning UI."""
    env = _speed_cap_env(instance_id)
    flag = (env.get("GATK_SPEED_CAP") or os.getenv("GATK_SPEED_CAP", "1")).strip().lower()
    enabled = flag not in ("0", "false", "no", "off")
    return {
        "enabled": enabled,
        "recover_forced_off": _env_flag(env, "GATK_SPEED_CAP_RECOVER", "0"),
        "caps": {
            "max_num_haplotypes_in_population": _env_int(env, "GATK_SPEED_CAP_HAP_MAX", 288),
            "max_reads_per_alignment_start": _env_int(env, "GATK_SPEED_CAP_READS_MAX", 36),
            "assembly_region_padding": _env_int(env, "GATK_SPEED_CAP_PAD_MAX", 120),
            "max_assembly_region_size": _env_int(env, "GATK_SPEED_CAP_ASSEMBLY_MAX", 400),
        },
        "soft_warn": {
            "max_num_haplotypes_in_population": 256,
            "max_reads_per_alignment_start": 32,
            "assembly_region_padding": 100,
            "max_assembly_region_size": 350,
            "max_alternate_alleles": 12,
        },
    }


def gatk_speed_warnings(config: Dict[str, Any], instance_id: str = "") -> List[Dict[str, Any]]:
    """Flag editor values that slow live GATK on 5 Mb rounds."""
    limits = gatk_speed_limits(instance_id)
    caps = limits["caps"]
    soft = limits["soft_warn"]
    enabled = limits["enabled"]
    out: List[Dict[str, Any]] = []

    if _config_truthy(config.get("recover_all_dangling_branches")):
        msg = "Major GATK slowdown on 5 Mb rounds (+5–10 min typical)."
        if limits["recover_forced_off"] and enabled:
            msg += " Forced false at run time by GATK_SPEED_CAP_RECOVER."
        out.append(
            {
                "param": "recover_all_dangling_branches",
                "severity": "critical",
                "value": True,
                "cap": False,
                "message": msg,
            }
        )

    numeric_rules = [
        ("max_num_haplotypes_in_population", "Haplotype population"),
        ("max_reads_per_alignment_start", "Reads per alignment start"),
        ("assembly_region_padding", "Assembly padding"),
        ("max_assembly_region_size", "Assembly region size"),
    ]
    for param, label in numeric_rules:
        raw = config.get(param)
        if raw is None:
            continue
        try:
            val = int(float(raw))
        except (TypeError, ValueError):
            continue
        cap = int(caps[param])
        warn_at = int(soft.get(param, cap))
        if val > cap:
            out.append(
                {
                    "param": param,
                    "severity": "critical",
                    "value": val,
                    "cap": cap,
                    "message": f"{label} {val} > cap {cap}."
                    + (" Clamped at GATK run." if enabled else " Speed cap disabled in .env."),
                }
            )
        elif val > warn_at:
            out.append(
                {
                    "param": param,
                    "severity": "warn",
                    "value": val,
                    "cap": cap,
                    "message": f"{label} {val} is high (fast target ≤{warn_at}).",
                }
            )

    maa = config.get("max_alternate_alleles")
    if maa is not None:
        try:
            val = int(float(maa))
            warn_at = int(soft.get("max_alternate_alleles", 12))
            if val > warn_at:
                out.append(
                    {
                        "param": "max_alternate_alleles",
                        "severity": "warn",
                        "value": val,
                        "cap": warn_at,
                        "message": f"Complex sites {val} > {warn_at} — slower on dense chr21.",
                    }
                )
        except (TypeError, ValueError):
            pass

    return out


def _sanitize_gatk_config(config: Dict[str, Any]) -> Dict[str, Any]:
    from tuning.config_manager import coerce_gatk_param_types
    from tuning.overnight_autotune import _enforce

    out = coerce_gatk_param_types(dict(config))
    for key in list(out):
        if key in _divergence_locked_keys():
            continue
        out[key] = _clamp_to_gatk_schema(key, out[key])
    out = _apply_guard_clamps(out)
    out = _apply_gatk_speed_caps(out)
    return coerce_gatk_param_types(_enforce(out))


def rival_instance_id(instance_id: str) -> Optional[str]:
    order = _queue_order()
    return next((x for x in order if x != instance_id and x != "default"), None)


def adaptive_divergence_scale_factor(anchor_score: Optional[float]) -> float:
    """Map regional opening champion score → style multiplier (high score = gentler)."""
    if anchor_score is None:
        return 1.0
    score = float(anchor_score)
    if score <= RIVAL_SCALE_SCORE_LO:
        return RIVAL_SCALE_AT_LO
    if score >= RIVAL_SCALE_SCORE_HI:
        return RIVAL_SCALE_AT_HI
    span = RIVAL_SCALE_SCORE_HI - RIVAL_SCALE_SCORE_LO
    if span <= 0:
        return 1.0
    t = (score - RIVAL_SCALE_SCORE_LO) / span
    return RIVAL_SCALE_AT_LO + t * (RIVAL_SCALE_AT_HI - RIVAL_SCALE_AT_LO)


def effective_rival_scale(
    caller_scale: float,
    anchor_score: Optional[float],
) -> float:
    return caller_scale * RIVAL_DIVERGENCE_SCALE * adaptive_divergence_scale_factor(anchor_score)


def adaptive_mirror_pull(anchor_score: Optional[float], base_pull: float = 0.45) -> float:
    """High regional baseline → smaller mirror pull; weak baseline → stronger separation."""
    factor = adaptive_divergence_scale_factor(anchor_score)
    return max(0.28, min(0.72, base_pull * factor))


def _param_nudge_weight(
    key: str,
    cur: float,
    *,
    instance_id: str,
    similar_pool: Optional[List[Any]] = None,
    champion_rec: Optional[Any] = None,
) -> float:
    """Per-param weight from role, guard headroom, baseline distance, and regional history."""
    from statistics import median
    from tuning.overnight_autotune import GUARD, GUARD_KEY_MAP, PARAM_ROLE_WEIGHT, PROVEN_BASELINE, _clamp

    weight = float(PARAM_ROLE_WEIGHT.get(key, 1.0))
    if key in _strategy_params(instance_id):
        weight *= 1.12

    lo_k, hi_k = GUARD_KEY_MAP.get(key, (None, None))
    if lo_k and hi_k:
        lo, hi = float(GUARD[lo_k]), float(GUARD[hi_k])
        span = hi - lo
        if span > 0:
            margin = min(cur - lo, hi - cur) / span
            weight *= _clamp(0.4 + margin * 0.95, 0.3, 1.0)

    default = PROVEN_BASELINE.get(key)
    if default is not None and isinstance(default, (int, float)):
        try:
            rel = abs(cur - float(default)) / max(abs(float(default)), 1e-6)
            if rel > 0.22:
                weight *= 0.88
        except (TypeError, ValueError):
            pass

    if similar_pool and champion_rec and len(similar_pool) >= 3:
        usable = [
            r
            for r in similar_pool
            if getattr(r, "config_snapshot", None) and key in r.config_snapshot
            and isinstance(r.config_snapshot.get(key), (int, float))
        ]
        if len(usable) >= 3:
            scores = sorted(float(r.score_100 or 0) for r in usable)
            p50 = scores[len(scores) // 2]
            w_vals = [
                float(r.config_snapshot[key])
                for r in usable
                if float(r.score_100 or 0) >= p50
            ]
            l_vals = [
                float(r.config_snapshot[key])
                for r in usable
                if float(r.score_100 or 0) < p50
            ]
            if len(w_vals) >= 2 and l_vals:
                spread = abs(median(w_vals) - median(l_vals))
                denom = max(abs(cur), abs(median(w_vals)), 1e-6)
                signal = _clamp(spread / denom, 0.0, 1.0)
                weight *= 0.78 + signal * 0.42

    return _clamp(weight, 0.25, 1.45)


def apply_rival_divergence(
    config: Dict[str, Any],
    instance_id: str,
    *,
    scale: float = 1.0,
    anchor_score: Optional[float] = None,
    similar_pool: Optional[List[Any]] = None,
    champion_rec: Optional[Any] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Rival-specific style nudges — scale adapts to regional opening champion score."""
    from tuning.overnight_autotune import GUARD, GUARD_KEY_MAP, _clamp, _clamp_param

    eff = effective_rival_scale(scale, anchor_score)
    out = dict(config)
    notes: List[str] = []
    score_note = (
        f"style scale {eff:.2f} (anchor {float(anchor_score):.1f})"
        if anchor_score is not None
        else f"style scale {eff:.2f}"
    )

    locked = _divergence_locked_keys()
    for key, (base_delta, ndig, label) in (RIVAL_BASE_NUDGES.get(instance_id) or {}).items():
        if key in locked or key not in out:
            continue
        cur = float(out[key])
        pw = _param_nudge_weight(
            key,
            cur,
            instance_id=instance_id,
            similar_pool=similar_pool,
            champion_rec=champion_rec,
        )
        delta = base_delta * eff * pw
        lo_k, hi_k = GUARD_KEY_MAP.get(key, (None, None))
        if lo_k and hi_k:
            new = _clamp_param(key, _clamp(cur + delta, GUARD[lo_k], GUARD[hi_k]), ndig)
        else:
            new = _clamp_param(key, cur + delta, ndig)
        new = _clamp_to_gatk_schema(key, new)
        if float(new) == cur:
            continue
        out[key] = new
        notes.append(f"rival style {label} {cur}→{new}")
    if notes:
        notes.insert(0, score_note)
    return _sanitize_gatk_config(out), notes


MIRROR_DIVERGENCE_KEYS: Tuple[str, ...] = (
    "heterozygosity",
    "indel_heterozygosity",
    "pruning_lod_threshold",
    "max_num_haplotypes_in_population",
    "standard_min_confidence_threshold_for_calling",
    "assembly_region_padding",
    "active_probability_threshold",
    "adaptive_pruning_initial_error_rate",
    "pair_hmm_gap_continuation_penalty",
    "phred_scaled_global_read_mismapping_rate",
)


def apply_mirror_divergence_from_rival(
    config: Dict[str, Any],
    instance_id: str,
    *,
    pull: float = 0.45,
    anchor_score: Optional[float] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Push config away from the other hotkey's current gatk.conf on shared levers."""
    from tuning.overnight_autotune import GUARD, GUARD_KEY_MAP, _clamp, _clamp_param

    rival = rival_instance_id(instance_id)
    if not rival:
        return config, []

    from tuning.portfolio_coordinator import load_instance_gatk_config

    rival_cfg = load_instance_gatk_config(rival)
    pull = adaptive_mirror_pull(anchor_score, pull)

    out = dict(config)
    notes: List[str] = []
    locked = _divergence_locked_keys()
    for key in MIRROR_DIVERGENCE_KEYS:
        if key in locked or key not in out or key not in rival_cfg:
            continue
        try:
            cur = float(out[key])
            riv = float(rival_cfg[key])
        except (TypeError, ValueError):
            continue
        if abs(cur - riv) < 1e-12:
            continue
        delta = pull * (cur - riv)
        if abs(delta) < 1e-12:
            continue
        lo_k, hi_k = GUARD_KEY_MAP.get(key, (None, None))
        ndig = _gatk_ndig(key)
        if lo_k and hi_k:
            new = _clamp_param(key, _clamp(cur + delta, GUARD[lo_k], GUARD[hi_k]), ndig)
        else:
            new = _clamp_param(key, cur + delta, ndig)
        new = _clamp_to_gatk_schema(key, new)
        if float(new) == cur:
            continue
        out[key] = new
        notes.append(f"mirror vs {rival} {key.split('_')[-1][:8]} {cur}→{new}")
    if notes and anchor_score is not None:
        notes.insert(0, f"mirror pull {pull:.2f} (anchor {float(anchor_score):.1f})")
    return _sanitize_gatk_config(out), notes


def load_instance_gatk_config(instance_id: str) -> Dict[str, Any]:
    """Load gatk.conf for a specific portfolio instance (ignores process env).

    Returns {} when the instance has no gatk.conf (e.g. a DeepVariant hotkey),
    so cross-tool divergence callers degrade gracefully instead of crashing.
    """
    from tuning.config_manager import load_gatk_config
    from tuning.instance import gatk_conf_path

    path = gatk_conf_path(instance_id)
    if not path.is_file():
        return {}
    return load_gatk_config(path)


def _force_spread_from_rival(
    config: Dict[str, Any],
    rival_cfg: Dict[str, Any],
    instance_id: str,
    target_dist: float,
) -> Tuple[Dict[str, Any], List[str]]:
    """Last-resort push on divergence keys until distance meets the floor."""
    from tuning.portfolio_intel import DIVERGENCE_KEYS, _config_distance
    from tuning.overnight_autotune import GUARD, GUARD_KEY_MAP, _clamp, _clamp_param

    out = dict(config)
    notes: List[str] = []
    is_explorer = instance_id == "gatk"
    signed = 1.0 if is_explorer else -1.0
    preset: Dict[str, float] = {
        "standard_min_confidence_threshold_for_calling": signed * -0.7,
        "assembly_region_padding": signed * 20.0,
        "active_probability_threshold": signed * 0.00022,
        "adaptive_pruning_initial_error_rate": signed * -0.00025,
        "heterozygosity": -signed * 0.00022,
        "indel_heterozygosity": -signed * 0.00003,
        "max_num_haplotypes_in_population": -signed * 14.0,
        "pruning_lod_threshold": -signed * 0.1,
        "pair_hmm_gap_continuation_penalty": signed * 1.0,
        "phred_scaled_global_read_mismapping_rate": signed * 5.0,
    }

    locked = _divergence_locked_keys()
    for key in DIVERGENCE_KEYS:
        if key in locked:
            continue
        if _config_distance(out, rival_cfg) >= target_dist:
            break
        if key not in out or key not in rival_cfg:
            continue
        try:
            cur = float(out[key])
            riv = float(rival_cfg[key])
        except (TypeError, ValueError):
            continue
        delta = preset.get(key, 0.0)
        if abs(delta) < 1e-12:
            if abs(cur - riv) < 1e-12:
                delta = signed * max(abs(riv), 1.0) * 0.04
            else:
                delta = 0.4 * (cur - riv)
        lo_k, hi_k = GUARD_KEY_MAP.get(key, (None, None))
        ndig = _gatk_ndig(key)
        if lo_k and hi_k:
            new = _clamp_param(key, _clamp(cur + delta, GUARD[lo_k], GUARD[hi_k]), ndig)
        else:
            new = _clamp_param(key, cur + delta, ndig)
        new = _clamp_to_gatk_schema(key, new)
        if float(new) == cur:
            continue
        out[key] = new
        notes.append(f"force spread {key.split('_')[-1][:8]} {cur}→{new}")
    return _sanitize_gatk_config(out), notes


def finalize_portfolio_config(
    config: Dict[str, Any],
    instance_id: str,
    *,
    min_distance: Optional[float] = None,
    anchor_score: Optional[float] = None,
    similar_pool: Optional[List[Any]] = None,
    champion_rec: Optional[Any] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Ensure portfolio config is typed correctly and far enough from the rival hotkey."""
    from tuning.config_manager import coerce_gatk_param_types
    from tuning.portfolio_intel import _config_distance, round_anchor_score

    if anchor_score is None:
        anchor_score = round_anchor_score()

    out = coerce_gatk_param_types(dict(config))
    notes: List[str] = []
    rival = rival_instance_id(instance_id)
    if not rival or not list_portfolio_instances():
        return out, notes

    floor = MIN_RIVAL_CONFIG_DISTANCE if min_distance is None else min_distance
    rival_cfg = load_instance_gatk_config(rival)
    if not rival_cfg:
        return out, notes

    dist = _config_distance(out, rival_cfg)
    if dist >= floor:
        return _sanitize_gatk_config(out), notes

    for attempt in range(4):
        pull = adaptive_mirror_pull(anchor_score, min(0.85, 0.45 + attempt * 0.12))
        scale = 1.5 + attempt * 0.75
        out, n1 = apply_rival_divergence(
            out,
            instance_id,
            scale=scale,
            anchor_score=anchor_score,
            similar_pool=similar_pool,
            champion_rec=champion_rec,
        )
        out, n2 = apply_mirror_divergence_from_rival(
            out, instance_id, pull=pull, anchor_score=anchor_score
        )
        notes.extend(n1 + n2)
        rival_cfg = load_instance_gatk_config(rival)
        out = coerce_gatk_param_types(out)
        dist = _config_distance(out, rival_cfg)
        if dist >= floor:
            notes.insert(0, f"rival distance enforced {dist:.3f} (min {floor:.3f})")
            return _sanitize_gatk_config(out), notes

    out, n3 = _force_spread_from_rival(out, rival_cfg, instance_id, floor)
    notes.extend(n3)
    out = coerce_gatk_param_types(out)
    dist = _config_distance(out, load_instance_gatk_config(rival))
    notes.insert(0, f"rival distance forced {dist:.3f} (target {floor:.3f})")
    out = _sanitize_gatk_config(out)
    from tuning.config_manager import validate_config

    valid, errors = validate_config(out)
    if not valid:
        notes.append(f"divergence fallback: invalid config ({errors[0] if errors else 'unknown'})")
        return _sanitize_gatk_config(config), notes
    return out, notes


_SUBMITTED_HISTORY_STATUSES = frozenset({"submitted", "scoring", "scored"})


def instance_round_submitted(instance_id: str, round_id: str) -> bool:
    """True when this hotkey's round history shows it already submitted."""
    return _instance_submitted_in_history(instance_id, round_id)


def _instance_submitted_in_history(instance_id: str, round_id: str) -> bool:
    """True when this hotkey's round history shows it already submitted."""
    from tuning.instance import bind_instance, reset_instance

    token = bind_instance(instance_id)
    try:
        from tuning.instance import instance_tool
        from tuning.score_store import get_round

        rec = get_round(round_id)
        if rec is None:
            return False
        if rec.resolved_tool() != instance_tool(instance_id):
            return False
        if rec.status in _SUBMITTED_HISTORY_STATUSES:
            return True
        return bool(rec.submitted_at)
    except Exception:
        return False
    finally:
        reset_instance(token)


def _heal_coordinator_submissions(state: Dict[str, Any], round_id: str) -> bool:
    """Backfill coordinator ``submitted`` from per-instance round history.

    Manual submits sometimes reach round_history but not coordinator.json
    (missed mark, race, or round reset). Without this, the sibling hotkey waits
    forever even though the rival already submitted.
    """
    if state.get("round_id") != round_id:
        return False
    changed = False
    for iid in discover_instances():
        inst = state["instances"].setdefault(iid, {})
        if inst.get("submitted"):
            continue
        if _instance_submitted_in_history(iid, round_id):
            inst.update(
                {
                    "submitted": True,
                    "compute_status": inst.get("compute_status") or "done",
                    "updated_at": _now_iso(),
                }
            )
            changed = True
    return changed


def _reconcile_coordinator_submissions(state: Dict[str, Any], round_id: str) -> bool:
    """Clear stale coordinator ``submitted`` when local state says the hotkey did not submit."""
    if state.get("round_id") != round_id:
        return False
    changed = False
    for iid in discover_instances():
        inst = state.get("instances", {}).get(iid)
        if not inst or not inst.get("submitted"):
            continue
        if _instance_submitted_in_history(iid, round_id):
            continue
        from tuning.instance import bind_instance, reset_instance
        from tuning.submit_control import load_control

        token = bind_instance(iid)
        try:
            pending = load_control().get("pending") or {}
        finally:
            reset_instance(token)
        # Active pending for this round means mark_submitted never ran.
        if pending.get("round_id") == round_id:
            inst["submitted"] = False
            if inst.get("compute_status") == "done":
                inst["compute_status"] = None
            inst["updated_at"] = _now_iso()
            changed = True
    return changed


def _sync_coordinator_submissions(state: Dict[str, Any], round_id: str) -> bool:
    """Heal missing marks, then drop stale submitted flags."""
    changed = _heal_coordinator_submissions(state, round_id)
    if _reconcile_coordinator_submissions(state, round_id):
        changed = True
    return changed


def _prior_tune_settled(
    inst: Dict[str, Any],
    *,
    instance_id: Optional[str] = None,
    round_id: Optional[str] = None,
) -> bool:
    """A prior rival no longer blocks our tune once it tuned OR already cleared the
    queue (e.g. submitted manually, which never records a tune_done)."""
    if inst.get("tune_done"):
        return True
    return _instance_queue_cleared(inst, instance_id=instance_id, round_id=round_id)


def _wait_prior_rival_tune(instance_id: str, round_id: Optional[str], *, timeout_seconds: int) -> None:
    """Queue-ordered autotune: later hotkeys wait for earlier rivals to finish tuning.

    A prior rival counts as settled when it has tuned OR already cleared the compute
    queue (manual submit / done / failed). Without this, a manually-submitted rival —
    which never records a tune_done — would stall the later hotkey's deadline tune for
    the full timeout.
    """
    if not round_id:
        return
    order = _queue_order()
    if instance_id not in order:
        return
    priors = order[: order.index(instance_id)]
    if not priors:
        return
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = load_coordinator()
        if state.get("round_id") not in (None, round_id):
            return
        if state.get("round_id") == round_id and _sync_coordinator_submissions(state, round_id):
            save_coordinator(state)
        instances = state.get("instances") or {}
        if all(
            _prior_tune_settled(
                instances.get(prior) or {},
                instance_id=prior,
                round_id=round_id,
            )
            for prior in priors
            if prior in discover_instances()
        ):
            return
        time.sleep(1.5)


@dataclass
class TuneSlotOutcome:
    success: bool = False


@dataclass
class ComputeSlotOutcome:
    success: bool = False
    superseded: bool = False


class RoundSuperseded(Exception):
    """Coordinator moved to a newer round while waiting in the compute queue."""

    def __init__(self, round_id: str) -> None:
        self.round_id = round_id
        super().__init__(round_id)


def _coordinator_round_active(round_id: str) -> bool:
    state = load_coordinator()
    active = state.get("round_id")
    return active is None or active == round_id


@contextmanager
def portfolio_tune_slot(
    instance_id: str,
    round_id: Optional[str],
    *,
    timeout_seconds: int = 600,
) -> Iterator[TuneSlotOutcome]:
    """Serialize portfolio deadline autotune in queue order (newgatk before gatk)."""
    outcome = TuneSlotOutcome()
    if instance_id == "default" or not list_portfolio_instances():
        yield outcome
        return

    _wait_prior_rival_tune(instance_id, round_id, timeout_seconds=timeout_seconds)
    _ensure_dir()
    fd = TUNE_LOCK.open("a+")
    acquired = False
    start = time.time()
    try:
        while time.time() - start < timeout_seconds:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(1.5)
        if not acquired:
            raise TimeoutError(
                f"Portfolio tune queue timeout for {instance_id} round {round_id or 'unknown'}"
            )
        if round_id:
            state = load_coordinator()
            _reset_round_if_needed(state, round_id)
            inst = state["instances"].setdefault(instance_id, {})
            inst["tune_started"] = _now_iso()
            inst.pop("tune_done", None)
            save_coordinator(state)
        fd.seek(0)
        fd.truncate()
        fd.write(f"{instance_id}:{round_id or ''}\n")
        fd.flush()
        yield outcome
    finally:
        if acquired:
            try:
                if round_id:
                    state = load_coordinator()
                    _reset_round_if_needed(state, round_id)
                    inst = state["instances"].setdefault(instance_id, {})
                    if outcome.success:
                        inst["tune_done"] = _now_iso()
                    else:
                        inst.pop("tune_done", None)
                    save_coordinator(state)
            finally:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        fd.close()


def rival_tune_divergence(instance_id: str) -> Dict[str, Any]:
    """Per-rival param focus + cycle offset so shared-history autotune diverges."""
    focus = _strategy_params(instance_id)
    order = _queue_order()
    idx = order.index(instance_id) if instance_id in order else 0
    span = max(len(focus), 3)
    # Stagger autotune cycles more aggressively between rivals.
    cycle_offset = (idx * max(3, span)) % 8
    return {"param_focus": focus, "cycle_offset": cycle_offset}


def _strategy_params(instance_id: str) -> Tuple[str, ...]:
    from tuning.instance import instance_tool

    if instance_tool(instance_id) == "gatk":
        return STRATEGY_PARAM_OWNERSHIP.get(instance_id, ())
    base = STRATEGY_PARAM_OWNERSHIP.get(instance_id, ())
    if instance_id == "newgatk" and "precision" not in discover_instances():
        extra = STRATEGY_PARAM_OWNERSHIP.get("precision", ())
        return base + extra
    return base


def _queue_order() -> List[str]:
    # Stable sort by COMPUTE_QUEUE_PRIORITY so the auto-deadline path runs
    # BCFtools before GATK regardless of discovery order. Unlisted instances
    # (e.g. "precision", "default") fall after and keep their relative order.
    live = list(discover_instances())
    return sorted(live, key=lambda iid: COMPUTE_QUEUE_PRIORITY.get(iid, 50))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)


def _default_state() -> Dict[str, Any]:
    return {
        "round_id": None,
        "queue_order": _queue_order(),
        "instances": {},
        "tune_ledger": [],
        "compute_holder": None,
        "updated_at": _now_iso(),
    }


def _sync_queue_order(state: Dict[str, Any]) -> None:
    """Keep queue order aligned with MINOS_PORTFOLIO_ACTIVE (anchor before scout)."""
    live = _queue_order()
    state["queue_order"] = live


def active_coordinator_round_id() -> Optional[str]:
    """Open round from submit control, else coordinator file."""
    try:
        from tuning.submit_control import load_control

        pending = load_control().get("pending") or {}
        rid = pending.get("round_id")
        if rid:
            return str(rid)
    except ImportError:
        pass
    state = load_coordinator()
    return state.get("round_id")


def load_coordinator() -> Dict[str, Any]:
    _ensure_dir()
    if not COORD_FILE.is_file():
        return _default_state()
    try:
        data = json.loads(COORD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    base = _default_state()
    base.update({k: v for k, v in data.items() if k in base or k in ("instances", "tune_ledger")})
    _sync_queue_order(base)
    return base


def save_coordinator(state: Dict[str, Any]) -> None:
    _ensure_dir()
    _sync_queue_order(state)
    state["updated_at"] = _now_iso()
    COORD_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _reset_round_if_needed(state: Dict[str, Any], round_id: str) -> None:
    if state.get("round_id") != round_id:
        state["round_id"] = round_id
        state["instances"] = {}
        state["tune_ledger"] = []
        state["compute_holder"] = None

def register_instance_round(
    instance_id: str,
    round_id: str,
    *,
    region: Optional[str] = None,
    time_remaining_seconds: Optional[int] = None,
    bam_ready: bool = False,
    submitted: bool = False,
) -> Dict[str, Any]:
    state = load_coordinator()
    _reset_round_if_needed(state, round_id)
    inst = state["instances"].setdefault(instance_id, {})
    updates: Dict[str, Any] = {
        "round_id": round_id,
        "region": region,
        "time_remaining_seconds": time_remaining_seconds,
        "bam_ready": bam_ready,
        "updated_at": _now_iso(),
    }
    if submitted or not inst.get("submitted"):
        updates["submitted"] = submitted
    inst.update(updates)
    save_coordinator(state)
    return inst


def mark_instance_submitted(instance_id: str, round_id: str, *, reason: str = "") -> None:
    state = load_coordinator()
    _reset_round_if_needed(state, round_id)
    inst = state["instances"].setdefault(instance_id, {})
    inst.update(
        {
            "submitted": True,
            "submit_reason": reason,
            "compute_status": "done",
            "updated_at": _now_iso(),
        }
    )
    holder = state.get("compute_holder") or {}
    if holder.get("instance") == instance_id:
        state["compute_holder"] = None
    save_coordinator(state)


def mark_instance_compute_failed(
    instance_id: str,
    round_id: str,
    *,
    reason: str = "",
) -> None:
    """Release the portfolio GATK queue when this hotkey did not submit."""
    state = load_coordinator()
    if state.get("round_id") != round_id:
        return
    _reset_round_if_needed(state, round_id)
    inst = state["instances"].setdefault(instance_id, {})
    inst.update(
        {
            "compute_status": "failed",
            "submit_reason": reason or inst.get("submit_reason"),
            "updated_at": _now_iso(),
        }
    )
    holder = state.get("compute_holder") or {}
    if holder.get("instance") == instance_id:
        state["compute_holder"] = None
    save_coordinator(state)


def _instance_queue_cleared(
    inst: Dict[str, Any],
    *,
    instance_id: Optional[str] = None,
    round_id: Optional[str] = None,
) -> bool:
    """True when this hotkey finished or released its compute slot for the round."""
    if instance_id and round_id:
        from tuning.instance import bind_instance, reset_instance
        from tuning.submit_control import load_control

        token = bind_instance(instance_id)
        try:
            pending = load_control().get("pending") or {}
        finally:
            reset_instance(token)
        if pending.get("round_id") == round_id:
            return False
        if inst.get("submitted"):
            return True
        if _instance_submitted_in_history(instance_id, round_id):
            return True
        if inst.get("compute_status") in ("done", "failed", "skipped"):
            return True
        return False

    if inst.get("submitted"):
        return True
    if inst.get("compute_status") in ("done", "failed", "skipped"):
        return True
    if instance_id and round_id and _instance_submitted_in_history(instance_id, round_id):
        return True
    return False


def queue_position(instance_id: str, round_id: str) -> int:
    state = load_coordinator()
    if state.get("round_id") != round_id:
        return 1
    if _sync_coordinator_submissions(state, round_id):
        save_coordinator(state)
    order = state.get("queue_order") or _queue_order()
    instances = state.get("instances") or {}
    pending = [
        iid
        for iid in order
        if iid in discover_instances()
        and not _instance_queue_cleared(
            instances.get(iid) or {},
            instance_id=iid,
            round_id=round_id,
        )
    ]
    if instance_id not in pending:
        return 0
    return pending.index(instance_id) + 1


def _prior_instances_done(instance_id: str, round_id: str) -> bool:
    """True when all earlier hotkeys finished or released their compute slot."""
    state = load_coordinator()
    if state.get("round_id") != round_id:
        return True
    if _sync_coordinator_submissions(state, round_id):
        save_coordinator(state)
    order = state.get("queue_order") or _queue_order()
    if instance_id not in order:
        return True
    instances = state.get("instances") or {}
    for prior in order:
        if prior == instance_id:
            break
        if prior not in discover_instances():
            continue
        if _instance_queue_cleared(
            instances.get(prior) or {},
            instance_id=prior,
            round_id=round_id,
        ):
            continue
        return False
    return True


def _blocking_prior_instance(instance_id: str, round_id: str) -> Optional[str]:
    """Instance id of the earlier hotkey still holding the portfolio compute queue."""
    state = load_coordinator()
    if state.get("round_id") != round_id:
        return None
    if _sync_coordinator_submissions(state, round_id):
        save_coordinator(state)
    order = state.get("queue_order") or _queue_order()
    if instance_id not in order:
        return None
    instances = state.get("instances") or {}
    for prior in order:
        if prior == instance_id:
            break
        if prior not in discover_instances():
            continue
        if not _instance_queue_cleared(
            instances.get(prior) or {},
            instance_id=prior,
            round_id=round_id,
        ):
            return prior
    return None


def _queue_pending(state: Dict[str, Any]) -> List[str]:
    order = state.get("queue_order") or _queue_order()
    instances = state.get("instances") or {}
    return [
        iid
        for iid in order
        if iid in discover_instances() and not instances.get(iid, {}).get("submitted")
    ]


@contextmanager
def compute_slot(
    instance_id: str,
    round_id: str,
    *,
    timeout_seconds: int = 7200,
    poll_seconds: float = 8.0,
    manual: bool = False,
) -> Iterator[ComputeSlotOutcome]:
    """Serialized compute slot — one heavy variant-caller job at a time.

    Normally hotkeys run in ``queue_order`` (anchor before scout) so the
    automatic deadline path computes them one-by-one. When ``manual=True`` the
    caller skips the ordering wait and grabs the slot as soon as the on-disk
    lock is free: a manually submitted hotkey runs immediately instead of
    queueing behind a sibling that has not been submitted. The file lock still
    guarantees the two callers never run at the same time.
    """
    outcome = ComputeSlotOutcome()
    if instance_id == "default" or not list_portfolio_instances():
        yield outcome
        return

    _ensure_dir()
    fd = COMPUTE_LOCK.open("a+")
    start = time.time()
    acquired = False
    last_queued_write = 0.0
    last_queue_log = 0.0
    try:
        while time.time() - start < timeout_seconds:
            if not _coordinator_round_active(round_id):
                outcome.superseded = True
                yield outcome
                return
            if not manual and not _prior_instances_done(instance_id, round_id):
                now = time.time()
                if now - last_queued_write >= 30.0:
                    state = load_coordinator()
                    _reset_round_if_needed(state, round_id)
                    inst = state["instances"].setdefault(instance_id, {})
                    inst["compute_status"] = "queued"
                    inst["queue_position"] = queue_position(instance_id, round_id)
                    inst["updated_at"] = _now_iso()
                    save_coordinator(state)
                    last_queued_write = now
                if now - last_queue_log >= 60.0:
                    pos = queue_position(instance_id, round_id)
                    prior = _blocking_prior_instance(instance_id, round_id)
                    if prior and pos > 1:
                        print(
                            f"   Portfolio queue: position {pos} — still waiting for {prior}",
                            flush=True,
                        )
                    last_queue_log = now
                time.sleep(poll_seconds)
                continue

            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                state = load_coordinator()
                if not _coordinator_round_active(round_id):
                    outcome.superseded = True
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                    acquired = False
                    yield outcome
                    return
                _reset_round_if_needed(state, round_id)
                if not manual and not _prior_instances_done(instance_id, round_id):
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                    acquired = False
                    time.sleep(poll_seconds)
                    continue
                state["compute_holder"] = {
                    "instance": instance_id,
                    "round_id": round_id,
                    "since": _now_iso(),
                    "position": queue_position(instance_id, round_id),
                }
                inst = state["instances"].setdefault(instance_id, {})
                inst["compute_status"] = "running"
                inst["queue_position"] = 1
                inst["updated_at"] = _now_iso()
                save_coordinator(state)
                fd.seek(0)
                fd.truncate()
                fd.write(f"{instance_id}:{round_id}\n")
                fd.flush()
                break
            except BlockingIOError:
                time.sleep(poll_seconds)

        if not acquired:
            raise TimeoutError(
                f"Portfolio compute queue timeout for {instance_id} round {round_id}"
            )

        yield outcome
    finally:
        if acquired:
            try:
                state = load_coordinator()
                if state.get("round_id") == round_id:
                    if state.get("compute_holder", {}).get("instance") == instance_id:
                        state["compute_holder"] = None
                    inst = state.get("instances", {}).get(instance_id, {})
                    if inst:
                        if outcome.superseded:
                            inst["compute_status"] = "skipped"
                        elif outcome.success:
                            inst["compute_status"] = "done"
                        else:
                            inst["compute_status"] = "failed"
                        inst["updated_at"] = _now_iso()
                    save_coordinator(state)
            finally:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        elif outcome.superseded:
            state = load_coordinator()
            if state.get("round_id") == round_id:
                inst = state.get("instances", {}).get(instance_id, {})
                if inst:
                    inst["compute_status"] = "skipped"
                    inst["updated_at"] = _now_iso()
                    save_coordinator(state)
        fd.close()


def coordinate_portfolio_tune(
    before: Dict[str, Any],
    after: Dict[str, Any],
    *,
    round_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Log rival autotune moves — each hotkey owns its full gatk.conf (no param blocking)."""
    from tuning.config_manager import validate_config

    instance_id = current_instance_id()
    if instance_id == "default" or not list_portfolio_instances():
        return after, []

    after = _sanitize_gatk_config({**before, **after})
    valid, errors = validate_config(after)
    if not valid:
        return _sanitize_gatk_config(before), [
            f"rival autotune rejected: {errors[0] if errors else 'invalid config'}"
        ]

    rid = round_id or active_coordinator_round_id()
    state = load_coordinator()
    if rid:
        _reset_round_if_needed(state, rid)

    notes: List[str] = []
    for param, old, new in diff_config(before, after):
        state.setdefault("tune_ledger", []).append(
            {
                "instance": instance_id,
                "param": param,
                "from": old,
                "to": new,
                "at": _now_iso(),
            }
        )
        notes.append(f"{instance_id} {param}: {old}→{new}")

    save_coordinator(state)
    if notes:
        notes.insert(0, f"rival autotune ({instance_id})")
    return after, notes


def portfolio_status_payload() -> Dict[str, Any]:
    from tuning.submit_control import load_control

    state = load_coordinator()
    rid = state.get("round_id")
    if rid:
        if _sync_coordinator_submissions(state, rid):
            save_coordinator(state)
    rows: List[Dict[str, Any]] = []

    for iid in discover_instances():
        try:
            from tuning.instance import bind_instance, reset_instance

            token = bind_instance(iid)
            try:
                ctrl = load_control()
                wallet_name, wallet_hotkey = wallet_credentials(iid)
                profile = PORTFOLIO_PROFILES.get(iid, {})
                coord_inst = (state.get("instances") or {}).get(iid, {})
                pending = ctrl.get("pending") or {}
                coord_round = state.get("round_id") or pending.get("round_id") or ""
                history_submitted = (
                    bool(coord_round) and _instance_submitted_in_history(iid, coord_round)
                )
                submitted = history_submitted or (
                    bool(coord_inst.get("submitted"))
                    and not (pending.get("round_id") == coord_round)
                )
                rows.append(
                    {
                        "id": iid,
                        "label": profile.get("label", iid),
                        "emoji": profile.get("emoji", "•"),
                        "pm2_name": profile.get("pm2_name"),
                        "wallet_name": wallet_name,
                        "wallet_hotkey": wallet_hotkey,
                        "manual_submit_enabled": ctrl.get("manual_submit_enabled"),
                        "auto_submit_when_seconds_left": ctrl.get("auto_submit_when_seconds_left"),
                        "approve_round_id": ctrl.get("approve_round_id"),
                        "last_submit_reason": ctrl.get("last_submit_reason"),
                        "last_submit_at": ctrl.get("last_submit_at"),
                        "pending": pending if pending else None,
                        "submitted": submitted,
                        "bam_ready": coord_inst.get("bam_ready") or pending.get("bam_ready", False),
                        "compute_status": coord_inst.get("compute_status"),
                        "queue_position": coord_inst.get("queue_position")
                        or queue_position(iid, state.get("round_id") or pending.get("round_id") or ""),
                        "region": coord_inst.get("region") or pending.get("region"),
                        "time_remaining_seconds": coord_inst.get("time_remaining_seconds")
                        or pending.get("time_remaining_seconds"),
                        "strategy_params": list(_strategy_params(iid)),
                    }
                )
            finally:
                reset_instance(token)
        except Exception as exc:
            rows.append({"id": iid, "error": str(exc)})

    holder = state.get("compute_holder")
    return {
        "round_id": state.get("round_id"),
        "queue_order": state.get("queue_order"),
        "compute_holder": holder,
        "queue_pending": _queue_pending(state),
        "tune_ledger": (state.get("tune_ledger") or [])[-20:],
        "instances": rows,
        "updated_at": state.get("updated_at"),
    }


def portfolio_auto_submit_seconds() -> int:
    for key in ("MINER_AUTO_SUBMIT_SECONDS_LEFT", "PORTFOLIO_AUTO_SUBMIT_SECONDS"):
        raw = os.getenv(key, "").strip()
        if raw.isdigit():
            return max(600, int(raw))
    return 600


def ensure_portfolio_submit_defaults() -> None:
    from tuning.instance import bind_instance, reset_instance
    from tuning.submit_control import load_control, save_control

    try:
        from tuning.portfolio_intel import ensure_scout_aligned_to_anchor

        ensure_scout_aligned_to_anchor()
    except Exception:
        pass

    try:
        from tuning.portfolio_auto_mode import active_submit_threshold_seconds, sync_all_instance_submit_controls

        sync_all_instance_submit_controls()
        threshold = active_submit_threshold_seconds()
    except Exception:
        threshold = portfolio_auto_submit_seconds()
    for iid in discover_instances():
        if iid == "default":
            continue
        token = bind_instance(iid)
        try:
            ctrl = load_control()
            updates: Dict[str, Any] = {"manual_submit_enabled": True}
            if int(ctrl.get("auto_submit_when_seconds_left") or 0) != threshold:
                updates["auto_submit_when_seconds_left"] = threshold
            if updates:
                save_control(updates)
        finally:
            reset_instance(token)
