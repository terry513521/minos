"""Tests for async seed batch store."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.seed import store


@pytest.fixture()
def seed_store_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "seed_results.json"
    monkeypatch.setattr(store, "_STORE_PATH", path)
    return path


def test_enqueue_and_status(seed_store_path: Path) -> None:
    batch_id, queued, skipped = store.enqueue_batch(
        batch_id="test-batch",
        entries=[
            {
                "source_id": "src-1",
                "source_key": "seed:chr22:from:src-1",
                "source_window": "chr21:1-100",
                "target_window": "chr22:1-100",
                "tool": "gatk",
                "conf": {"threads": 4},
            }
        ],
    )
    assert batch_id == "test-batch"
    assert queued == 1
    assert skipped == 0
    snap = store.status_snapshot()
    assert snap["pending"] == 1
    assert snap["status"] == "running"


def test_enqueue_skips_duplicate_pending(seed_store_path: Path) -> None:
    entry = {
        "source_id": "src-1",
        "source_key": "seed:chr22:from:src-1",
        "source_window": "chr21:1-100",
        "target_window": "chr22:1-100",
        "tool": "gatk",
        "conf": {},
    }
    store.enqueue_batch(batch_id="b1", entries=[entry])
    _, queued, skipped = store.enqueue_batch(batch_id="b2", entries=[entry])
    assert queued == 0
    assert skipped == 1


def test_mark_result_updates_counts(seed_store_path: Path) -> None:
    store.enqueue_batch(
        batch_id="b1",
        entries=[
            {
                "source_id": "src-1",
                "source_key": "seed:chr22:from:src-1",
                "source_window": "chr21:1-100",
                "target_window": "chr22:1-100",
                "tool": "gatk",
                "conf": {},
            }
        ],
    )
    store.mark_result("seed:chr22:from:src-1", success=True, score=0.75)
    snap = store.status_snapshot()
    assert snap["scored"] == 1
    assert snap["status"] == "idle"
    rows = store.list_results(status="scored")
    assert len(rows) == 1
    assert rows[0]["score"] == 0.75
