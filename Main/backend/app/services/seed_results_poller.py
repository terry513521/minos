"""Background poller — sync worker seed results into Main DB every N minutes."""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import SessionLocal
from app.services.history_seed_sync import sync_seed_results_from_workers

logger = logging.getLogger(__name__)


class SeedResultsPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        settings = get_settings()
        if not settings.seed_results_poll_enabled:
            logger.info("Seed results poller disabled")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="seed-results-poller")
        logger.info(
            "Seed results poller started (every %ss)",
            max(60, settings.seed_results_poll_seconds),
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        settings = get_settings()
        interval = max(60, settings.seed_results_poll_seconds)
        while True:
            try:
                async with SessionLocal() as db:
                    result = await sync_seed_results_from_workers(db)
                    if result.imported or result.failed or result.worker_errors:
                        logger.info(
                            "Seed poller imported=%s skipped=%s failed=%s errors=%s",
                            result.imported,
                            result.skipped_duplicate,
                            result.failed,
                            len(result.worker_errors),
                        )
            except Exception:
                logger.exception("Seed results poller tick failed")
            await asyncio.sleep(interval)


poller = SeedResultsPoller()
