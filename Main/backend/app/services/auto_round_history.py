"""Persist auto-mode round results (per-worker best score/conf)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AutoModeRound
from app.schemas import AutoModeRoundRecord, AutoModeWorkerRoundResult
from app.selector import parse_window
from app.services.worker_proxy import fetch_worker_best

if TYPE_CHECKING:
    from app.services.auto_mode import AutoSession

AutoRoundEndReason = Literal["best_export", "restart", "time_limit", "stop_all"]


def _round_source_key(session: AutoSession) -> str:
    return f"auto-round:{session.region}:{session.started_at.isoformat()}"


async def _worker_results_for_session(db: AsyncSession, session: AutoSession) -> list[AutoModeWorkerRoundResult]:
    results: list[AutoModeWorkerRoundResult] = []
    for assignment in session.assignments:
        best = await fetch_worker_best(db, assignment.worker_id)
        results.append(
            AutoModeWorkerRoundResult(
                worker_id=assignment.worker_id,
                worker_name=assignment.worker_name,
                algorithm=assignment.algorithm,
                candidate_index=assignment.candidate_index,
                window=assignment.window,
                best_score=float(best.best_score) if best.ok and best.best_score is not None else None,
                best_conf=best.best_conf if best.ok and best.best_conf else {},
                trials_evaluated=int(best.trials_evaluated or 0) if best.ok else 0,
                dispatch_ok=assignment.dispatch_ok,
                error=best.error if not best.ok else None,
            )
        )
    return results


def _pick_winner(
    worker_results: list[AutoModeWorkerRoundResult],
) -> tuple[str | None, str | None, float | None, dict[str, Any]]:
    scored = [
        row
        for row in worker_results
        if row.best_score is not None and row.best_conf
    ]
    if not scored:
        return None, None, None, {}
    winner = max(scored, key=lambda row: float(row.best_score or 0))
    return winner.worker_id, winner.worker_name, float(winner.best_score or 0), dict(winner.best_conf)


async def record_auto_round_if_needed(
    db: AsyncSession,
    *,
    end_reason: AutoRoundEndReason,
) -> AutoModeRound | None:
    """Snapshot per-worker bests for the current auto session (once per session)."""
    from app.services.auto_mode import auto_mode_store

    session = auto_mode_store.session
    if session is None or session.round_recorded or not session.assignments:
        return None

    source_key = _round_source_key(session)
    existing = await db.execute(select(AutoModeRound).where(AutoModeRound.source_key == source_key))
    if existing.scalar_one_or_none() is not None:
        session.round_recorded = True
        return None

    worker_results = await _worker_results_for_session(db, session)
    winner_worker_id, winner_worker_name, winner_score, winner_conf = _pick_winner(worker_results)
    parsed = parse_window(session.region)
    now = datetime.now(timezone.utc)

    row = AutoModeRound(
        source_key=source_key,
        region=parsed.window,
        chromosome=parsed.chromosome,
        start=parsed.start,
        end=parsed.end,
        tool=session.tool,
        started_at=session.started_at,
        ended_at=now,
        end_reason=end_reason,
        winner_worker_id=winner_worker_id,
        winner_worker_name=winner_worker_name,
        winner_score=winner_score,
        winner_conf=winner_conf or None,
        worker_results=[item.model_dump() for item in worker_results],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    session.round_recorded = True
    return row


async def list_auto_rounds(
    db: AsyncSession,
    *,
    limit: int = 50,
) -> list[AutoModeRoundRecord]:
    result = await db.execute(
        select(AutoModeRound).order_by(AutoModeRound.ended_at.desc()).limit(min(limit, 200))
    )
    rows = list(result.scalars().all())
    return [_round_to_record(row) for row in rows]


def _round_to_record(row: AutoModeRound) -> AutoModeRoundRecord:
    worker_results = [
        AutoModeWorkerRoundResult.model_validate(item)
        for item in (row.worker_results or [])
        if isinstance(item, dict)
    ]
    return AutoModeRoundRecord(
        id=row.id,
        region=row.region,
        tool=row.tool,
        started_at=row.started_at,
        ended_at=row.ended_at,
        end_reason=row.end_reason,
        winner_worker_id=row.winner_worker_id,
        winner_worker_name=row.winner_worker_name,
        winner_score=row.winner_score,
        winner_conf=row.winner_conf or {},
        worker_results=worker_results,
    )
