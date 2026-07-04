"""Format optimization task metadata for logs and API responses."""

from __future__ import annotations

from typing import Any


def format_task_banner(
    *,
    worker: str,
    job_id: str,
    window: str,
    tool: str,
    algorithm: str,
    planned_trials: int,
    adaptive_max_trials: int,
    concurrency: int,
    limit_seconds: int,
    params: list[str],
    trial_threads: int | None = None,
    trial_memory_gb: int | None = None,
    benchmark_window: str | None = None,
) -> str:
    """Multi-line task summary for worker logs."""
    lines = [
        "=== Worker task ===",
        f"  worker: {worker}",
        f"  job_id: {job_id}",
        f"  region: {window}",
    ]
    if benchmark_window and benchmark_window != window:
        lines.append(f"  benchmark slice: {benchmark_window}")
    lines.extend([
        f"  tool: {tool}",
        f"  algorithm: {algorithm}",
        f"  trials: 1 base + {adaptive_max_trials} search ({planned_trials} planned)",
        f"  concurrency: {concurrency}",
    ])
    if trial_threads is not None and trial_memory_gb is not None:
        lines.append(f"  per slot: {trial_threads} CPUs, {trial_memory_gb} GB RAM")
    lines.append(f"  params ({len(params)}): {', '.join(params) if params else '(none)'}")
    lines.append(f"  limit: {limit_seconds}s")
    return "\n".join(lines)


def format_task_line(
    *,
    tool: str | None,
    window: str | None,
    algorithm: str | None,
    trials_evaluated: int = 0,
    search_space_size: int = 0,
    concurrency: int | None = None,
    status: str | None = None,
) -> str:
    """Compact one-line task summary for progress messages."""
    parts: list[str] = []
    if tool:
        parts.append(tool)
    if window:
        parts.append(window)
    if algorithm:
        parts.append(algorithm)
    if search_space_size > 0:
        parts.append(f"trial {trials_evaluated}/{search_space_size}")
    elif trials_evaluated > 0:
        parts.append(f"trial {trials_evaluated}")
    if concurrency and concurrency > 1:
        parts.append(f"×{concurrency}")
    if status and status not in ("ready", "idle"):
        parts.append(status)
    return " · ".join(parts)


def task_fields_from_request(
    *,
    algorithm: str,
    concurrency: int,
    limit_seconds: int,
    adaptive_max_trials: int,
    params: list[str],
    trial_threads: int | None,
    trial_memory_gb: int | None,
    benchmark_window: str | None,
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "concurrency": concurrency,
        "limit_seconds": limit_seconds,
        "adaptive_max_trials": adaptive_max_trials,
        "params": list(params),
        "trial_threads": trial_threads,
        "trial_memory_gb": trial_memory_gb,
        "benchmark_window": benchmark_window,
    }
