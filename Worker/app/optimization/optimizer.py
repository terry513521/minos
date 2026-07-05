from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.optimization.search_runners import run_adaptive_search
from app.optimization.algorithms import normalize_algorithm
from app.benchmark import BenchmarkResult, run_benchmark, validate_benchmark_assets, validate_tool_supported
from app.config import Settings, get_settings
from app.optimization.job_control import is_stop_requested
from app.domain.schemas import OptimizeRequest, OptimizeResponse
from app.optimization.task_info import format_task_banner, format_task_line, task_fields_from_request
from app.optimization.search import (
    build_optimization_plan,
    count_search_trials,
    format_optimization_plan,
)
from app.domain.state import best_store
from app.core.window import resolve_benchmark_window
from app.paths import WORKER_ROOT

logger = logging.getLogger(__name__)


def resolve_adaptive_max_trials(request: OptimizeRequest, settings: Settings) -> int:
    if request.adaptive_max_trials is not None:
        return max(0, int(request.adaptive_max_trials))
    return settings.adaptive_max_trials


def validate_optimize_request(request: OptimizeRequest, settings: Settings | None = None) -> int:
    """Validate payload and return search space size (no benchmarks)."""
    settings = settings or get_settings()
    adaptive_max_trials = resolve_adaptive_max_trials(request, settings)
    validate_tool_supported(request.tool)
    algorithm = normalize_algorithm(request.algorithm)
    _parse_limit_seconds(request.limit)
    _parse_concurrency(request.concurrency)
    from app.benchmark import validate_benchmark_assets

    benchmark_window, _ = resolve_benchmark_window(
        request.window, settings.benchmark_subwindow_mb, seed=request.job_id
    )
    validate_benchmark_assets(benchmark_window, settings)
    intervals = _intervals_payload(request)
    include_base = request.include_base_benchmark
    search_space_size = count_search_trials(
        request.base_conf,
        request.tool,
        request.params,
        intervals,
        algorithm=algorithm,
        adaptive_max_trials=adaptive_max_trials,
        include_base_benchmark=include_base,
    )
    if search_space_size <= 0:
        raise ValueError(
            "No trials planned: enable base conf benchmark or set search trials > 0"
        )
    return search_space_size


def _intervals_payload(request: OptimizeRequest) -> dict[str, Any] | None:
    if not request.param_intervals:
        return None
    return {
        name: spec.model_dump(exclude_none=True)
        for name, spec in request.param_intervals.items()
        if name in request.params
    }


def build_accept_response(
    request: OptimizeRequest,
    settings: Settings | None,
    search_space_size: int,
) -> OptimizeResponse:
    settings = settings or get_settings()
    return OptimizeResponse(
        status="accepted",
        worker=settings.name,
        job_id=request.job_id,
        window=request.window,
        tool=request.tool,
        concurrency=request.concurrency,
        algorithm=normalize_algorithm(request.algorithm),
        limit=request.limit,
        params=request.params,
        search_space_size=search_space_size,
        trials_evaluated=0,
        best_score=None,
        best_conf={},
        message="Optimization started; poll GET /best for live best score and conf",
    )


def _parse_limit_seconds(raw: str) -> int:
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid limit: {raw!r}") from exc
    if value <= 0:
        raise ValueError("limit must be a positive number of seconds")
    return value


def _parse_concurrency(raw: str) -> int:
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid concurrency: {raw!r}") from exc
    if value <= 0:
        raise ValueError("concurrency must be >= 1")
    return value


def _runtime_resources(base_conf: dict[str, Any], settings: Settings) -> tuple[int, int]:
    threads = int(base_conf.get("threads") or settings.trial_threads)
    memory_gb = int(base_conf.get("memory_gb") or settings.trial_memory_gb)
    return threads, memory_gb


def _evaluate_conf(
    request: OptimizeRequest,
    conf: dict[str, Any],
    work_root: Path,
    settings: Settings,
) -> BenchmarkResult:
    trial_dir = work_root / f"trial_{uuid.uuid4().hex[:12]}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    try:
        return run_benchmark(
            window=request.window,
            tool=request.tool,
            conf=conf,
            work_dir=trial_dir,
            settings=settings,
        )
    finally:
        shutil.rmtree(trial_dir, ignore_errors=True)


def _shutdown_executor(pool: ThreadPoolExecutor) -> None:
    pool.shutdown(wait=False, cancel_futures=True)


def _run_parallel_grid(
    *,
    candidate_variants: list[dict[str, Any]],
    concurrency: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    label: str = "trial",
) -> None:
    pool = ThreadPoolExecutor(max_workers=concurrency)
    futures = []
    try:
        for conf in candidate_variants:
            if timed_out():
                break
            futures.append(pool.submit(evaluate, conf))
        for future in as_completed(futures):
            if timed_out():
                break
            try:
                record_result(future.result(), label)
            except Exception as exc:
                logger.warning("Trial task failed: %s", exc)
    finally:
        _shutdown_executor(pool)


def _run_adaptive_search(
    *,
    request: OptimizeRequest,
    base_conf: dict[str, Any],
    intervals: dict[str, Any] | None,
    algorithm: str,
    concurrency: int,
    max_trials: int,
    work_root: Path,
    settings: Settings,
    timed_out: Callable[[], bool],
    record_result: Callable[[BenchmarkResult, str], None],
    anchor_conf: dict[str, Any] | None = None,
) -> None:
    evaluate = lambda conf: _evaluate_conf(request, conf, work_root, settings)
    run_adaptive_search(
        request=request,
        base_conf=base_conf,
        intervals=intervals,
        algorithm=algorithm,
        concurrency=concurrency,
        max_trials=max_trials,
        timed_out=timed_out,
        evaluate=evaluate,
        record_result=record_result,
        run_batch=_run_parallel_grid,
        anchor_conf=anchor_conf,
    )


def optimize_job(request: OptimizeRequest, settings: Settings | None = None) -> OptimizeResponse:
    settings = settings or get_settings()
    worker_name = settings.name
    algorithm = normalize_algorithm(request.algorithm)
    adaptive_max_trials = resolve_adaptive_max_trials(request, settings)
    benchmark_window, source_window = resolve_benchmark_window(
        request.window, settings.benchmark_subwindow_mb, seed=request.job_id
    )
    job_request = request.model_copy(update={"window": benchmark_window})
    limit_seconds = _parse_limit_seconds(request.limit)
    deadline = time.time() + limit_seconds
    concurrency = _parse_concurrency(request.concurrency)
    intervals = _intervals_payload(request)
    include_base = request.include_base_benchmark

    plan = build_optimization_plan(
        window=request.window,
        tool=job_request.tool,
        params=job_request.params,
        param_intervals=intervals,
        base_conf=job_request.base_conf,
        concurrency=concurrency,
        limit_seconds=limit_seconds,
        algorithm=algorithm,
        adaptive_max_trials=adaptive_max_trials,
        include_base_benchmark=include_base,
        vcf_cache_enabled=True,
        gatk_persistent_container=False,
        benchmark_window=benchmark_window,
        trial_threads=settings.trial_threads,
        trial_memory_gb=settings.trial_memory_gb,
        delta_rounds=request.delta_rounds,
    )
    plan_text = format_optimization_plan(plan)
    logger.info("\n%s", plan_text)
    search_space_size = int(plan["planned_trials"])

    threads, memory_gb = _runtime_resources(job_request.base_conf, settings)
    task = task_fields_from_request(
        algorithm=algorithm,
        concurrency=concurrency,
        limit_seconds=limit_seconds,
        adaptive_max_trials=adaptive_max_trials,
        params=list(job_request.params),
        trial_threads=threads,
        trial_memory_gb=memory_gb,
        benchmark_window=benchmark_window,
    )
    logger.info(
        "\n%s",
        format_task_banner(
            worker=worker_name,
            job_id=request.job_id,
            window=request.window,
            tool=job_request.tool,
            algorithm=algorithm,
            planned_trials=search_space_size,
            adaptive_max_trials=adaptive_max_trials,
            concurrency=concurrency,
            limit_seconds=limit_seconds,
            params=list(job_request.params),
            trial_threads=threads,
            trial_memory_gb=memory_gb,
            benchmark_window=task["benchmark_window"],
        ),
    )

    best_store.begin_job(
        request.job_id,
        request.window,
        job_request.tool,
        search_space_size=search_space_size,
        **task,
    )
    progress_msg = format_task_line(
        tool=job_request.tool,
        window=request.window,
        algorithm=algorithm,
        trials_evaluated=0,
        search_space_size=search_space_size,
        concurrency=concurrency,
        status="benchmarking" if adaptive_max_trials <= 0 else "optimizing",
    )
    if task.get("benchmark_window") and task["benchmark_window"] != request.window:
        progress_msg += f" · slice {task['benchmark_window']}"
    best_store.set_progress(
        trials_evaluated=0,
        message=progress_msg,
    )
    work_root = WORKER_ROOT / "runs" / request.job_id
    work_root.mkdir(parents=True, exist_ok=True)

    logger.info("Benchmark: GIAB (Worker/datasets/giab)")

    try:
        from app.benchmark.giab.data import ensure_bam_for_region

        logger.info("Preparing GIAB BAM slice for %s", benchmark_window)
        ensure_bam_for_region(benchmark_window)
        best_score: float | None = None
        best_conf = deepcopy(request.base_conf)
        trials_evaluated = 0
        errors: list[str] = []
        best_lock = threading.Lock()

        def record_result(result: BenchmarkResult, label: str = "trial") -> None:
            nonlocal best_score, best_conf, trials_evaluated
            trials_evaluated += 1
            progress = format_task_line(
                tool=job_request.tool,
                window=request.window,
                algorithm=algorithm,
                trials_evaluated=trials_evaluated,
                search_space_size=search_space_size,
                concurrency=concurrency,
            )
            progress += f" ({label})"
            if result.cached:
                progress += " · cache hit"
            if result.success:
                progress += f" · score {result.score:.4f} (raw {result.raw_score:.2f})"
            else:
                progress += " · failed"
            logger.info("%s", progress)
            best_store.set_progress(trials_evaluated=trials_evaluated, message=progress)

            is_best = False
            if result.success:
                with best_lock:
                    if best_score is None or result.score > best_score:
                        best_score = result.score
                        best_conf = deepcopy(result.conf)
                        is_best = True
                        best_store.update_best(
                            score=result.score,
                            conf=result.conf,
                            trials_evaluated=trials_evaluated,
                            message=f"{progress} · new best",
                        )

            best_store.record_trial(
                index=trials_evaluated,
                label=label,
                success=result.success,
                score=result.score if result.success else None,
                raw_score=result.raw_score if result.success else None,
                cached=result.cached,
                error=result.error,
                is_best=is_best,
            )

            if not result.success and result.error:
                errors.append(result.error)
                logger.warning("Trial error: %s", result.error)

        if not is_stop_requested() and include_base:
            logger.info("Trial 1/%s (base conf)", search_space_size)
            base_result = _evaluate_conf(
                job_request, job_request.base_conf, work_root, settings
            )
            record_result(base_result, "base conf")
        elif not is_stop_requested() and not include_base:
            logger.info("Skipping base conf benchmark — search trials only")
        else:
            logger.info("Stop requested before base trial — skipping optimization")

        def timed_out() -> bool:
            return time.time() >= deadline or is_stop_requested()

        if adaptive_max_trials > 0 and not timed_out():
            logger.info(
                "Starting %s search: up to %s trials after base",
                algorithm,
                adaptive_max_trials,
            )
            _run_adaptive_search(
                request=job_request,
                base_conf=job_request.base_conf,
                intervals=intervals,
                algorithm=algorithm,
                concurrency=concurrency,
                max_trials=adaptive_max_trials,
                work_root=work_root,
                settings=settings,
                timed_out=timed_out,
                record_result=record_result,
                anchor_conf=best_conf,
            )
        elif adaptive_max_trials <= 0:
            logger.info("Benchmark-only job — skipping search after base conf")

        if best_score is None:
            message = errors[0] if errors else "No successful benchmark trials"
            if is_stop_requested():
                message = "Stopped — no successful trials completed"
            best_store.fail_job(message=message)
            return OptimizeResponse(
                status="error",
                worker=worker_name,
                job_id=request.job_id,
                window=request.window,
                tool=job_request.tool,
                concurrency=request.concurrency,
                algorithm=algorithm,
                limit=request.limit,
                params=request.params,
                search_space_size=search_space_size,
                trials_evaluated=trials_evaluated,
                best_score=0.0,
                best_conf=deepcopy(request.base_conf),
                message=message,
            )

        finish_message = (
            f"Done: {trials_evaluated}/{search_space_size} trials · best {best_score:.4f} · "
            f"{plan['mode']} · reference space {plan['full_cartesian_grid']} configs"
        )
        if is_stop_requested():
            finish_message += " (stopped by user)"
        elif time.time() >= deadline:
            finish_message += " (stopped at time limit)"
        best_store.finish_job(message=finish_message)

        return OptimizeResponse(
            status="completed",
            worker=worker_name,
            job_id=request.job_id,
            window=request.window,
            tool=job_request.tool,
            concurrency=request.concurrency,
            algorithm=algorithm,
            limit=request.limit,
            params=request.params,
            search_space_size=search_space_size,
            trials_evaluated=trials_evaluated,
            best_score=best_score,
            best_conf=best_conf,
            message=finish_message,
        )
    except Exception:
        logger.exception("Optimization job failed")
        raise
