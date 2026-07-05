"""Seed chr22 round_history by re-scoring chr20/chr21 portfolio rows on Worker."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history_origin import (
    HISTORY_ORIGIN_SEED,
    SEED_SOURCE_CHROMS,
    remap_window_to_chr22,
    seed_source_key,
    worker_for_seed_slot,
)
from app.models import RoundHistory
from app.schemas import HistorySeedChr22Item, HistorySeedChr22Request, HistorySeedChr22Response
from app.services.history_store import save_history_record
from app.services.worker_proxy import benchmark_on_worker


async def seed_chr22_history(
    db: AsyncSession,
    body: HistorySeedChr22Request,
) -> HistorySeedChr22Response:
    worker_ids = body.resolved_worker_ids()
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
        items=[],
    )

    batch = 0
    assign_slot = 0
    for source in sources:
        if batch >= body.limit:
            break

        target_window = remap_window_to_chr22(source.window)
        if not target_window:
            response.skipped_invalid += 1
            response.items.append(
                HistorySeedChr22Item(
                    source_id=source.id,
                    source_window=source.window,
                    target_window="",
                    tool=source.tool,
                    status="skipped_invalid",
                    error="Cannot remap window to chr22",
                )
            )
            continue

        key = seed_source_key(source.id)
        if key in existing_keys:
            response.skipped_existing += 1
            response.items.append(
                HistorySeedChr22Item(
                    source_id=source.id,
                    source_window=source.window,
                    target_window=target_window,
                    tool=source.tool,
                    status="skipped_existing",
                )
            )
            continue

        worker_id = worker_for_seed_slot(worker_ids, assign_slot)
        assign_slot += 1

        if body.dry_run:
            batch += 1
            response.items.append(
                HistorySeedChr22Item(
                    source_id=source.id,
                    source_window=source.window,
                    target_window=target_window,
                    tool=source.tool,
                    worker_id=worker_id,
                    status="dry_run",
                )
            )
            continue

        bench = await benchmark_on_worker(
            db,
            worker_id=worker_id,
            window=target_window,
            tool=source.tool,
            conf=source.conf,
        )
        if not bench.ok or bench.score is None:
            response.failed += 1
            response.items.append(
                HistorySeedChr22Item(
                    source_id=source.id,
                    source_window=source.window,
                    target_window=target_window,
                    tool=source.tool,
                    worker_id=worker_id,
                    status="failed",
                    error=bench.error or "Benchmark failed",
                )
            )
            continue

        row = await save_history_record(
            db,
            window=target_window,
            tool=source.tool,
            conf=source.conf,
            score=float(bench.score),
            worker_id=worker_id,
            source_key=key,
            history_origin=HISTORY_ORIGIN_SEED,
        )
        existing_keys.add(key)
        response.scored += 1
        batch += 1
        response.items.append(
            HistorySeedChr22Item(
                source_id=source.id,
                source_window=source.window,
                target_window=target_window,
                tool=source.tool,
                worker_id=worker_id,
                status="scored",
                score=row.score,
                history_id=row.id,
            )
        )

    return response
