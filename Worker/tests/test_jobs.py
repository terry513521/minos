from app.job_control import (
    clear_stop_request,
    is_stop_requested,
    request_stop_optimization as signal_stop,
)
from app.jobs import request_stop_optimization, worker_busy


def test_stop_request_lifecycle():
    clear_stop_request()
    assert not is_stop_requested()
    signal_stop()
    assert is_stop_requested()

    clear_stop_request()
    assert not is_stop_requested()


def test_request_stop_when_idle():
    clear_stop_request()
    assert request_stop_optimization() is False


def test_worker_busy_when_idle():
    assert worker_busy() is False
