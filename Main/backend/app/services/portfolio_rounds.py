"""Portfolio rounds cache for /history/rounds dashboard (rich rows + summary)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.history_import import WINDOW_IN_REGION, fetch_rounds_payload

logger = logging.getLogger(__name__)

_EMPTY_SUMMARY: dict[str, Any] = {
    "rounds": 0,
    "rows": 0,
    "chroms": [],
    "instances": [],
    "date_min": None,
    "date_max": None,
    "avg_score": 0.0,
    "best_score": 0.0,
}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_region(region: str) -> tuple[str, int, int] | None:
    match = WINDOW_IN_REGION.match(region.strip())
    if not match:
        return None
    return match.group(1).lower(), int(match.group(2)), int(match.group(3))


def _breakdown_components(inst: dict) -> dict[str, float | None]:
    breakdown = inst.get("score_breakdown") or {}
    components = breakdown.get("components") or []
    out: dict[str, float | None] = {
        "core": None,
        "completeness": None,
        "fp": None,
        "quality": None,
    }
    if not isinstance(components, list):
        return out
    for item in components:
        if not isinstance(item, dict):
            continue
        key = item.get("id")
        if key in out:
            out[key] = _number(item.get("contribution"))
    return out


def flatten_portfolio_rows(payload: dict | list) -> list[dict[str, Any]]:
    """Flatten portfolio /api/rounds or rounds.json into chart-friendly rows."""
    if isinstance(payload, list):
        rounds = payload
    elif isinstance(payload, dict):
        rounds = payload.get("rounds") or []
    else:
        return []

    rows: list[dict[str, Any]] = []
    for round_obj in rounds:
        if not isinstance(round_obj, dict):
            continue

        leader = _number(round_obj.get("leader_score"))
        instances = round_obj.get("instances") or {}
        if not isinstance(instances, dict):
            continue

        for instance_key, inst in instances.items():
            if not isinstance(inst, dict):
                continue

            score_100 = _number(inst.get("score_100"))
            combined = _number(inst.get("combined_final"))
            if score_100 is None and combined is not None:
                score_100 = combined * 100.0
            if score_100 is None:
                continue

            region = str(inst.get("region") or round_obj.get("region") or "")
            parsed = _parse_region(region)
            if parsed is None:
                continue
            chrom, start, end = parsed

            metrics = inst.get("score_metrics") if isinstance(inst.get("score_metrics"), dict) else {}
            breakdown = _breakdown_components(inst)

            gap = _number(inst.get("gap_to_leader"))
            if gap is None and leader is not None:
                gap = leader - score_100

            runtime = _number(inst.get("runtime_seconds") or inst.get("runtime_s")) or 0.0
            instance_id = str(inst.get("instance_id") or instance_key)

            rows.append(
                {
                    "round_id": str(inst.get("round_id") or round_obj.get("round_id") or ""),
                    "region": region,
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "leader_score": leader,
                    "instance": instance_id,
                    "label": str(instance_key),
                    "score_100": round(score_100, 2),
                    "rank": inst.get("rank"),
                    "gap_to_leader": round(gap, 1) if gap is not None else None,
                    "runtime_s": round(runtime, 1),
                    "f1_snp": _number(inst.get("f1_snp") or metrics.get("f1_snp")),
                    "f1_indel": _number(inst.get("f1_indel") or metrics.get("f1_indel")),
                    "variant_count": inst.get("variant_count"),
                    "core": breakdown["core"],
                    "completeness": breakdown["completeness"],
                    "fp": breakdown["fp"],
                    "quality": breakdown["quality"],
                }
            )

    rows.sort(key=lambda r: (r["round_id"], r["chrom"], r["start"], r["instance"]))
    return rows


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(_EMPTY_SUMMARY)

    round_ids = {r["round_id"] for r in rows if r.get("round_id")}
    chroms = sorted({r["chrom"] for r in rows if r.get("chrom")})
    instances = sorted({r["instance"] for r in rows if r.get("instance")})
    dates = [r["round_id"] for r in rows if r.get("round_id")]
    scores = [float(r["score_100"]) for r in rows]

    return {
        "rounds": len(round_ids),
        "rows": len(rows),
        "chroms": chroms,
        "instances": instances,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "avg_score": round(sum(scores) / len(scores), 2),
        "best_score": round(max(scores), 2),
    }


def _cache_path() -> Path:
    settings = get_settings()
    if settings.portfolio_rounds_cache_path.strip():
        return Path(settings.portfolio_rounds_cache_path.strip())
    return Path(__file__).resolve().parents[1] / "data" / "portfolio_rounds_cache.json"


class PortfolioRoundsStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: list[dict[str, Any]] = []
        self._summary: dict[str, Any] = dict(_EMPTY_SUMMARY)
        self._synced_at: datetime | None = None
        self._source: str = "empty"
        self._api_url: str | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "synced_at": self._synced_at,
            "source": self._source,
            "api_url": self._api_url,
            "summary": self._summary,
            "rows": self._rows,
        }

    def _apply_rows(self, rows: list[dict[str, Any]], *, source: str, api_url: str | None) -> None:
        self._rows = rows
        self._summary = build_summary(rows)
        self._synced_at = datetime.now(timezone.utc)
        self._source = source
        self._api_url = api_url

    def _save_cache(self) -> None:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "synced_at": self._synced_at.isoformat() if self._synced_at else None,
            "source": self._source,
            "api_url": self._api_url,
            "summary": self._summary,
            "rows": self._rows,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _load_cache(self) -> bool:
        path = _cache_path()
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        rows = data.get("rows")
        if not isinstance(rows, list):
            return False
        self._rows = rows
        self._summary = data.get("summary") or build_summary(rows)
        raw_synced = data.get("synced_at")
        if raw_synced:
            try:
                self._synced_at = datetime.fromisoformat(str(raw_synced).replace("Z", "+00:00"))
            except ValueError:
                self._synced_at = None
        self._source = str(data.get("source") or "cache")
        self._api_url = data.get("api_url")
        return bool(rows)

    def _load_file(self, path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read portfolio rounds file %s: %s", path, exc)
            return False
        rows = flatten_portfolio_rows(payload)
        if not rows:
            return False
        self._apply_rows(rows, source="file", api_url=None)
        self._save_cache()
        return True

    async def bootstrap(self) -> None:
        settings = get_settings()
        async with self._lock:
            if self._load_cache():
                logger.info("Portfolio rounds loaded from cache (%s rows)", len(self._rows))
                return

            fallback = settings.portfolio_rounds_path
            if fallback.is_file() and self._load_file(fallback):
                logger.info("Portfolio rounds loaded from %s (%s rows)", fallback, len(self._rows))
                return

        if settings.portfolio_rounds_sync_on_startup and settings.history_api_url.strip():
            try:
                await self.sync_from_api(
                    settings.history_api_url.strip(),
                    timeout=settings.history_api_timeout,
                )
            except Exception:
                logger.exception("Portfolio rounds startup API sync failed")

    async def sync_from_api(self, url: str, *, timeout: float = 60.0) -> dict[str, Any]:
        payload = await fetch_rounds_payload(url, timeout=timeout)
        rows = flatten_portfolio_rows(payload)
        async with self._lock:
            self._apply_rows(rows, source="api", api_url=url)
            self._save_cache()
        return self.to_response()

    async def reload_from_file(self, path: Path | None = None) -> dict[str, Any]:
        settings = get_settings()
        target = path or settings.portfolio_rounds_path
        async with self._lock:
            if not self._load_file(target):
                raise FileNotFoundError(f"No portfolio rounds at {target}")
        return self.to_response()

    async def get(self) -> dict[str, Any]:
        async with self._lock:
            if not self._rows:
                settings = get_settings()
                if not self._load_cache() and settings.portfolio_rounds_path.is_file():
                    self._load_file(settings.portfolio_rounds_path)
            return self.to_response()


store = PortfolioRoundsStore()
