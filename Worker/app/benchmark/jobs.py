"""Serialize standalone /benchmark requests on the worker."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.benchmark.engine import run_benchmark
from app.config import Settings

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
        try:
            return run_benchmark(
                window=window,
                tool=tool,
                conf=conf,
                settings=settings,
            )
        finally:
            logger.info("benchmark finished window=%s tool=%s", window, tool)
