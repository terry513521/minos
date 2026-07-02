"""Tests for the candidate finder engine."""

import unittest

from app.engine.candidate_finder import CandidateFinderEngine, HistoryEntry
from app.selector import parse_window


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

    def test_step3_selects_best_score_among_similar(self) -> None:
        history = [
            _entry(id="high-score-far", start=50_000_000, end=55_000_000, score=0.95),
            _entry(id="mid-close", start=10_500_000, end=14_500_000, score=0.80),
            _entry(id="low-exact", start=10_000_000, end=15_000_000, score=0.70),
        ]
        result = self.engine.find(self.window, history, tool="gatk", n=2)
        self.assertEqual(result.type_matched, 3)
        self.assertGreaterEqual(result.coordinate_matched, 2)
        self.assertEqual(len(result.selected), 2)
        self.assertEqual(result.selected[0].entry.id, "mid-close")
        self.assertEqual(result.selected[1].entry.id, "low-exact")
        self.assertEqual(result.selected[0].rank_score, 0.80)

    def test_empty_history(self) -> None:
        result = self.engine.find(self.window, [], tool="gatk", n=2)
        self.assertEqual(result.type_matched, 0)
        self.assertEqual(result.selected, ())


if __name__ == "__main__":
    unittest.main()
