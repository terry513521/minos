from __future__ import annotations

import logging
import threading
from typing import Callable

from app.state import best_store

logger = logging.getLogger(__name__)

_stop_requested = threading.Event()
_abort_hook: Callable[[], None] | None = None
_abort_lock = threading.Lock()


def clear_stop_request() -> None:
    _stop_requested.clear()


def is_stop_requested() -> bool:
    return _stop_requested.is_set()


def set_abort_hook(hook: Callable[[], None] | None) -> None:
    global _abort_hook
    with _abort_lock:
        _abort_hook = hook


def _run_abort_hook() -> None:
    with _abort_lock:
        hook = _abort_hook
    if hook is not None:
        try:
            hook()
        except Exception:
            logger.exception("Abort hook failed during stop")


def request_stop_optimization() -> bool:
    """Signal the active job to stop cooperatively and run any abort hook."""
    if not _stop_requested.is_set():
        _stop_requested.set()
        snap = best_store.snapshot()
        if snap.status in ("optimizing", "stopping"):
            best_store.set_stopping(message="Stop requested — cancelling pending trials…")
        _run_abort_hook()
        logger.info("Optimization stop requested")
    return True
