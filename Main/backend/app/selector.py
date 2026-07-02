"""Parse genomic windows and coordinate helpers for candidate selection."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from templates.tool_params import validate_region  # noqa: E402

WINDOW_RE = re.compile(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedWindow:
    window: str
    chromosome: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def parse_window(window: str) -> ParsedWindow:
    check = validate_region(window)
    if not check["valid"]:
        raise ValueError(check["error"])

    m = WINDOW_RE.match(window.strip())
    if not m:
        raise ValueError(f"Invalid window format: {window}")

    chrom = m.group(1)
    if not chrom.startswith("chr"):
        chrom = f"chr{chrom}"

    start = int(m.group(2))
    end = int(m.group(3))
    canonical = f"{chrom}:{start}-{end}"
    return ParsedWindow(window=canonical, chromosome=chrom, start=start, end=end)


def coordinate_similarity(x: int, y: int, x_h: int, y_h: int) -> float:
    """IoU + center-distance blend on the same chromosome."""
    overlap = max(0, min(y, y_h) - max(x, x_h))
    union_len = max(y, y_h) - min(x, x_h)
    iou = overlap / union_len if union_len > 0 else 0.0

    length = max(y - x, 1)
    center_dist = abs(((x_h + y_h) / 2) - ((x + y) / 2)) / length
    return 0.7 * iou + 0.3 * (1 - min(center_dist, 1.0))


def rank_history_rows(
    window: ParsedWindow,
    rows: list[dict],
    *,
    tool: str = "gatk",
    min_similarity: float = 0.2,
) -> list[dict]:
    """Rank history dicts through the candidate finder engine."""
    from app.engine.candidate_finder import CandidateFinderEngine, history_dict_to_entry

    engine = CandidateFinderEngine(min_similarity=min_similarity)
    entries = [
        history_dict_to_entry({**row, "tool": row.get("tool", tool), "chromosome": window.chromosome})
        for row in rows
    ]
    pool_n = max(len(entries), 1)
    result = engine.find(window, entries, tool=tool, n=pool_n)

    output: list[dict] = []
    for scored in result.ranked_pool:
        row = scored.entry
        output.append(
            {
                "id": row.id,
                "start": row.start,
                "end": row.end,
                "score": row.score,
                "conf": row.conf,
                "window": row.window,
                "tool": row.tool,
                "similarity": scored.similarity,
                "rank_score": scored.rank_score,
            }
        )
    return output


def select_base_candidates(ranked: list[dict], k: int) -> list[dict]:
    if not ranked or k <= 0:
        return []
    return ranked[:k]
