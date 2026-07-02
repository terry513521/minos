"""Tests for history persistence."""

import unittest

from app.services.history_store import _source_key_for_run


class HistoryStoreTests(unittest.TestCase):
    def test_source_key_for_run(self) -> None:
        self.assertEqual(_source_key_for_run("abc-123"), "run:abc-123")


if __name__ == "__main__":
    unittest.main()
