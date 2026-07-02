from app.optimization.job_control import (
    clear_stop_request,
    is_stop_requested,
    request_stop_optimization,
)
from app.optimization.jobs import request_stop_optimization as jobs_request_stop, worker_busy


def test_stop_request_lifecycle():
    clear_stop_request()
    assert not is_stop_requested()
    request_stop_optimization()
    assert is_stop_requested()
    clear_stop_request()
    assert not is_stop_requested()


def test_jobs_stop_when_idle():
    clear_stop_request()
    assert not worker_busy()
    assert jobs_request_stop() is False
