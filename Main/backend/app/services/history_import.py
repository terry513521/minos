"""Import round history from Minos tuning JSON exports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RoundHistory
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
    round_id = entry.get("round_id") or ""
    region = entry.get("region") or ""
    tool = entry.get("tool") or "gatk"
    return f"{source_label}:{tool}:{round_id}:{region}"


def _source_label(path: Path) -> str:
    """e.g. instances/gatk/tuning/data/round_history.json -> gatk"""
    if path.parent.name == "data":
        tuning = path.parent.parent
        if tuning.name == "tuning" and tuning.parent.name:
            return tuning.parent.name
    return path.stem


def _load_rounds(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("rounds") or [])
    if isinstance(data, list):
        return data
    return []


def _entry_to_row(source_label: str, entry: dict) -> RoundHistory | None:
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

    return RoundHistory(
        chromosome=parsed.chromosome,
        start=parsed.start,
        end=parsed.end,
        window=parsed.window,
        tool=tool,
        conf=_wrap_conf(tool, snapshot),
        score=float(score),
        run_id=str(entry.get("round_id")) if entry.get("round_id") else None,
        source_key=_source_key(source_label, entry),
        created_at=_parse_created_at(entry),
    )


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
            result.parsed += 1
            if entry.get("combined_final") is None:
                result.skipped_unscored += 1
                continue

            row = _entry_to_row(source_label, entry)
            if row is None:
                result.skipped_invalid += 1
                continue

            if row.source_key in existing_keys:
                result.skipped_duplicate += 1
                continue

            db.add(row)
            existing_keys.add(row.source_key)
            result.imported += 1

    await db.commit()
    return result


async def maybe_import_default_history(db: AsyncSession, paths: list[Path]) -> HistoryImportResult | None:
    """Import configured JSON files when history table is empty."""
    if not paths:
        return None

    count = await db.scalar(select(func.count()).select_from(RoundHistory))
    if count and count > 0:
        return None

    return await import_history_files(db, paths, replace=False)
