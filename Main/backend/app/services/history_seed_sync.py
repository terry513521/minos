"""Pull completed seed benchmark results from workers into round_history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.history_origin import HISTORY_ORIGIN_SEED, ExistingSeedState
from app.schemas import HistorySeedSyncResponse
from app.services.history_seed import _load_existing_seed_state
from app.services.history_store import save_history_record
from app.services.worker_proxy import (
    fetch_worker_seed_results,
    resolve_dispatchable_worker_ids,
    resolve_worker_base_urls,
)

logger = logging.getLogger(__name__)

_last_sync_at: datetime | None = None


def last_seed_sync_at() -> datetime | None:
    return _last_sync_at


async def sync_seed_results_from_workers(
    db: AsyncSession,
    *,
    worker_ids: list[str] | None = None,
) -> HistorySeedSyncResponse:
    """Fetch GET /seed/results from workers and persist scored rows (deduped)."""
    global _last_sync_at

    ids = worker_ids or await resolve_dispatchable_worker_ids(db)
    if not ids:
        return HistorySeedSyncResponse(
            workers_polled=0,
            imported=0,
            skipped_duplicate=0,
            failed=0,
            last_sync_at=_last_sync_at,
            worker_errors=["No dispatchable workers registered"],
        )

    seed_state = await _load_existing_seed_state(db)
    bases = await resolve_worker_base_urls(db, ids)
    imported = 0
    skipped_duplicate = 0
    failed = 0
    worker_errors: list[str] = []

    for worker_id in ids:
        base = bases.get(worker_id)
        payload = await fetch_worker_seed_results(
            base_url=base,
            worker_id=worker_id,
            status="scored",
        )
        if not payload.ok:
            worker_errors.append(f"{worker_id}: {payload.error or 'fetch failed'}")
            continue

        for item in payload.results:
            if not item.success or item.score is None:
                continue
            source_id = item.source_id or item.seed_id or ""
            if seed_state.is_already_seeded(
                portfolio_id=source_id,
                target_window=item.target_window,
                tool=item.tool,
                conf=item.conf,
            ):
                skipped_duplicate += 1
                continue
            try:
                await save_history_record(
                    db,
                    window=item.target_window,
                    tool=item.tool,
                    conf=item.conf,
                    score=float(item.score),
                    worker_id=worker_id,
                    source_key=item.source_key,
                    history_origin=HISTORY_ORIGIN_SEED,
                )
            except Exception as exc:
                failed += 1
                logger.warning(
                    "Seed sync failed worker=%s source_key=%s: %s",
                    worker_id,
                    item.source_key,
                    exc,
                )
                continue
            seed_state.register_seed(
                source_key=item.source_key,
                portfolio_id=source_id,
                target_window=item.target_window,
                tool=item.tool,
                conf=item.conf,
            )
            imported += 1

    _last_sync_at = datetime.now(timezone.utc)
    logger.info(
        "Seed sync complete workers=%s imported=%s skipped=%s failed=%s",
        len(ids),
        imported,
        skipped_duplicate,
        failed,
    )
    return HistorySeedSyncResponse(
        workers_polled=len(ids),
        imported=imported,
        skipped_duplicate=skipped_duplicate,
        failed=failed,
        last_sync_at=_last_sync_at,
        worker_errors=worker_errors,
    )
