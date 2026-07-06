"""Background poller — refresh portfolio rounds cache from the API."""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.portfolio_rounds import store

logger = logging.getLogger(__name__)


class PortfolioRoundsPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        settings = get_settings()
        if not settings.portfolio_rounds_poll_enabled:
            logger.info("Portfolio rounds poller disabled")
            return
        url = (settings.history_api_url or "").strip()
        if not url:
            logger.info("Portfolio rounds poller skipped — no history API URL")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="portfolio-rounds-poller")
        logger.info(
            "Portfolio rounds poller started (every %ss)",
            max(60, settings.portfolio_rounds_poll_seconds),
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
        interval = max(60, settings.portfolio_rounds_poll_seconds)
        url = settings.history_api_url.strip()
        while True:
            await asyncio.sleep(interval)
            try:
                result = await store.sync_from_api(url, timeout=settings.history_api_timeout)
                logger.info(
                    "Portfolio rounds poller synced %s rows from API",
                    result["summary"]["rows"],
                )
            except Exception:
                logger.exception("Portfolio rounds poller tick failed")


poller = PortfolioRoundsPoller()
