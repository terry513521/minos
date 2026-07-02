from __future__ import annotations

import logging
import threading

from app.state import best_store

logger = logging.getLogger(__name__)

_stop_requested = threading.Event()


def clear_stop_request() -> None:
    _stop_requested.clear()


def is_stop_requested() -> bool:
    return _stop_requested.is_set()


def request_stop_optimization() -> bool:
    """Signal the active job to stop after the current trial."""
    if not _stop_requested.is_set():
        _stop_requested.set()
        snap = best_store.snapshot()
        if snap.status == "optimizing":
            best_store.set_progress(
                trials_evaluated=snap.trials_evaluated,
                message="Stop requested — finishing current trial…",
            )
        logger.info("Optimization stop requested")
    return True
