from app.domain.state import best_store
from app.optimization.job_control import clear_stop_request, request_stop_optimization as signal_stop


def test_record_trial_and_stopping_status():
    clear_stop_request()
    best_store.begin_job(
        "job-1",
        "chr21:1-1000000",
        "gatk",
        search_space_size=5,
        algorithm="grid",
        concurrency=4,
        limit_seconds=1800,
        adaptive_max_trials=4,
        params=["min_mapping_quality_score"],
        trial_threads=6,
        trial_memory_gb=10,
    )
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
    assert snap.algorithm == "grid"
    assert snap.concurrency == 4
    assert snap.trial_threads == 6

    signal_stop()
    snap = best_store.snapshot()
    assert snap.status == "stopping"

    best_store.finish_job(message="Stopped")
    snap = best_store.snapshot()
    assert snap.status == "ready"
    assert len(snap.trials) == 1


def test_begin_job_benchmark_only_uses_benchmarking_status():
    best_store.begin_job(
        "job-bench",
        "chr21:1-5000000",
        "gatk",
        search_space_size=1,
        algorithm="grid",
        concurrency=1,
        limit_seconds=1800,
        adaptive_max_trials=0,
        params=["pcr_indel_model"],
    )
    snap = best_store.snapshot()
    assert snap.status == "benchmarking"
    assert snap.search_space_size == 1
