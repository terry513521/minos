"""Tests for history origin helpers and chr22 seed remap."""

import unittest

from app.history_origin import (
    HISTORY_ORIGIN_SEED,
    remap_window_to_chr22,
    seed_source_key,
    infer_history_origin,
)


class HistoryOriginTests(unittest.TestCase):
    def test_infer_seed_and_worker(self) -> None:
        self.assertEqual(infer_history_origin("seed:chr22:from:abc"), HISTORY_ORIGIN_SEED)
        self.assertEqual(infer_history_origin("run:job-1"), "worker")
        self.assertEqual(infer_history_origin("gatk:round:chr21:1-2"), "portfolio")

    def test_remap_chr21_to_chr22(self) -> None:
        self.assertEqual(
            remap_window_to_chr22("chr21:35444092-40444092"),
            "chr22:35444092-40444092",
        )

    def test_remap_chr20_to_chr22(self) -> None:
        self.assertEqual(
            remap_window_to_chr22("chr20:10000000-15000000"),
            "chr22:10000000-15000000",
        )

    def test_remap_rejects_chr22_source(self) -> None:
        self.assertIsNone(remap_window_to_chr22("chr22:10000000-15000000"))

    def test_seed_source_key(self) -> None:
        self.assertEqual(seed_source_key("uuid-1"), "seed:chr22:from:uuid-1")


if __name__ == "__main__":
    unittest.main()
