"""Run candidate finder engine against DB history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.defaults import default_tool_conf
from app.engine.candidate_finder import CandidateFinderEngine, HistoryEntry
from app.models import RoundHistory
from app.schemas import CandidatePreview, FindCandidatesResponse
from app.selector import parse_window


def _to_preview(index: int, scored) -> CandidatePreview:
    row = scored.entry
    return CandidatePreview(
        index=index,
        base_conf=row.conf,
        rank_score=scored.rank_score,
        history_id=row.id,
        source_window=row.window or None,
        history_score=row.score,
        similarity=scored.similarity,
    )


def scored_pool_to_previews(ranked_pool) -> list[CandidatePreview]:
    return [_to_preview(i, scored) for i, scored in enumerate(ranked_pool)]


async def load_history_entries(
    db: AsyncSession,
    *,
    tool: str,
    limit: int = 500,
) -> list[HistoryEntry]:
    result = await db.execute(
        select(RoundHistory)
        .where(RoundHistory.tool == tool.lower())
        .order_by(RoundHistory.score.desc())
        .limit(limit)
    )
    return [
        HistoryEntry(
            id=h.id,
            window=h.window,
            chromosome=h.chromosome,
            start=h.start,
            end=h.end,
            tool=h.tool.lower(),
            score=h.score,
            conf=h.conf,
        )
        for h in result.scalars().all()
    ]


async def find_candidates(
    db: AsyncSession,
    *,
    window: str,
    tool: str = "gatk",
    k_candidates: int = 2,
    min_similarity: float = CandidateFinderEngine.DEFAULT_MIN_SIMILARITY,
) -> FindCandidatesResponse:
    parsed = parse_window(window)
    tool_key = tool.lower().strip()

    history = await load_history_entries(db, tool=tool_key)
    engine = CandidateFinderEngine(min_similarity=min_similarity)
    result = engine.find(parsed, history, tool=tool_key, n=k_candidates)

    candidates: list[CandidatePreview] = []
    if result.selected:
        candidates = [_to_preview(i, scored) for i, scored in enumerate(result.selected)]
    else:
        candidates = [
            CandidatePreview(
                index=0,
                base_conf=default_tool_conf(tool_key),
                rank_score=0.0,
                history_id=None,
                source_window=None,
                history_score=None,
                similarity=None,
            )
        ]

    return FindCandidatesResponse(
        window=parsed.window,
        chromosome=parsed.chromosome,
        tool=tool_key,
        k_candidates=k_candidates,
        candidates=candidates,
        used_default=result.used_default,
        history_matched=result.type_matched,
        coordinate_matched=result.coordinate_matched,
        total_history=result.total_history,
        ranked_pool_size=len(result.ranked_pool),
        min_similarity=result.min_similarity,
    )
