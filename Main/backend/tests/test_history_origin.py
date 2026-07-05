"""Tests for history origin helpers and chr22 seed remap."""

import unittest

from app.history_origin import (
    HISTORY_ORIGIN_SEED,
    ExistingSeedState,
    remap_window_to_chr22,
    parse_seed_source_history_id,
    seed_result_fingerprint,
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

    def test_parse_seed_source_history_id(self) -> None:
        self.assertEqual(
            parse_seed_source_history_id("seed:chr22:from:uuid-1"),
            "uuid-1",
        )
        self.assertIsNone(parse_seed_source_history_id("run:abc"))

    def test_existing_seed_state_skips_by_source_key(self) -> None:
        state = ExistingSeedState(source_keys={seed_source_key("p1")})
        self.assertTrue(
            state.is_already_seeded(
                portfolio_id="p1",
                target_window="chr22:1-100",
                tool="gatk",
                conf={"x": 1},
            )
        )

    def test_existing_seed_state_skips_by_chr22_fingerprint(self) -> None:
        conf = {"min-base-quality": 20}
        state = ExistingSeedState(
            fingerprints={seed_result_fingerprint("chr22:1-100", "gatk", conf)}
        )
        self.assertTrue(
            state.is_already_seeded(
                portfolio_id="other-id",
                target_window="chr22:1-100",
                tool="gatk",
                conf=conf,
            )
        )
        self.assertFalse(
            state.is_already_seeded(
                portfolio_id="other-id",
                target_window="chr22:1-100",
                tool="gatk",
                conf={"min-base-quality": 21},
            )
        )

    def test_register_seed_updates_state(self) -> None:
        state = ExistingSeedState()
        state.register_seed(
            source_key=seed_source_key("p9"),
            portfolio_id="p9",
            target_window="chr22:5-10",
            tool="bcftools",
            conf={},
        )
        self.assertTrue(
            state.is_already_seeded(
                portfolio_id="p9",
                target_window="chr22:5-10",
                tool="bcftools",
                conf={},
            )
        )


if __name__ == "__main__":
    unittest.main()
