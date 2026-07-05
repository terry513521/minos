"""Import round history from Minos tuning JSON exports and remote /api/rounds."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history_origin import HISTORY_ORIGIN_IMPORT, HISTORY_ORIGIN_PORTFOLIO
from app.selector import parse_window

WINDOW_IN_REGION = re.compile(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$", re.IGNORECASE)

TOOL_OPTION_KEYS = {
    "gatk": "gatk_options",
    "bcftools": "bcftools_options",
    "deepvariant": "deepvariant_options",
    "freebayes": "freebayes_options",
}


@dataclass
class HistoryImportResult:
    files: int
    parsed: int
    imported: int
    skipped_unscored: int
    skipped_invalid: int
    skipped_duplicate: int


def _parse_created_at(entry: dict) -> datetime:
    for key in ("scored_at", "submitted_at", "round_id"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _wrap_conf(tool: str, snapshot: dict) -> dict:
    key = TOOL_OPTION_KEYS.get(tool, f"{tool}_options")
    return {key: snapshot}


def _source_key(source_label: str, entry: dict) -> str:
    """Canonical dedupe key — same round from JSON files and API must collide."""
    round_id = entry.get("round_id") or ""
    region = entry.get("region") or ""
    tool = str(entry.get("tool") or "gatk").lower()
    instance_id = entry.get("instance_id") or ""
    base = f"{tool}:{round_id}:{region}"
    if instance_id:
        return f"{base}:{instance_id}"
    return base


def _import_source_key(source_label: str, entry: dict) -> str:
    """File imports prefix source_key so origin can be inferred."""
    return f"import:{_source_key(source_label, entry)}"


def _source_label(path: Path) -> str:
    """e.g. instances/gatk/tuning/data/round_history.json -> gatk"""
    if path.parent.name == "data":
        tuning = path.parent.parent
        if tuning.name == "tuning" and tuning.parent.name:
            return tuning.parent.name
    return path.stem


def api_source_label(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.strip("/") or "api"
    return f"api:{host}"


def flatten_round_entries(data: dict | list) -> list[dict]:
    """Normalize portfolio /api/rounds payloads into flat scored history rows."""
    if isinstance(data, list):
        rounds = data
    elif isinstance(data, dict):
        rounds = data.get("rounds") or []
    else:
        return []

    entries: list[dict] = []
    for round_item in rounds:
        if not isinstance(round_item, dict):
            continue

        instances = round_item.get("instances")
        if isinstance(instances, dict) and instances:
            for instance_id, instance in instances.items():
                if not isinstance(instance, dict):
                    continue
                entry = dict(instance)
                entry.setdefault("round_id", round_item.get("round_id"))
                entry.setdefault("region", round_item.get("region"))
                entry.setdefault("instance_id", instance.get("instance_id") or instance_id)
                entries.append(entry)
            continue

        if round_item.get("combined_final") is not None or round_item.get("config_snapshot"):
            entries.append(round_item)

    return entries


def _load_rounds(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "rounds" in data:
        return flatten_round_entries(data)
    if isinstance(data, list):
        return flatten_round_entries(data)
    return []


def _entry_to_row(source_label: str, entry: dict, *, from_api: bool = False) -> RoundHistory | None:
    score = entry.get("combined_final")
    if score is None:
        return None

    region = entry.get("region")
    if not region or not WINDOW_IN_REGION.match(region.strip()):
        return None

    tool = str(entry.get("tool") or "gatk").lower()
    snapshot = entry.get("config_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        return None

    try:
        parsed = parse_window(region)
    except ValueError:
        return None

    key = _source_key(source_label, entry) if from_api else _import_source_key(source_label, entry)
    origin = HISTORY_ORIGIN_PORTFOLIO if from_api else HISTORY_ORIGIN_IMPORT

    return RoundHistory(
        chromosome=parsed.chromosome,
        start=parsed.start,
        end=parsed.end,
        window=parsed.window,
        tool=tool,
        conf=_wrap_conf(tool, snapshot),
        score=float(score),
        run_id=str(entry.get("round_id")) if entry.get("round_id") else None,
        source_key=key,
        history_origin=origin,
        created_at=_parse_created_at(entry),
    )


async def _import_entries(
    db: AsyncSession,
    source_label: str,
    entries: list[dict],
    *,
    replace: bool = False,
) -> HistoryImportResult:
    result = HistoryImportResult(
        files=0,
        parsed=0,
        imported=0,
        skipped_unscored=0,
        skipped_invalid=0,
        skipped_duplicate=0,
    )

    existing_keys: set[str] = set()
    if not replace:
        rows = await db.execute(
            select(RoundHistory.source_key).where(RoundHistory.source_key.is_not(None))
        )
        existing_keys = {k for k in rows.scalars().all() if k}

    if replace:
        await db.execute(RoundHistory.__table__.delete())
        existing_keys.clear()

    for entry in entries:
        _import_one_entry(result, existing_keys, source_label, entry, db)

    await db.commit()
    return result


async def import_history_files(
    db: AsyncSession,
    paths: list[Path],
    *,
    replace: bool = False,
) -> HistoryImportResult:
    result = HistoryImportResult(
        files=0,
        parsed=0,
        imported=0,
        skipped_unscored=0,
        skipped_invalid=0,
        skipped_duplicate=0,
    )

    existing_keys: set[str] = set()
    if not replace:
        rows = await db.execute(
            select(RoundHistory.source_key).where(RoundHistory.source_key.is_not(None))
        )
        existing_keys = {k for k in rows.scalars().all() if k}

    if replace:
        await db.execute(RoundHistory.__table__.delete())
        existing_keys.clear()

    for path in paths:
        if not path.is_file():
            continue
        result.files += 1
        source_label = _source_label(path)
        for entry in _load_rounds(path):
            _import_one_entry(result, existing_keys, source_label, entry, db)

    await db.commit()
    return result


def _import_one_entry(
    result: HistoryImportResult,
    existing_keys: set[str],
    source_label: str,
    entry: dict,
    db: AsyncSession,
) -> None:
    result.parsed += 1
    if entry.get("combined_final") is None:
        result.skipped_unscored += 1
        return

    row = _entry_to_row(source_label, entry, from_api=source_label.startswith("api:"))
    if row is None:
        result.skipped_invalid += 1
        return

    if row.source_key in existing_keys:
        result.skipped_duplicate += 1
        return

    db.add(row)
    existing_keys.add(row.source_key)
    result.imported += 1


async def fetch_rounds_payload(url: str, *, timeout: float = 60.0) -> dict | list:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Rounds API returned non-JSON object")
        return payload


async def import_history_api(
    db: AsyncSession,
    url: str,
    *,
    replace: bool = False,
    timeout: float = 60.0,
) -> HistoryImportResult:
    """Fetch GET /api/rounds and upsert scored rows into round_history."""
    payload = await fetch_rounds_payload(url, timeout=timeout)
    entries = flatten_round_entries(payload)
    result = await _import_entries(db, api_source_label(url), entries, replace=replace)
    result.files = 1
    return result


async def maybe_import_default_history(db: AsyncSession, paths: list[Path]) -> HistoryImportResult | None:
    """Import configured JSON files when history table is empty."""
    if not paths:
        return None

    count = await db.scalar(select(func.count()).select_from(RoundHistory))
    if count and count > 0:
        return None

    return await import_history_files(db, paths, replace=False)


async def maybe_sync_history_api(db: AsyncSession, url: str | None) -> HistoryImportResult | None:
    """Merge new rows from the configured rounds API on startup."""
    if not url or not url.strip():
        return None
    try:
        return await import_history_api(db, url.strip(), replace=False)
    except Exception:
        return None
