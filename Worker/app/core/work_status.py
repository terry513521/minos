"""Terminal-friendly worker activity reporting."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from app.domain.state import best_store

logger = logging.getLogger(__name__)

_PHASE_LABELS = {
    "bam": "preparing BAM slice",
    "call": "variant calling",
    "score": "hap.py scoring",
}


class WorkPhase(str, Enum):
    BAM = "bam"
    CALL = "call"
    SCORE = "score"


@dataclass(frozen=True)
class BenchmarkActivity:
    window: str
    tool: str


_lock = threading.Lock()
_phase: WorkPhase | None = None
_benchmark: BenchmarkActivity | None = None
_reporter_thread: threading.Thread | None = None
_reporter_stop = threading.Event()


def set_work_phase(phase: WorkPhase | None) -> None:
    with _lock:
        global _phase
        _phase = phase


def set_benchmark_activity(window: str | None, tool: str | None = None) -> None:
    with _lock:
        global _benchmark
        if window and tool:
            _benchmark = BenchmarkActivity(window=window, tool=tool.lower().strip())
        else:
            _benchmark = None


def _phase_label(phase: WorkPhase | None) -> str | None:
    if phase is None:
        return None
    return _PHASE_LABELS.get(phase.value)


def format_worker_status(
    *,
    snapshot=None,
    benchmark: BenchmarkActivity | None = None,
    phase: WorkPhase | None = None,
) -> str | None:
    """Return a one-line status summary, or None when idle."""
    snap = snapshot if snapshot is not None else best_store.snapshot()

    with _lock:
        bench = benchmark if benchmark is not None else _benchmark
        current_phase = phase if phase is not None else _phase

    if snap.status in ("optimizing", "benchmarking", "stopping"):
        parts = [f"[worker] {snap.status}"]
        if snap.tool:
            parts.append(snap.tool)
        if snap.window:
            parts.append(snap.window)
        if snap.search_space_size > 0:
            parts.append(f"trial {snap.trials_evaluated}/{snap.search_space_size}")
        elif snap.trials_evaluated > 0:
            parts.append(f"trial {snap.trials_evaluated}")
        if snap.best_score is not None:
            parts.append(f"best {snap.best_score:.4f}")
        phase_text = _phase_label(current_phase)
        if phase_text:
            parts.append(phase_text)
        elif snap.message:
            parts.append(snap.message)
        return " · ".join(parts)

    if bench is not None:
        parts = [f"[worker] benchmark", bench.tool, bench.window]
        phase_text = _phase_label(current_phase)
        if phase_text:
            parts.append(phase_text)
        return " · ".join(parts)

    return None


def log_worker_status(force: bool = False) -> None:
    line = format_worker_status()
    if line:
        logger.info(line)
    elif force:
        logger.info("[worker] idle")


def _reporter_loop(interval_sec: float) -> None:
    last_line: str | None = None
    while not _reporter_stop.wait(interval_sec):
        line = format_worker_status()
        if not line:
            last_line = None
            continue
        if line != last_line:
            logger.info(line)
            last_line = line


def start_status_reporter(interval_sec: float | None = None) -> None:
    global _reporter_thread
    if interval_sec is None:
        raw = os.getenv("WORKER_STATUS_INTERVAL_SEC", "20").strip()
        try:
            interval_sec = float(raw)
        except ValueError:
            interval_sec = 20.0
    if interval_sec <= 0:
        return

    with _lock:
        if _reporter_thread is not None and _reporter_thread.is_alive():
            return
        _reporter_stop.clear()
        _reporter_thread = threading.Thread(
            target=_reporter_loop,
            args=(interval_sec,),
            name="worker-status-reporter",
            daemon=True,
        )
        _reporter_thread.start()
        logger.info("[worker] status reporter every %.0fs (set WORKER_STATUS_INTERVAL_SEC=0 to disable)", interval_sec)


def stop_status_reporter() -> None:
    _reporter_stop.set()


@contextmanager
def work_status_context(*, window: str, tool: str, phase: WorkPhase | None = None):
    set_benchmark_activity(window, tool)
    if phase is not None:
        set_work_phase(phase)
    log_worker_status(force=True)
    try:
        yield
    finally:
        set_work_phase(None)
        set_benchmark_activity(None, None)
