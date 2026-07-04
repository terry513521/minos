"""Tests for worker task summary formatting."""

from app.optimization.task_info import format_task_banner, format_task_line


def test_format_task_banner_includes_core_fields():
    text = format_task_banner(
        worker="vm-1",
        job_id="job-abc",
        window="chr20:10000000-15000000",
        tool="gatk",
        algorithm="pbt",
        planned_trials=301,
        adaptive_max_trials=300,
        concurrency=16,
        limit_seconds=7200,
        params=["pcr_indel_model", "standard_min_confidence_threshold_for_calling"],
        trial_threads=6,
        trial_memory_gb=10,
        benchmark_window="chr20:12000000-13000000",
    )
    assert "worker: vm-1" in text
    assert "region: chr20:10000000-15000000" in text
    assert "benchmark slice: chr20:12000000-13000000" in text
    assert "algorithm: pbt" in text
    assert "concurrency: 16" in text
    assert "6 CPUs, 10 GB RAM" in text


def test_format_task_line_compact():
    line = format_task_line(
        tool="gatk",
        window="chr21:1-1000000",
        algorithm="cascade",
        trials_evaluated=12,
        search_space_size=50,
        concurrency=8,
        status="optimizing",
    )
    assert line == "gatk · chr21:1-1000000 · cascade · trial 12/50 · ×8 · optimizing"
