"""Stratified GIAB quick-test windows — cached per round region + tier."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from tuning.giab.data import parse_region_bounds
from tuning.giab.paths import GIAB_RESULTS_DIR

logger = logging.getLogger(__name__)

SUITE_VERSION = 2
WINDOW_BP = 1_000_000
SUITES_DIR = GIAB_RESULTS_DIR / "suites"

# Stratified offsets inside the round region (fraction of slide range).
TIER_OFFSETS: Dict[str, List[float]] = {
    "light": [0.5],
    "medium": [0.25, 0.75],
    "full": [],
}


def extract_window(full_region: str, window_bp: int, offset_fraction: float) -> str:
    """Return a *window_bp* slice at *offset_fraction* along the round region."""
    chrom, start, end = parse_region_bounds(full_region)
    width = end - start
    if window_bp <= 0 or width <= window_bp:
        return full_region
    slide = end - window_bp - start
    win_start = start + int(slide * max(0.0, min(1.0, offset_fraction)))
    return f"{chrom}:{win_start}-{win_start + window_bp}"


def canonical_regions(regions: List[str]) -> str:
    """Stable cache identity for one or more test windows."""
    if not regions:
        return ""
    if len(regions) == 1:
        return regions[0]
    return "|".join(sorted(regions))


def _suite_id(full_region: str, tier: str, round_id: str = "") -> str:
    raw = f"v{SUITE_VERSION}|{round_id}|{full_region}|{tier}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _suite_path(suite_id: str) -> Path:
    return SUITES_DIR / f"{suite_id}.json"


def build_suite_windows(full_region: str, tier: str) -> List[Dict[str, Any]]:
    """Build stratified windows for a tier (no disk I/O)."""
    tier = (tier or "").strip().lower()
    if tier == "full" or tier not in TIER_OFFSETS or not TIER_OFFSETS[tier]:
        return [{"region": full_region, "offset_pct": 0, "label": "full", "window_bp": 0}]

    windows: List[Dict[str, Any]] = []
    for idx, frac in enumerate(TIER_OFFSETS[tier]):
        win = extract_window(full_region, WINDOW_BP, frac)
        chrom, w_start, w_end = parse_region_bounds(win)
        _, f_start, f_end = parse_region_bounds(full_region)
        full_w = max(f_end - f_start, 1)
        center = ((w_start + w_end) // 2) - f_start
        offset_pct = int(round(100 * center / full_w))
        windows.append(
            {
                "region": win,
                "offset_pct": offset_pct,
                "label": f"w{idx + 1}",
                "window_bp": WINDOW_BP,
                "offset_fraction": frac,
            }
        )
    return windows


def load_or_create_suite(
    full_region: str,
    tier: str,
    round_id: str = "",
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Load cached test suite or create stratified windows for this round region."""
    tier = (tier or "full").strip().lower()
    suite_id = _suite_id(full_region, tier, round_id)
    path = _suite_path(suite_id)

    if not force and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                cached.get("suite_version") == SUITE_VERSION
                and cached.get("full_region") == full_region
                and cached.get("tier") == tier
                and cached.get("round_id", "") == (round_id or "")
                and cached.get("windows")
            ):
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    windows = build_suite_windows(full_region, tier)
    payload: Dict[str, Any] = {
        "suite_id": suite_id,
        "suite_version": SUITE_VERSION,
        "full_region": full_region,
        "tier": tier,
        "round_id": round_id or "",
        "windows": windows,
        "region_canonical": canonical_regions([w["region"] for w in windows]),
        "window_count": len(windows),
        "total_window_bp": sum(int(w.get("window_bp") or 0) for w in windows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(
        "GIAB suite %s tier=%s round=%s → %d window(s)",
        suite_id,
        tier,
        (round_id or "")[:19] or "—",
        len(windows),
    )
    return payload
