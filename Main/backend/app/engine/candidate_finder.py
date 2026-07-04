"""Candidate finder engine — type match → similar coordinates → best score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.selector import ParsedWindow, composite_candidate_rank_score, coordinate_similarity


@dataclass(frozen=True)
class HistoryEntry:
    id: str | None
    window: str
    chromosome: str
    start: int
    end: int
    tool: str
    score: float
    conf: dict[str, Any]


@dataclass(frozen=True)
class ScoredHistoryEntry:
    entry: HistoryEntry
    similarity: float
    rank_score: float  # composite rank: 40% history score + 60% similarity


@dataclass(frozen=True)
class CandidateFindResult:
    window: ParsedWindow
    tool: str
    n: int
    min_similarity: float
    total_history: int
    type_matched: int
    coordinate_matched: int
    ranked_pool: tuple[ScoredHistoryEntry, ...]
    selected: tuple[ScoredHistoryEntry, ...]

    @property
    def used_default(self) -> bool:
        return len(self.selected) == 0


def history_dict_to_entry(row: dict[str, Any]) -> HistoryEntry:
    return HistoryEntry(
        id=row.get("id"),
        window=row.get("window") or "",
        chromosome=row.get("chromosome") or "",
        start=int(row["start"]),
        end=int(row["end"]),
        tool=str(row.get("tool") or "gatk").lower(),
        score=float(row["score"]),
        conf=row.get("conf") or {},
    )


class CandidateFinderEngine:
    """
    1. Filter history by tool type (+ chromosome).
    2. Keep rows with similar genomic coordinates (interval overlap from x to y).
    3. Among those, select top-N by composite rank (40% score + 60% similarity).
    """

    DEFAULT_MIN_SIMILARITY = 0.2
    DEFAULT_FALLBACK_POOL = 15

    def __init__(
        self,
        *,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        fallback_pool: int = DEFAULT_FALLBACK_POOL,
    ) -> None:
        if not 0.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between 0 and 1")
        if fallback_pool < 1:
            raise ValueError("fallback_pool must be >= 1")
        self.min_similarity = min_similarity
        self.fallback_pool = fallback_pool

    def find(
        self,
        window: ParsedWindow,
        history: list[HistoryEntry],
        *,
        tool: str,
        n: int,
    ) -> CandidateFindResult:
        if n < 1:
            raise ValueError("n must be >= 1")

        tool_key = tool.lower().strip()
        type_matched = self.filter_type_matching(history, tool=tool_key, chromosome=window.chromosome)
        with_similarity = self.compute_coordinate_similarity(window, type_matched)
        coord_similar = self.filter_similar_coordinates(with_similarity)
        ranked_pool = self.rank_by_composite_score(coord_similar)
        selected = self.select_n_candidates(ranked_pool, n)

        return CandidateFindResult(
            window=window,
            tool=tool_key,
            n=n,
            min_similarity=self.min_similarity,
            total_history=len(history),
            type_matched=len(type_matched),
            coordinate_matched=len(coord_similar),
            ranked_pool=tuple(ranked_pool),
            selected=tuple(selected),
        )

    @staticmethod
    def filter_type_matching(
        history: list[HistoryEntry],
        *,
        tool: str,
        chromosome: str,
    ) -> list[HistoryEntry]:
        """Step 1: same tool type and chromosome."""
        tool_key = tool.lower().strip()
        chrom_key = chromosome.lower().strip()
        return [
            row
            for row in history
            if row.tool.lower() == tool_key and row.chromosome.lower() == chrom_key
        ]

    def compute_coordinate_similarity(
        self,
        window: ParsedWindow,
        rows: list[HistoryEntry],
    ) -> list[tuple[HistoryEntry, float]]:
        """Attach coordinate similarity to each type-matched row."""
        return [
            (row, coordinate_similarity(window.start, window.end, row.start, row.end))
            for row in rows
        ]

    def filter_similar_coordinates(
        self,
        rows_with_similarity: list[tuple[HistoryEntry, float]],
    ) -> list[tuple[HistoryEntry, float]]:
        """Step 2: keep rows with similar coordinates."""
        similar = [
            (entry, sim) for entry, sim in rows_with_similarity if sim >= self.min_similarity
        ]
        if similar:
            return similar

        # No rows above threshold — keep only overlapping/nearby rows (sim > 0).
        positive = [(entry, sim) for entry, sim in rows_with_similarity if sim > 0.0]
        if not positive:
            return []

        ranked = sorted(positive, key=lambda pair: pair[1], reverse=True)
        return ranked[: min(self.fallback_pool, len(ranked))]

    @staticmethod
    def rank_by_composite_score(
        rows_with_similarity: list[tuple[HistoryEntry, float]],
    ) -> list[ScoredHistoryEntry]:
        """Step 3: sort by composite rank (score + similarity blend)."""
        pool = [
            ScoredHistoryEntry(
                entry=entry,
                similarity=sim,
                rank_score=composite_candidate_rank_score(entry.score, sim),
            )
            for entry, sim in rows_with_similarity
        ]
        pool.sort(key=lambda row: row.rank_score, reverse=True)
        return pool

    @staticmethod
    def select_n_candidates(
        ranked: list[ScoredHistoryEntry],
        n: int,
    ) -> list[ScoredHistoryEntry]:
        if not ranked or n <= 0:
            return []
        return ranked[:n]
