"""Worker dispatch validation for conf-check (benchmark-only) jobs."""

from app.schemas import WorkerDispatchRequest


def test_dispatch_accepts_adaptive_max_trials_zero():
    body = WorkerDispatchRequest(
        window="chr21:13919563-18919563",
        tool="gatk",
        base_conf={
            "gatk_options": {"pcr_indel_model": "NONE"},
            "threads": 4,
            "memory_gb": 8,
        },
        params=["pcr_indel_model"],
        concurrency=1,
        algorithm="grid",
        limit_seconds=1800,
        adaptive_max_trials=0,
    )
    assert body.adaptive_max_trials == 0
