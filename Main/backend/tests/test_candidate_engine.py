"""Tests for the candidate finder engine."""

import unittest

from app.engine.candidate_finder import CandidateFinderEngine, HistoryEntry
from app.selector import composite_candidate_rank_score, coordinate_similarity, parse_window


def _entry(
    *,
    id: str,
    chrom: str = "chr20",
    start: int,
    end: int,
    tool: str = "gatk",
    score: float,
) -> HistoryEntry:
    return HistoryEntry(
        id=id,
        window=f"{chrom}:{start}-{end}",
        chromosome=chrom,
        start=start,
        end=end,
        tool=tool,
        score=score,
        conf={"gatk_options": {"pcr_indel_model": "NONE"}},
    )


class CandidateFinderEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = parse_window("chr20:10000000-15000000")
        self.engine = CandidateFinderEngine(min_similarity=0.2)

    def test_step1_filters_tool_and_chromosome(self) -> None:
        history = [
            _entry(id="a", start=10_000_000, end=15_000_000, tool="gatk", score=0.9),
            _entry(id="b", start=10_000_000, end=15_000_000, tool="bcftools", score=0.95),
            _entry(id="c", chrom="chr21", start=10_000_000, end=15_000_000, tool="gatk", score=0.99),
        ]
        matched = self.engine.filter_type_matching(history, tool="gatk", chromosome="chr20")
        self.assertEqual([row.id for row in matched], ["a"])

    def test_step2_filters_similar_coordinates(self) -> None:
        exact = _entry(id="a", start=10_000_000, end=15_000_000, score=0.5)
        far = _entry(id="b", start=50_000_000, end=55_000_000, score=0.9)
        with_sim = self.engine.compute_coordinate_similarity(self.window, [exact, far])
        similar = self.engine.filter_similar_coordinates(with_sim)
        ids = [entry.id for entry, _ in similar]
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)

    def test_step3_ranks_by_composite_score(self) -> None:
        history = [
            _entry(id="high-score-far", start=50_000_000, end=55_000_000, score=0.95),
            _entry(id="mid-close", start=10_500_000, end=14_500_000, score=0.80),
            _entry(id="low-exact", start=10_000_000, end=15_000_000, score=0.70),
        ]
        result = self.engine.find(self.window, history, tool="gatk", n=2)
        self.assertEqual(result.type_matched, 3)
        self.assertEqual(result.coordinate_matched, 2)
        self.assertEqual(len(result.selected), 2)
        self.assertEqual(result.selected[0].entry.id, "low-exact")
        self.assertEqual(result.selected[1].entry.id, "mid-close")
        self.assertAlmostEqual(result.selected[0].rank_score, composite_candidate_rank_score(0.70, 1.0))

    def test_offset_overlapping_window_matches_history(self) -> None:
        window = parse_window("chr20:9000000-14000000")
        history = [
            _entry(id="shifted", start=10_000_000, end=15_000_000, score=0.75),
            _entry(id="far", start=50_000_000, end=55_000_000, score=0.95),
        ]
        result = self.engine.find(window, history, tool="gatk", n=1)
        self.assertEqual(result.selected[0].entry.id, "shifted")
        self.assertGreater(result.selected[0].similarity, 0.7)
        self.assertNotIn("far", [row.entry.id for row in result.selected])

    def test_fallback_excludes_zero_similarity_rows(self) -> None:
        history = [
            _entry(id="far-high", start=50_000_000, end=55_000_000, score=0.99),
        ]
        result = self.engine.find(self.window, history, tool="gatk", n=1)
        self.assertEqual(result.coordinate_matched, 0)
        self.assertEqual(result.selected, ())

    def test_empty_history(self) -> None:
        result = self.engine.find(self.window, [], tool="gatk", n=2)
        self.assertEqual(result.type_matched, 0)
        self.assertEqual(result.selected, ())


if __name__ == "__main__":
    unittest.main()
