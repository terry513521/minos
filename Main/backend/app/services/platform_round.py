from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.minos_platform import (
    AuthenticationError,
    PlatformClientError,
    PlatformConfig,
    get_round_status,
    load_keypair,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10


@dataclass
class PlatformRoundSnapshot:
    enabled: bool
    polled_at: datetime | None = None
    error: str | None = None
    has_active_round: bool = False
    round_id: str | None = None
    status: str | None = None
    region: str | None = None
    chromosome: str | None = None
    time_remaining_seconds: int | None = None
    start_time: str | None = None
    submission_end_time: str | None = None
    scoring_end_time: str | None = None
    phase_deadline_at: str | None = None
    optimize_deadline_at: str | None = None
    num_mutations: int | None = None
    downsampled_coverage: int | None = None
    has_submitted: bool = False
    demo_mode: bool = False
    hotkey_ss58: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "polled_at": self.polled_at.isoformat() if self.polled_at else None,
            "error": self.error,
            "has_active_round": self.has_active_round,
            "round_id": self.round_id,
            "status": self.status,
            "region": self.region,
            "chromosome": self.chromosome,
            "time_remaining_seconds": self.time_remaining_seconds,
            "start_time": self.start_time,
            "submission_end_time": self.submission_end_time,
            "scoring_end_time": self.scoring_end_time,
            "phase_deadline_at": self.phase_deadline_at,
            "optimize_deadline_at": self.optimize_deadline_at,
            "num_mutations": self.num_mutations,
            "downsampled_coverage": self.downsampled_coverage,
            "has_submitted": self.has_submitted,
            "demo_mode": self.demo_mode,
            "hotkey_ss58": self.hotkey_ss58,
        }


def _iso_field(data: dict[str, Any], key: str) -> str | None:
    val = data.get(key)
    if val is None:
        return None
    return str(val)


def _deadline_from_remaining(polled_at: datetime, seconds: int | None) -> str | None:
    if seconds is None:
        return None
    from datetime import timedelta

    return (polled_at + timedelta(seconds=seconds)).isoformat()


def _optimize_deadline(submission_end: str | None) -> str | None:
    if not submission_end:
        return None
    from datetime import timedelta

    try:
        end = datetime.fromisoformat(submission_end.replace("Z", "+00:00"))
        return (end - timedelta(seconds=600)).isoformat()
    except (TypeError, ValueError):
        return None


def _normalize_region(region: str | None) -> tuple[str | None, str | None]:
    if not region or not str(region).strip():
        return None, None
    from app.selector import parse_window

    try:
        parsed = parse_window(str(region))
        return parsed.window, parsed.chromosome
    except ValueError:
        raw = str(region).strip()
        chrom = raw.split(":", 1)[0] if ":" in raw else raw
        if chrom and not chrom.lower().startswith("chr"):
            chrom = f"chr{chrom}"
        return raw, chrom if chrom else None


class PlatformRoundPoller:
    """Poll Minos platform round-status and keep an in-memory cache."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._snapshot = PlatformRoundSnapshot(enabled=False)
        self._task: asyncio.Task | None = None
        self._listeners: list[asyncio.Queue] = []

    @property
    def snapshot(self) -> PlatformRoundSnapshot:
        return self._snapshot

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._listeners:
            self._listeners.remove(q)

    async def _notify(self, data: dict[str, Any]) -> None:
        for q in list(self._listeners):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    async def poll_once(self) -> PlatformRoundSnapshot:
        settings = get_settings()
        if not settings.platform_enabled:
            snap = PlatformRoundSnapshot(enabled=False, error="Platform polling disabled")
            async with self._lock:
                self._snapshot = snap
            return snap

        if not settings.platform_url:
            snap = PlatformRoundSnapshot(enabled=True, error="MAIN_PLATFORM_URL not set")
            async with self._lock:
                self._snapshot = snap
            return snap

        try:
            keypair = load_keypair(settings.platform_wallet_uri)
            data = await get_round_status(
                config=PlatformConfig(
                    base_url=settings.platform_url,
                    timeout=settings.platform_timeout,
                ),
                keypair=keypair,
                demo=settings.platform_demo_mode,
            )
            polled_at = datetime.now(timezone.utc)
            submission_end = _iso_field(data, "submission_end_time")
            remaining = data.get("time_remaining_seconds")
            region, chromosome = _normalize_region(data.get("region"))
            if chromosome is None and data.get("chromosome"):
                chromosome = str(data.get("chromosome")).strip() or None
            snap = PlatformRoundSnapshot(
                enabled=True,
                polled_at=polled_at,
                has_active_round=bool(data.get("has_active_round")),
                round_id=data.get("round_id"),
                status=data.get("status"),
                region=region,
                chromosome=chromosome,
                time_remaining_seconds=remaining,
                start_time=_iso_field(data, "start_time"),
                submission_end_time=submission_end,
                scoring_end_time=_iso_field(data, "scoring_end_time"),
                phase_deadline_at=_deadline_from_remaining(polled_at, remaining),
                optimize_deadline_at=_optimize_deadline(submission_end),
                num_mutations=data.get("num_mutations"),
                downsampled_coverage=data.get("downsampled_coverage"),
                has_submitted=bool(data.get("has_submitted", False)),
                demo_mode=settings.platform_demo_mode,
                hotkey_ss58=keypair.ss58_address,
                raw=data,
            )
        except AuthenticationError as exc:
            snap = PlatformRoundSnapshot(
                enabled=True,
                polled_at=datetime.now(timezone.utc),
                error=f"Authentication failed: {exc}",
                demo_mode=settings.platform_demo_mode,
            )
        except PlatformClientError as exc:
            snap = PlatformRoundSnapshot(
                enabled=True,
                polled_at=datetime.now(timezone.utc),
                error=str(exc),
                demo_mode=settings.platform_demo_mode,
            )
        except Exception as exc:
            logger.exception("Platform round poll failed")
            snap = PlatformRoundSnapshot(
                enabled=True,
                polled_at=datetime.now(timezone.utc),
                error=str(exc),
                demo_mode=settings.platform_demo_mode,
            )

        async with self._lock:
            prev_region = self._snapshot.region
            prev_status = self._snapshot.status
            prev_round_id = self._snapshot.round_id
            self._snapshot = snap

        payload = {"type": "platform_round", "data": snap.to_dict()}
        if (
            snap.region != prev_region
            or snap.status != prev_status
            or snap.round_id != prev_round_id
            or snap.error
        ):
            await self._notify(payload)
        return snap

    async def run_loop(self) -> None:
        settings = get_settings()
        interval = max(3, settings.platform_poll_seconds)
        while True:
            await self.poll_once()
            await asyncio.sleep(interval)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            await self.poll_once()
            self._task = asyncio.create_task(self.run_loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None


poller = PlatformRoundPoller()
