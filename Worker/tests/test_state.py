from app.job_control import clear_stop_request, request_stop_optimization as signal_stop
from app.state import best_store


def test_record_trial_and_stopping_status():
    clear_stop_request()
    best_store.begin_job("job-1", "chr21:1-1000000", "gatk", search_space_size=5)
    best_store.record_trial(
        index=1,
        label="base conf",
        success=True,
        score=0.81,
        raw_score=81.0,
        is_best=True,
    )
    snap = best_store.snapshot()
    assert len(snap.trials) == 1
    assert snap.trials[0].score == 0.81
    assert snap.trials[0].is_best is True

    signal_stop()
    snap = best_store.snapshot()
    assert snap.status == "stopping"

    best_store.finish_job(message="Stopped")
    snap = best_store.snapshot()
    assert snap.status == "ready"
    assert len(snap.trials) == 1
