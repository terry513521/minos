"""Tests for genomic window parsing and coordinate similarity."""

import unittest

from app.selector import coordinate_similarity, parse_window


class SelectorTests(unittest.TestCase):
    def test_parse_window_uses_start_and_end_coordinates(self) -> None:
        parsed = parse_window("chr20:9000000-14000000")
        self.assertEqual(parsed.start, 9_000_000)
        self.assertEqual(parsed.end, 14_000_000)
        self.assertEqual(parsed.length, 5_000_000)

    def test_overlap_between_offset_five_mb_windows(self) -> None:
        query = parse_window("chr20:9000000-14000000")
        history = parse_window("chr20:10000000-15000000")
        sim = coordinate_similarity(query.start, query.end, history.start, history.end)
        self.assertAlmostEqual(sim, 0.7067, places=3)

    def test_exact_match_similarity_is_one(self) -> None:
        window = parse_window("chr20:10000000-15000000")
        sim = coordinate_similarity(window.start, window.end, window.start, window.end)
        self.assertEqual(sim, 1.0)

    def test_non_overlapping_adjacent_windows_have_zero_similarity(self) -> None:
        query = parse_window("chr20:10000000-15000000")
        history = parse_window("chr20:15000000-20000000")
        sim = coordinate_similarity(query.start, query.end, history.start, history.end)
        self.assertEqual(sim, 0.0)


if __name__ == "__main__":
    unittest.main()
