"""Background execution for POST /seed/batch."""

from __future__ import annotations

import logging
import threading

from app.benchmark import validate_benchmark_assets, validate_tool_supported
from app.benchmark.jobs import run_benchmark_exclusive
from app.config import Settings, get_settings
from app.optimization.jobs import worker_busy
from app.seed import store

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active_thread: threading.Thread | None = None


def seed_busy() -> bool:
    with _lock:
        return _active_thread is not None and _active_thread.is_alive()


def submit_seed_batch(
    *,
    batch_id: str | None,
    items: list[dict],
    settings: Settings | None = None,
) -> tuple[str, int, int]:
    """Queue seed work and start background runner when idle."""
    settings = settings or get_settings()
    resolved_batch, queued, skipped = store.enqueue_batch(batch_id=batch_id, entries=items)
    if queued <= 0:
        return resolved_batch, queued, skipped
    _start_runner(settings)
    return resolved_batch, queued, skipped


def _start_runner(settings: Settings) -> None:
    global _active_thread
    with _lock:
        if _active_thread is not None and _active_thread.is_alive():
            return

        def _run() -> None:
            _run_pending(settings)

        _active_thread = threading.Thread(
            target=_run,
            name="seed-batch",
            daemon=True,
        )
        _active_thread.start()


def _run_pending(settings: Settings) -> None:
    import time

    while True:
        if worker_busy():
            time.sleep(5)
            continue
        pending = store.next_pending()
        if pending is None:
            logger.info("Seed batch complete")
            return
        source_key = str(pending["source_key"])
        window = str(pending["target_window"])
        tool = str(pending["tool"])
        conf = dict(pending.get("conf") or {})
        store.mark_running(source_key)
        logger.info("Seed benchmark start source_key=%s window=%s tool=%s", source_key, window, tool)
        try:
            validate_tool_supported(tool)
            validate_benchmark_assets(window, settings)
            result = run_benchmark_exclusive(
                window=window,
                tool=tool,
                conf=conf,
                settings=settings,
            )
            if result.success:
                store.mark_result(
                    source_key,
                    success=True,
                    score=result.score,
                    raw_score=result.raw_score,
                    variant_count=result.variant_count,
                    cached=result.cached,
                )
                logger.info(
                    "Seed benchmark done source_key=%s score=%.4f cached=%s",
                    source_key,
                    result.score,
                    result.cached,
                )
            else:
                store.mark_result(
                    source_key,
                    success=False,
                    error=result.error or "Benchmark failed",
                )
                logger.warning(
                    "Seed benchmark failed source_key=%s error=%s",
                    source_key,
                    result.error,
                )
        except Exception as exc:
            store.mark_result(source_key, success=False, error=str(exc))
            logger.exception("Seed benchmark error source_key=%s", source_key)
