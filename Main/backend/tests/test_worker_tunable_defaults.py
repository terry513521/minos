"""Tests for per-worker tunable defaults persistence."""

import unittest

from app.schemas import WorkerTunableProfileBody
from app.services.worker_tunable_defaults import normalize_profile_body


class WorkerTunableDefaultsTests(unittest.TestCase):
    def test_normalize_profile_normalizes_tool_and_algorithm(self) -> None:
        profile = normalize_profile_body(
            {
                "tool": "GATK",
                "selected_params": ["base_quality_score_threshold"],
                "algorithm": "OPTUNA",
                "concurrency": 2,
                "limit_seconds": 1200,
                "trial_threads": 4,
                "trial_memory_gb": 8,
                "trial_count": 5,
            }
        )
        self.assertEqual(profile.tool, "gatk")
        self.assertEqual(profile.algorithm, "optuna")
        self.assertEqual(profile.trial_count, 5)

    def test_normalize_profile_rejects_empty_params(self) -> None:
        with self.assertRaises(ValueError):
            normalize_profile_body(
                WorkerTunableProfileBody(
                    tool="gatk",
                    selected_params=[],
                )
            )


if __name__ == "__main__":
    unittest.main()
