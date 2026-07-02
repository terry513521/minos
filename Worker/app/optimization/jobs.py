from __future__ import annotations

import logging
import threading

from app.config import Settings
from app.optimization.job_control import clear_stop_request, request_stop_optimization as signal_stop
from app.optimization.optimizer import optimize_job
from app.domain.schemas import OptimizeRequest
from app.domain.state import best_store

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active_thread: threading.Thread | None = None


def worker_busy() -> bool:
    with _lock:
        return _active_thread is not None and _active_thread.is_alive()


def request_stop_optimization() -> bool:
    """Signal the active job to stop after the current trial. Returns True if a job is running."""
    with _lock:
        if _active_thread is None or not _active_thread.is_alive():
            return False
    signal_stop()
    return True


def submit_optimize_job(request: OptimizeRequest, settings: Settings) -> None:
    global _active_thread

    with _lock:
        if _active_thread is not None and _active_thread.is_alive():
            raise RuntimeError("Worker already running an optimization job")

        clear_stop_request()

        def _run() -> None:
            try:
                optimize_job(request, settings)
            except Exception:
                logger.exception("Background optimization failed for job %s", request.job_id)
                snap = best_store.snapshot()
                if snap.status == "optimizing":
                    best_store.fail_job(message="Optimization failed unexpectedly")

        _active_thread = threading.Thread(
            target=_run,
            name=f"optimize-{request.job_id}",
            daemon=True,
        )
        _active_thread.start()
