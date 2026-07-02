"""Tests for worker trial history in best_store."""

from app.state import best_store


def test_record_trial_and_best_flag():
    best_store.begin_job("job-1", "chr21:1-100", "gatk", search_space_size=5)
    best_store.record_trial(
        index=1,
        label="base conf",
        success=True,
        score=0.5,
        raw_score=50.0,
        is_best=True,
    )
    best_store.record_trial(
        index=2,
        label="trial",
        success=True,
        score=0.7,
        raw_score=70.0,
        is_best=True,
    )

    snap = best_store.snapshot()
    assert len(snap.trials) == 2
    assert snap.trials[0].is_best is False
    assert snap.trials[1].is_best is True
    assert snap.trials[1].score == 0.7


def test_set_stopping_status():
    best_store.begin_job("job-2", "chr21:1-100", "gatk", search_space_size=3)
    best_store.set_stopping(message="Stop requested")
    snap = best_store.snapshot()
    assert snap.status == "stopping"
    assert snap.stop_requested is True
