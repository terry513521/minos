"""Serialize standalone /benchmark requests on the worker."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.benchmark.engine import run_benchmark
from app.config import Settings
from app.core.work_status import log_worker_status, work_status_context

logger = logging.getLogger(__name__)

_benchmark_lock = threading.Lock()


def run_benchmark_exclusive(
    *,
    window: str,
    tool: str,
    conf: dict[str, Any],
    settings: Settings,
) -> Any:
    """Run one GIAB benchmark; only one /benchmark at a time per worker process."""
    with _benchmark_lock:
        logger.info("benchmark start window=%s tool=%s", window, tool)
        with work_status_context(window=window, tool=tool):
            result = run_benchmark(
                window=window,
                tool=tool,
                conf=conf,
                settings=settings,
            )
            if result.success:
                logger.info(
                    "benchmark done window=%s tool=%s score=%.4f cached=%s",
                    window,
                    tool,
                    result.score,
                    result.cached,
                )
            else:
                logger.warning(
                    "benchmark failed window=%s tool=%s error=%s",
                    window,
                    tool,
                    result.error,
                )
        return result
