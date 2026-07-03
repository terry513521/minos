"""Per-algorithm search loops for Worker optimization jobs."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from typing import Any, Literal

from app.benchmark import BenchmarkResult, conf_equals
from app.optimization.adaptive_search import (
    build_conf_from_params,
    create_optuna_study,
    suggest_optuna_params,
    suggest_random_params,
)
from app.optimization.algorithms import is_optuna_algorithm, normalize_algorithm
from app.optimization.param_specs import TuneSpec
from app.optimization.quasi_random import build_quasi_sample_confs, seed_from_job_id
from app.domain.schemas import OptimizeRequest

logger = logging.getLogger(__name__)

QuasiRandomAlgorithm = Literal["sobol", "lhs"]
OptunaAlgorithm = Literal["optuna", "gp"]


class ConfMemory:
    """Track configs already tried (and skip duplicate base conf)."""

    def __init__(self, base_conf: dict[str, Any]) -> None:
        self._base_conf = base_conf
        self._seen: set[str] = set()

    def remember(self, conf: dict[str, Any]) -> bool:
        key = str(conf)
        if key in self._seen or conf_equals(conf, self._base_conf):
            return False
        self._seen.add(key)
        return True


def run_random_search(
    *,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    concurrency: int,
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    run_batch: Callable[..., None],
) -> None:
    memory = ConfMemory(base_conf)
    extra_done = 0
    rng = random.Random()

    while not timed_out() and extra_done < max_trials:
        batch: list[dict[str, Any]] = []
        attempts = 0
        while len(batch) < concurrency and attempts < concurrency * 20:
            attempts += 1
            params = suggest_random_params(rng, base_conf, tool, specs)
            conf = build_conf_from_params(base_conf, tool, params)
            if memory.remember(conf):
                batch.append(conf)
        if not batch:
            logger.info("Random search exhausted unique configs")
            break
        before = extra_done
        run_batch(
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


def run_quasi_random_search(
    algorithm: QuasiRandomAlgorithm,
    *,
    job_id: str,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    concurrency: int,
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    run_batch: Callable[..., None],
) -> None:
    """Sobol or LHS: pre-plan space-filling samples, then benchmark in batches."""
    memory = ConfMemory(base_conf)
    seed = seed_from_job_id(job_id)
    param_sets = build_quasi_sample_confs(
        algorithm,
        n=max_trials,
        base_conf=base_conf,
        tool=tool,
        specs=specs,
        seed=seed,
    )
    extra_done = 0
    idx = 0

    while not timed_out() and extra_done < max_trials and idx < len(param_sets):
        batch: list[dict[str, Any]] = []
        while (
            len(batch) < concurrency
            and idx < len(param_sets)
            and extra_done + len(batch) < max_trials
        ):
            conf = build_conf_from_params(base_conf, tool, param_sets[idx])
            idx += 1
            if memory.remember(conf):
                batch.append(conf)
        if not batch:
            logger.info("%s search exhausted unique configs", algorithm.upper())
            break
        before = extra_done
        run_batch(
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


def run_gp_search(
    *,
    job_id: str,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
) -> None:
    """Gaussian-process Bayesian optimization via Optuna GPSampler."""
    _run_optuna_loop(
        algorithm="gp",
        job_id=job_id,
        base_conf=base_conf,
        tool=tool,
        specs=specs,
        max_trials=max_trials,
        timed_out=timed_out,
        evaluate=evaluate,
        record_result=record_result,
    )


def run_optuna_search(
    *,
    job_id: str,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
) -> None:
    """TPE Bayesian optimization via Optuna."""
    _run_optuna_loop(
        algorithm="optuna",
        job_id=job_id,
        base_conf=base_conf,
        tool=tool,
        specs=specs,
        max_trials=max_trials,
        timed_out=timed_out,
        evaluate=evaluate,
        record_result=record_result,
    )


def _run_optuna_loop(
    *,
    algorithm: OptunaAlgorithm,
    job_id: str,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
) -> None:
    import optuna

    memory = ConfMemory(base_conf)
    seed = seed_from_job_id(job_id)
    study = create_optuna_study(algorithm, seed=seed)
    extra_done = 0

    while not timed_out() and extra_done < max_trials:
        trial = study.ask()
        params = suggest_optuna_params(trial, base_conf, tool, specs)
        conf = build_conf_from_params(base_conf, tool, params)
        if not memory.remember(conf):
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


def run_adaptive_search(
    *,
    request: OptimizeRequest,
    base_conf: dict[str, Any],
    intervals: dict[str, Any] | None,
    algorithm: str,
    concurrency: int,
    max_trials: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    run_batch: Callable[..., None],
) -> None:
    """Dispatch to the search loop for the requested algorithm."""
    from app.optimization.adaptive_search import resolve_search_specs

    algo = normalize_algorithm(algorithm)
    specs = resolve_search_specs(request.tool, request.params, intervals)

    if algo == "random":
        run_random_search(
            base_conf=base_conf,
            tool=request.tool,
            specs=specs,
            concurrency=concurrency,
            max_trials=max_trials,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
            run_batch=run_batch,
        )
        return

    if algo in ("sobol", "lhs"):
        run_quasi_random_search(
            algo,
            job_id=request.job_id,
            base_conf=base_conf,
            tool=request.tool,
            specs=specs,
            concurrency=concurrency,
            max_trials=max_trials,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
            run_batch=run_batch,
        )
        return

    if algo == "gp":
        run_gp_search(
            job_id=request.job_id,
            base_conf=base_conf,
            tool=request.tool,
            specs=specs,
            max_trials=max_trials,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
        )
        return

    if algo == "optuna":
        run_optuna_search(
            job_id=request.job_id,
            base_conf=base_conf,
            tool=request.tool,
            specs=specs,
            max_trials=max_trials,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
        )
        return

    if is_optuna_algorithm(algo):
        raise ValueError(f"Unhandled Optuna algorithm: {algo}")
    raise ValueError(f"Unhandled adaptive algorithm: {algo}")
