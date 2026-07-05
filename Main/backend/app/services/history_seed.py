"""Seed chr22 round_history by re-scoring chr20/chr21 portfolio rows on Worker."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history_origin import (
    HISTORY_ORIGIN_SEED,
    SEED_SOURCE_CHROMS,
    remap_window_to_chr22,
    seed_source_key,
)
from app.models import RoundHistory
from app.schemas import HistorySeedChr22Item, HistorySeedChr22Request, HistorySeedChr22Response, HistorySeedChr22WorkerSkip
from app.services.history_store import save_history_record
from app.services.worker_proxy import (
    post_worker_benchmark,
    resolve_seed_workers,
    resolve_worker_base_urls,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SeedWorkItem:
    source_id: str
    source_window: str
    target_window: str
    tool: str
    conf: dict[str, Any]
    worker_id: str
    source_key: str


async def _benchmark_seed_wave(
    worker_bases: dict[str, str | None],
    wave: list[_SeedWorkItem],
) -> list[tuple[_SeedWorkItem, Any]]:
    results = await asyncio.gather(
        *[
            post_worker_benchmark(
                base_url=worker_bases.get(item.worker_id),
                worker_id=item.worker_id,
                window=item.target_window,
                tool=item.tool,
                conf=item.conf,
            )
            for item in wave
        ]
    )
    return list(zip(wave, results))


async def _persist_seed_result(
    db: AsyncSession,
    *,
    item: _SeedWorkItem,
    bench: Any,
    existing_keys: set[str],
) -> tuple[HistorySeedChr22Item, bool]:
    """Save one benchmark result. Returns (item, scored_ok)."""
    if not bench.ok or bench.score is None:
        return (
            HistorySeedChr22Item(
                source_id=item.source_id,
                source_window=item.source_window,
                target_window=item.target_window,
                tool=item.tool,
                worker_id=item.worker_id,
                status="failed",
                error=bench.error or "Benchmark failed",
            ),
            False,
        )

    row = await save_history_record(
        db,
        window=item.target_window,
        tool=item.tool,
        conf=item.conf,
        score=float(bench.score),
        worker_id=item.worker_id,
        source_key=item.source_key,
        history_origin=HISTORY_ORIGIN_SEED,
    )
    existing_keys.add(item.source_key)
    return (
        HistorySeedChr22Item(
            source_id=item.source_id,
            source_window=item.source_window,
            target_window=item.target_window,
            tool=item.tool,
            worker_id=item.worker_id,
            status="scored",
            score=row.score,
            history_id=row.id,
        ),
        True,
    )


async def seed_chr22_history(
    db: AsyncSession,
    body: HistorySeedChr22Request,
) -> HistorySeedChr22Response:
    """
    Seed chr22 rows on one worker:
      POST /benchmark for each portfolio row sequentially (one at a time).
    """
    preferred_id = body.resolved_seed_worker_id()
    worker_ids, skipped_workers, dispatch_urls = await resolve_seed_workers(
        db,
        preferred_ids=[preferred_id] if preferred_id else None,
    )
    if not worker_ids:
        detail = "; ".join(
            f"{s.get('worker_name') or s['worker_id']}: {s['reason']}" for s in skipped_workers
        )
        raise ValueError(
            "No reachable worker for seeding."
            + (f" Skipped: {detail}" if detail else " Register a worker with health_url or base_url.")
        )
    seed_worker_id = worker_ids[0]
    if len(worker_ids) > 1:
        skipped_workers.extend(
            [
                {
                    "worker_id": wid,
                    "worker_name": None,
                    "reason": f"Only one worker used for seeding (selected {seed_worker_id})",
                }
                for wid in worker_ids[1:]
            ]
        )
    worker_ids = [seed_worker_id]
    dispatch_urls = {seed_worker_id: dispatch_urls[seed_worker_id]}
    if skipped_workers:
        logger.warning(
            "chr22 seed: using worker %s, skipped %s",
            seed_worker_id,
            skipped_workers,
        )
    source_chroms = {
        c.lower().strip() if c.lower().startswith("chr") else f"chr{c.lower().strip()}"
        for c in body.source_chromosomes
    }
    source_chroms = {c for c in source_chroms if c in SEED_SOURCE_CHROMS}
    if not source_chroms:
        source_chroms = set(SEED_SOURCE_CHROMS)

    result = await db.execute(
        select(RoundHistory)
        .where(RoundHistory.chromosome.in_(sorted(source_chroms)))
        .order_by(RoundHistory.score.desc())
    )
    sources = list(result.scalars().all())

    existing_keys = {
        k
        for k in (
            await db.scalars(
                select(RoundHistory.source_key).where(RoundHistory.source_key.is_not(None))
            )
        ).all()
        if k
    }

    response = HistorySeedChr22Response(
        total_sources=len(sources),
        skipped_existing=0,
        skipped_invalid=0,
        scored=0,
        failed=0,
        dry_run=body.dry_run,
        worker_ids_used=worker_ids,
        worker_dispatch_urls=dispatch_urls,
        workers_skipped=[
            HistorySeedChr22WorkerSkip(
                worker_id=row["worker_id"],
                worker_name=row.get("worker_name"),
                reason=row["reason"],
            )
            for row in skipped_workers
        ],
        items=[],
    )

    entries: list[tuple[str, HistorySeedChr22Item | _SeedWorkItem]] = []
    batch = 0

    for source in sources:
        if batch >= body.limit:
            break

        target_window = remap_window_to_chr22(source.window)
        if not target_window:
            response.skipped_invalid += 1
            entries.append(
                (
                    "skip",
                    HistorySeedChr22Item(
                        source_id=source.id,
                        source_window=source.window,
                        target_window="",
                        tool=source.tool,
                        status="skipped_invalid",
                        error="Cannot remap window to chr22",
                    ),
                )
            )
            continue

        key = seed_source_key(source.id)
        if key in existing_keys:
            response.skipped_existing += 1
            entries.append(
                (
                    "skip",
                    HistorySeedChr22Item(
                        source_id=source.id,
                        source_window=source.window,
                        target_window=target_window,
                        tool=source.tool,
                        status="skipped_existing",
                    ),
                )
            )
            continue

        worker_id = seed_worker_id
        batch += 1

        if body.dry_run:
            entries.append(
                (
                    "dry",
                    HistorySeedChr22Item(
                        source_id=source.id,
                        source_window=source.window,
                        target_window=target_window,
                        tool=source.tool,
                        worker_id=worker_id,
                        status="dry_run",
                    ),
                )
            )
            continue

        entries.append(
            (
                "work",
                _SeedWorkItem(
                    source_id=source.id,
                    source_window=source.window,
                    target_window=target_window,
                    tool=source.tool,
                    conf=source.conf,
                    worker_id=worker_id,
                    source_key=key,
                ),
            )
        )

    work_items = [entry[1] for entry in entries if entry[0] == "work"]
    bench_by_source: dict[str, Any] = {}
    waves_completed = 0

    if work_items and not body.dry_run:
        worker_bases = await resolve_worker_base_urls(db, worker_ids)
        dispatch_url = worker_bases.get(seed_worker_id) or "unreachable"
        for item_index, item in enumerate(work_items, start=1):
            logger.info(
                "chr22 seed %s/%s: POST /benchmark to %s@%s window=%s",
                item_index,
                len(work_items),
                seed_worker_id,
                dispatch_url,
                item.target_window,
            )
            wave_results = await _benchmark_seed_wave(worker_bases, [item])
            item, bench = wave_results[0]
            result_item, scored_ok = await _persist_seed_result(
                db,
                item=item,
                bench=bench,
                existing_keys=existing_keys,
            )
            if scored_ok:
                response.scored += 1
            else:
                response.failed += 1
            bench_by_source[item.source_id] = result_item
            waves_completed += 1
            logger.info(
                "chr22 seed %s/%s complete (scored=%s failed=%s so far)",
                item_index,
                len(work_items),
                response.scored,
                response.failed,
            )

    for kind, payload in entries:
        if kind in {"skip", "dry"}:
            response.items.append(payload)
            continue
        response.items.append(bench_by_source[payload.source_id])

    response.waves_completed = waves_completed if not body.dry_run else len(work_items)
    response.workers_per_wave = 1
    return response
