"""Persisted control-plane key/value settings (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ControlPlaneSetting

LAST_AUTO_START_REGION_KEY = "last_auto_start_region"
AUTO_MODE_TUNABLE_CONFIG_KEY = "auto_mode_tunable_config"


async def get_control_plane_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(ControlPlaneSetting).where(ControlPlaneSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_control_plane_setting(db: AsyncSession, key: str, value: str | None) -> None:
    result = await db.execute(select(ControlPlaneSetting).where(ControlPlaneSetting.key == key))
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(ControlPlaneSetting(key=key, value=value, updated_at=now))
    else:
        row.value = value
        row.updated_at = now
    await db.commit()
