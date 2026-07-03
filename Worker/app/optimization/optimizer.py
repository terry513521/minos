from __future__ import annotations

import logging
import random
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.optimization.adaptive_search import (
    build_conf_from_params,
    create_optuna_study,
    resolve_search_specs,
    suggest_optuna_params,
    suggest_random_params,
)
from app.optimization.quasi_random import (
    build_quasi_sample_confs,
    seed_from_job_id,
)
from app.optimization.algorithms import is_optuna_algorithm, normalize_algorithm
from app.benchmark import BenchmarkResult, conf_equals, run_benchmark, validate_benchmark_assets, validate_tool_supported
from app.config import Settings, get_settings
from app.optimization.job_control import is_stop_requested
from app.domain.schemas import OptimizeRequest, OptimizeResponse
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
        return max(1, int(request.adaptive_max_trials))
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
    return count_search_trials(
        request.base_conf,
        request.tool,
        request.params,
        intervals,
        algorithm=algorithm,
        adaptive_max_trials=adaptive_max_trials,
    )


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


def _runtime_resources(settings: Settings, base_conf: dict[str, Any]) -> tuple[int, int]:
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
) -> None:
    specs = resolve_search_specs(request.tool, request.params, intervals)
    seen: set[str] = set()
    extra_done = 0
    rng = random.Random()

    def remember(conf: dict[str, Any]) -> bool:
        key = str(conf)
        if key in seen or conf_equals(conf, base_conf):
            return False
        seen.add(key)
        return True

    evaluate = lambda conf: _evaluate_conf(request, conf, work_root, settings)

    if algorithm == "random":
        while not timed_out() and extra_done < max_trials:
            batch: list[dict[str, Any]] = []
            attempts = 0
            while len(batch) < concurrency and attempts < concurrency * 20:
                attempts += 1
                params = suggest_random_params(rng, base_conf, request.tool, specs)
                conf = build_conf_from_params(base_conf, request.tool, params)
                if remember(conf):
                    batch.append(conf)
            if not batch:
                logger.info("Random search exhausted unique configs")
                break
            before = extra_done
            _run_parallel_grid(
                candidate_variants=batch,
                concurrency=min(concurrency, len(batch)),
                timed_out=timed_out,
                evaluate=evaluate,
                record_result=record_result,
                label="random",
            )
            extra_done += len(batch)
            if extra_done == before:
                break
        return

    if algorithm in ("sobol", "lhs"):
        seed = seed_from_job_id(request.job_id)
        param_sets = build_quasi_sample_confs(
            algorithm,
            n=max_trials,
            base_conf=base_conf,
            tool=request.tool,
            specs=specs,
            seed=seed,
        )
        idx = 0
        while not timed_out() and extra_done < max_trials and idx < len(param_sets):
            batch: list[dict[str, Any]] = []
            while (
                len(batch) < concurrency
                and idx < len(param_sets)
                and extra_done + len(batch) < max_trials
            ):
                conf = build_conf_from_params(base_conf, request.tool, param_sets[idx])
                idx += 1
                if remember(conf):
                    batch.append(conf)
            if not batch:
                logger.info("%s search exhausted unique configs", algorithm.upper())
                break
            before = extra_done
            _run_parallel_grid(
                candidate_variants=batch,
                concurrency=min(concurrency, len(batch)),
                timed_out=timed_out,
                evaluate=evaluate,
                record_result=record_result,
                label=algorithm,
            )
            extra_done += len(batch)
            if extra_done == before:
                break
        return

    if is_optuna_algorithm(algorithm):
        import optuna

        study = create_optuna_study(algorithm)
        while not timed_out() and extra_done < max_trials:
            trial = study.ask()
            params = suggest_optuna_params(trial, base_conf, request.tool, specs)
            conf = build_conf_from_params(base_conf, request.tool, params)
            if not remember(conf):
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                continue
            if timed_out():
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                break
            result = evaluate(conf)
            record_result(result, algorithm)
            extra_done += 1
            if result.success:
                study.tell(trial, result.score)
            else:
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
        return

    raise ValueError(f"Unhandled adaptive algorithm: {algorithm}")


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
        vcf_cache_enabled=True,
        gatk_persistent_container=False,
        benchmark_window=benchmark_window
        if source_window and benchmark_window != request.window
        else None,
        trial_threads=settings.trial_threads,
        trial_memory_gb=settings.trial_memory_gb,
    )
    plan_text = format_optimization_plan(plan)
    logger.info("\n%s", plan_text)
    search_space_size = int(plan["planned_trials"])

    best_store.begin_job(
        request.job_id,
        request.window,
        job_request.tool,
        search_space_size=search_space_size,
    )
    progress_msg = (
        f"Planned {search_space_size} trials · {plan['mode']} · "
        f"{plan['param_count']} params"
    )
    if source_window and source_window != benchmark_window:
        progress_msg += f" · benchmark slice {benchmark_window}"
    best_store.set_progress(
        trials_evaluated=0,
        message=progress_msg,
    )
    work_root = WORKER_ROOT / "runs" / request.job_id
    work_root.mkdir(parents=True, exist_ok=True)

    logger.info("Benchmark: GIAB (Worker/datasets/giab)")

    try:
        best_score: float | None = None
        best_conf = deepcopy(request.base_conf)
        trials_evaluated = 0
        errors: list[str] = []
        best_lock = threading.Lock()

        def record_result(result: BenchmarkResult, label: str = "trial") -> None:
            nonlocal best_score, best_conf, trials_evaluated
            trials_evaluated += 1
            progress = f"Trial {trials_evaluated}/{search_space_size} ({label})"
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

        if not is_stop_requested():
            logger.info("Trial 1/%s (base conf)", search_space_size)
            base_result = _evaluate_conf(
                job_request, job_request.base_conf, work_root, settings
            )
            record_result(base_result, "base conf")
        else:
            logger.info("Stop requested before base trial — skipping optimization")

        def timed_out() -> bool:
            return time.time() >= deadline or is_stop_requested()

        if not timed_out():
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
            )

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
