"""Tests for chr22 history seed worker distribution."""

import unittest

from app.history_origin import chunk_seed_work_items, worker_for_seed_slot
from app.schemas import HistorySeedChr22Request


class HistorySeedWorkerTests(unittest.TestCase):
    def test_worker_for_seed_slot_round_robin(self) -> None:
        workers = ["a", "b", "c"]
        self.assertEqual(worker_for_seed_slot(workers, 0), "a")
        self.assertEqual(worker_for_seed_slot(workers, 1), "b")
        self.assertEqual(worker_for_seed_slot(workers, 2), "c")
        self.assertEqual(worker_for_seed_slot(workers, 3), "a")
        self.assertEqual(worker_for_seed_slot(workers, 9), "a")

    def test_resolved_worker_ids_from_list(self) -> None:
        body = HistorySeedChr22Request(worker_ids=["w2", "w1", "w2"])
        self.assertEqual(body.resolved_worker_ids(), ["w2", "w1"])

    def test_resolved_worker_ids_legacy_single(self) -> None:
        body = HistorySeedChr22Request(worker_id="solo")
        self.assertEqual(body.resolved_worker_ids(), ["solo"])

    def test_resolved_worker_ids_merges_legacy_first(self) -> None:
        body = HistorySeedChr22Request(worker_id="primary", worker_ids=["secondary", "primary"])
        self.assertEqual(body.resolved_worker_ids(), ["primary", "secondary"])

    def test_resolved_seed_worker_id_prefers_worker_id(self) -> None:
        body = HistorySeedChr22Request(worker_id="primary", worker_ids=["secondary"])
        self.assertEqual(body.resolved_seed_worker_id(), "primary")

    def test_resolved_seed_worker_id_from_list(self) -> None:
        body = HistorySeedChr22Request(worker_ids=["only"])
        self.assertEqual(body.resolved_seed_worker_id(), "only")

    def test_resolved_seed_worker_id_empty(self) -> None:
        body = HistorySeedChr22Request()
        self.assertIsNone(body.resolved_seed_worker_id())

    def test_chunk_seed_work_items_by_worker_count(self) -> None:
        items = list(range(5))
        waves = chunk_seed_work_items(items, 3)
        self.assertEqual(len(waves), 2)
        self.assertEqual(waves[0], [0, 1, 2])
        self.assertEqual(waves[1], [3, 4])


if __name__ == "__main__":
    unittest.main()
