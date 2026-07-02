"""Persist (w, conf, s) rows to round_history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptimizationRun, RoundHistory
from app.selector import parse_window


def _source_key_for_run(run_id: str) -> str:
    return f"run:{run_id}"


async def save_history_record(
    db: AsyncSession,
    *,
    window: str,
    tool: str,
    conf: dict,
    score: float,
    run_id: str | None = None,
    worker_id: str | None = None,
    source_key: str | None = None,
    replace: bool = False,
) -> RoundHistory:
    """Insert a scored history row. Parses window into chromosome/start/end."""
    if score < 0 or score > 1:
        raise ValueError("score must be between 0 and 1")

    parsed = parse_window(window)
    tool_key = tool.lower().strip()
    key = source_key or (f"run:{run_id}" if run_id else None)

    if key:
        existing = await db.execute(
            select(RoundHistory).where(RoundHistory.source_key == key)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            if not replace:
                return row
            row.window = parsed.window
            row.chromosome = parsed.chromosome
            row.start = parsed.start
            row.end = parsed.end
            row.tool = tool_key
            row.conf = conf
            row.score = float(score)
            row.run_id = run_id
            row.worker_id = worker_id
            await db.commit()
            await db.refresh(row)
            return row

    row = RoundHistory(
        window=parsed.window,
        chromosome=parsed.chromosome,
        start=parsed.start,
        end=parsed.end,
        tool=tool_key,
        conf=conf,
        score=float(score),
        run_id=run_id,
        worker_id=worker_id,
        source_key=key,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def save_history_from_run(
    db: AsyncSession,
    run: OptimizationRun,
    *,
    replace: bool = False,
) -> RoundHistory:
    """Write the run winner (conf, score) into round_history."""
    if run.winner_conf is None or run.winner_score is None:
        raise ValueError("Run has no winner_conf / winner_score yet")

    return await save_history_record(
        db,
        window=run.window,
        tool=run.tool,
        conf=run.winner_conf,
        score=run.winner_score,
        run_id=run.id,
        source_key=_source_key_for_run(run.id),
        replace=replace,
    )
