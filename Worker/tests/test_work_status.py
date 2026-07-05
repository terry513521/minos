"""Tests for terminal work-status formatting."""

from app.core.work_status import (
    BenchmarkActivity,
    WorkPhase,
    format_worker_status,
    set_benchmark_activity,
    set_work_phase,
)
from app.domain.state import BestSnapshot


def setup_function() -> None:
    set_work_phase(None)
    set_benchmark_activity(None, None)


def test_format_idle_returns_none():
    assert format_worker_status(snapshot=BestSnapshot()) is None


def test_format_optimizing_job():
    snap = BestSnapshot(
        status="optimizing",
        tool="gatk",
        window="chr21:19256212-24256212",
        trials_evaluated=3,
        search_space_size=50,
        best_score=0.8123,
        message="gatk · chr21:... · trial 3/50",
    )
    line = format_worker_status(snapshot=snap, phase=WorkPhase.CALL)
    assert line is not None
    assert "[worker] optimizing" in line
    assert "gatk" in line
    assert "trial 3/50" in line
    assert "best 0.8123" in line
    assert "variant calling" in line


def test_format_standalone_benchmark():
    bench = BenchmarkActivity(window="chr22:15284883-20284883", tool="gatk")
    line = format_worker_status(
        snapshot=BestSnapshot(),
        benchmark=bench,
        phase=WorkPhase.BAM,
    )
    assert line is not None
    assert "[worker] benchmark" in line
    assert "chr22:15284883-20284883" in line
    assert "preparing BAM slice" in line
