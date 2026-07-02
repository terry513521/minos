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

from app.adaptive_search import (
    build_conf_from_params,
    create_optuna_study,
    resolve_search_specs,
    suggest_optuna_params,
    suggest_random_params,
)
from app.algorithms import is_adaptive_algorithm, normalize_algorithm
from app.assets import WORKER_ROOT, resolve_assets
from app.benchmark import BenchmarkResult, conf_equals, run_benchmark
from app.config import Settings, get_settings
from app.job_control import is_stop_requested
from app.schemas import OptimizeRequest, OptimizeResponse
from app.search import (
    build_optimization_plan,
    build_search_space,
    count_search_trials,
    filter_param_intervals,
    format_optimization_plan,
    split_params_for_lanes,
)
from app.state import best_store
from app.window_utils import resolve_benchmark_window

logger = logging.getLogger(__name__)


def validate_optimize_request(request: OptimizeRequest, settings: Settings | None = None) -> int:
    """Validate payload and return search space size (no benchmarks)."""
    settings = settings or get_settings()
    algorithm = normalize_algorithm(request.algorithm)
    _parse_limit_seconds(request.limit)
    _parse_concurrency(request.concurrency)
    from app.assets import validate_benchmark_assets

    benchmark_window, _ = resolve_benchmark_window(request.window, settings.benchmark_subwindow_mb)
    validate_benchmark_assets(benchmark_window, settings)
    resolve_assets(benchmark_window, settings)
    intervals = _intervals_payload(request)
    concurrency = _parse_concurrency(request.concurrency)
    param_split = (
        settings.param_split_concurrency
        and concurrency > 1
        and len(request.params) > 1
        and not is_adaptive_algorithm(algorithm)
    )
    return count_search_trials(
        request.base_conf,
        request.tool,
        request.params,
        intervals,
        concurrency=concurrency,
        param_split=param_split,
        algorithm=algorithm,
        adaptive_max_trials=settings.adaptive_max_trials,
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
    gatk_pool: Any | None = None,
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
            gatk_pool=gatk_pool,
        )
    finally:
        shutil.rmtree(trial_dir, ignore_errors=True)


def _run_parallel_grid(
    *,
    candidate_variants: list[dict[str, Any]],
    concurrency: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    label: str = "trial",
) -> None:
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for conf in candidate_variants:
            if timed_out():
                break
            futures.append(pool.submit(evaluate, conf))
        for future in as_completed(futures):
            if timed_out():
                break
            record_result(future.result(), label)


def _run_param_split_lanes(
    *,
    request: OptimizeRequest,
    base_conf: dict[str, Any],
    intervals: dict[str, Any] | None,
    concurrency: int,
    work_root: Path,
    settings: Settings,
    gatk_pool: Any | None,
    timed_out: Callable[[], bool],
    record_result: Callable[[BenchmarkResult, str], None],
) -> None:
    """Each lane tunes a different param subset; lanes run in parallel."""
    lanes = split_params_for_lanes(request.params, concurrency)
    lane_variants: list[tuple[list[str], list[dict[str, Any]]]] = []

    for lane_params in lanes:
        lane_intervals = filter_param_intervals(intervals, lane_params)
        variants = build_search_space(base_conf, request.tool, lane_params, lane_intervals)
        candidates = [conf for conf in variants if not conf_equals(conf, base_conf)]
        lane_variants.append((lane_params, candidates))

    def run_lane(lane_params: list[str], candidates: list[dict[str, Any]]) -> None:
        logger.info(
            "Lane start: params [%s] · %s trial(s)",
            ", ".join(lane_params),
            len(candidates),
        )
        for conf in candidates:
            if timed_out():
                return
            record_result(
                _evaluate_conf(request, conf, work_root, settings, gatk_pool),
                f"lane [{', '.join(lane_params)}]",
            )

    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        futures = [
            pool.submit(run_lane, lane_params, candidates)
            for lane_params, candidates in lane_variants
        ]
        for future in as_completed(futures):
            if timed_out():
                break
            future.result()


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
    gatk_pool: Any | None,
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

    evaluate = lambda conf: _evaluate_conf(request, conf, work_root, settings, gatk_pool)

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

    import optuna

    study = create_optuna_study()
    while not timed_out() and extra_done < max_trials:
        trial = study.ask()
        params = suggest_optuna_params(trial, base_conf, request.tool, specs)
        conf = build_conf_from_params(base_conf, request.tool, params)
        if not remember(conf):
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
            continue
        result = evaluate(conf)
        record_result(result, "optuna")
        extra_done += 1
        if result.success:
            study.tell(trial, result.score)
        else:
            study.tell(trial, state=optuna.trial.TrialState.FAIL)


def optimize_job(request: OptimizeRequest, settings: Settings | None = None) -> OptimizeResponse:
    settings = settings or get_settings()
    worker_name = settings.name
    algorithm = normalize_algorithm(request.algorithm)
    benchmark_window, source_window = resolve_benchmark_window(
        request.window, settings.benchmark_subwindow_mb
    )
    job_request = request.model_copy(update={"window": benchmark_window})
    limit_seconds = _parse_limit_seconds(request.limit)
    deadline = time.time() + limit_seconds
    concurrency = _parse_concurrency(request.concurrency)
    intervals = _intervals_payload(request)

    use_param_split = (
        settings.param_split_concurrency
        and concurrency > 1
        and len(request.params) > 1
        and not is_adaptive_algorithm(algorithm)
    )
    plan = build_optimization_plan(
        window=benchmark_window,
        tool=job_request.tool,
        params=job_request.params,
        param_intervals=intervals,
        base_conf=job_request.base_conf,
        concurrency=concurrency,
        param_split=use_param_split,
        limit_seconds=limit_seconds,
        algorithm=algorithm,
        adaptive_max_trials=settings.adaptive_max_trials,
        vcf_cache_enabled=settings.vcf_cache_enabled,
        gatk_persistent_container=settings.gatk_persistent_container,
        source_window=source_window,
        trial_threads=settings.trial_threads,
        trial_memory_gb=settings.trial_memory_gb,
    )
    plan_text = format_optimization_plan(plan)
    logger.info("\n%s", plan_text)
    search_space_size = int(plan["planned_trials"])

    best_store.begin_job(
        request.job_id,
        benchmark_window,
        job_request.tool,
        search_space_size=search_space_size,
    )
    best_store.set_progress(
        trials_evaluated=0,
        message=(
            f"Planned {search_space_size} trials · {plan['mode']} · "
            f"{plan['param_count']} params"
        ),
    )
    work_root = WORKER_ROOT / "runs" / request.job_id
    work_root.mkdir(parents=True, exist_ok=True)

    gatk_pool = None
    try:
        if settings.gatk_persistent_container and job_request.tool.lower() == "gatk":
            assets = resolve_assets(benchmark_window, settings)
            threads, memory_gb = _runtime_resources(settings, job_request.base_conf)
            from app.gatk_container import GatkContainerPool

            gatk_pool = GatkContainerPool(
                job_id=request.job_id,
                bam_path=assets.bam_path,
                reference_path=assets.reference_fasta,
                output_parent=work_root,
                slots=concurrency,
                threads=threads,
                memory_gb=memory_gb,
            )
            logger.info(
                "Persistent GATK pool: %s container(s), %s threads, %s GB",
                concurrency,
                threads,
                memory_gb,
            )

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
            if not result.success:
                if result.error:
                    errors.append(result.error)
                    logger.warning("Trial error: %s", result.error)
                return
            with best_lock:
                if best_score is None or result.score > best_score:
                    best_score = result.score
                    best_conf = deepcopy(result.conf)
                    best_store.update_best(
                        score=result.score,
                        conf=result.conf,
                        trials_evaluated=trials_evaluated,
                        message=f"{progress} · new best",
                    )

        logger.info("Trial 1/%s (base conf)", search_space_size)
        base_result = _evaluate_conf(
            job_request, job_request.base_conf, work_root, settings, gatk_pool
        )
        record_result(base_result, "base conf")

        def timed_out() -> bool:
            return time.time() >= deadline or is_stop_requested()

        if not timed_out():
            if is_adaptive_algorithm(algorithm):
                logger.info(
                    "Starting %s search: up to %s trials after base",
                    algorithm,
                    settings.adaptive_max_trials,
                )
                _run_adaptive_search(
                    request=job_request,
                    base_conf=job_request.base_conf,
                    intervals=intervals,
                    algorithm=algorithm,
                    concurrency=concurrency,
                    max_trials=settings.adaptive_max_trials,
                    work_root=work_root,
                    settings=settings,
                    gatk_pool=gatk_pool,
                    timed_out=timed_out,
                    record_result=record_result,
                )
            elif use_param_split:
                logger.info(
                    "Starting param-split search: %s lane(s), %s trials after base",
                    len(plan["lanes"]),
                    max(0, search_space_size - 1),
                )
                _run_param_split_lanes(
                    request=job_request,
                    base_conf=job_request.base_conf,
                    intervals=intervals,
                    concurrency=concurrency,
                    work_root=work_root,
                    settings=settings,
                    gatk_pool=gatk_pool,
                    timed_out=timed_out,
                    record_result=record_result,
                )
            else:
                variants = build_search_space(
                    job_request.base_conf, job_request.tool, job_request.params, intervals
                )
                candidate_variants = [
                    v for v in variants if not conf_equals(v, job_request.base_conf)
                ]
                logger.info(
                    "Starting full grid: %s configs (%s trials after base), concurrency %s",
                    plan["full_cartesian_grid"],
                    len(candidate_variants),
                    concurrency,
                )
                if candidate_variants:
                    evaluate = lambda conf: _evaluate_conf(
                        job_request, conf, work_root, settings, gatk_pool
                    )
                    _run_parallel_grid(
                        candidate_variants=candidate_variants,
                        concurrency=concurrency,
                        timed_out=timed_out,
                        evaluate=evaluate,
                        record_result=record_result,
                    )

        if best_score is None:
            message = errors[0] if errors else "No successful benchmark trials"
            best_store.fail_job(message=message)
            return OptimizeResponse(
                status="error",
                worker=worker_name,
                job_id=request.job_id,
                window=benchmark_window,
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
            f"{plan['mode']} · Cartesian {plan['full_cartesian_grid']}"
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
            window=benchmark_window,
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
    finally:
        if gatk_pool is not None:
            gatk_pool.stop_all()
