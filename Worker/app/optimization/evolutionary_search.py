"""Population-based and multistage search for expensive genomic benchmarks.

Designed for GATK-style tuning where each trial is minutes of Docker + hap.py
and many CPU cores can run trials in parallel.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.benchmark import BenchmarkResult
from app.optimization.adaptive_search import (
    build_conf_from_params,
    suggest_random_params,
)
from app.optimization.param_specs import TuneSpec
from app.optimization.quasi_random import build_quasi_sample_confs, seed_from_job_id
from app.optimization.search import _read_param_value, _values_for_param

logger = logging.getLogger(__name__)


@dataclass
class PopulationMember:
    params: dict[str, Any]
    score: float = float("-inf")


@dataclass
class SearchTracker:
    """Track best config seen during a multistage search."""

    best_score: float = float("-inf")
    best_params: dict[str, Any] = field(default_factory=dict)
    best_conf: dict[str, Any] | None = None

    def consider(self, result: BenchmarkResult, params: dict[str, Any]) -> None:
        if not result.success:
            return
        if result.score > self.best_score:
            self.best_score = result.score
            self.best_params = dict(params)
            self.best_conf = result.conf


def extract_params_from_conf(
    conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for spec in specs:
        value = _read_param_value(conf, tool, spec.name)
        if value is not None:
            params[spec.name] = value
    return params


def _index_on_axis(values: list[Any], current: Any) -> int:
    for idx, value in enumerate(values):
        if value == current:
            return idx
    for idx, value in enumerate(values):
        try:
            if float(value) == float(current):
                return idx
        except (TypeError, ValueError):
            continue
    return len(values) // 2


def mutate_params(
    rng: random.Random,
    params: dict[str, Any],
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    *,
    strength: float = 0.3,
) -> dict[str, Any]:
    """Perturb a parameter set on discrete search axes."""
    strength = max(0.05, min(1.0, float(strength)))
    mutated = dict(params)
    if not specs:
        return mutated

    n_mutate = max(1, int(round(len(specs) * strength)))
    chosen = rng.sample(specs, min(n_mutate, len(specs)))
    for spec in chosen:
        values = _values_for_param(base_conf, tool, spec)
        if not values:
            continue
        current = mutated.get(spec.name, values[0])
        if spec.values is not None or len(values) <= 8:
            alternatives = [v for v in values if v != current]
            mutated[spec.name] = rng.choice(alternatives) if alternatives else rng.choice(values)
            continue

        idx = _index_on_axis(values, current)
        max_step = max(1, int(round(len(values) * strength * 0.35)))
        if rng.random() < 0.65:
            delta = rng.randint(-max_step, max_step)
            new_idx = max(0, min(len(values) - 1, idx + delta))
        else:
            new_idx = rng.randint(0, len(values) - 1)
        mutated[spec.name] = values[new_idx]
    return mutated


def generate_local_neighbors(
    params: dict[str, Any],
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    *,
    max_neighbors: int,
) -> list[dict[str, Any]]:
    """Single-parameter ±1 grid moves around a promising config."""
    neighbors: list[dict[str, Any]] = []
    seen: set[str] = set()

    for spec in specs:
        values = _values_for_param(base_conf, tool, spec)
        if len(values) <= 1:
            continue
        current = params.get(spec.name, values[0])
        idx = _index_on_axis(values, current)
        for delta in (-1, 1):
            new_idx = idx + delta
            if 0 <= new_idx < len(values):
                candidate = dict(params)
                candidate[spec.name] = values[new_idx]
                key = str(sorted(candidate.items()))
                if key not in seen:
                    seen.add(key)
                    neighbors.append(candidate)
        if len(neighbors) >= max_neighbors:
            break
    return neighbors[:max_neighbors]


def _eval_param_batch(
    *,
    batch: list[tuple[dict[str, Any], dict[str, Any]]],
    concurrency: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    label: str,
    tracker: SearchTracker | None = None,
) -> list[tuple[dict[str, Any], BenchmarkResult]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not batch:
        return []

    results: list[tuple[dict[str, Any], BenchmarkResult]] = []
    pool = ThreadPoolExecutor(max_workers=max(1, concurrency))
    futures: dict[Any, dict[str, Any]] = {}
    try:
        for conf, params in batch:
            if timed_out():
                break
            futures[pool.submit(evaluate, conf)] = params
        for future in as_completed(futures):
            if timed_out():
                break
            params = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.warning("%s trial failed: %s", label, exc)
                continue
            record_result(result, label)
            if tracker is not None:
                tracker.consider(result, params)
            results.append((params, result))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def _seed_population(
    rng: random.Random,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    pop_size: int,
) -> list[PopulationMember]:
    population: list[PopulationMember] = [
        PopulationMember(params=extract_params_from_conf(base_conf, tool, specs))
    ]
    while len(population) < pop_size:
        params = suggest_random_params(rng, base_conf, tool, specs)
        population.append(PopulationMember(params=params))
    return population


def _merge_population(
    population: list[PopulationMember],
    offspring: list[tuple[dict[str, Any], BenchmarkResult]],
    pop_size: int,
) -> list[PopulationMember]:
    merged = list(population)
    for params, result in offspring:
        if result.success:
            merged.append(PopulationMember(params=params, score=result.score))
    merged.sort(key=lambda member: member.score, reverse=True)
    return merged[:pop_size]


def run_pbt_search(
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
    memory: Any,
) -> None:
    """Population-Based Tuning — parallel evolution around the best configs.

    Each generation evaluates up to ``concurrency`` offspring in parallel.
    Top performers become parents; underperformers are replaced by mutated
    copies of the leaders. Exploration pressure increases when progress stalls.
    """
    from app.optimization.search_runners import ConfMemory

    if not isinstance(memory, ConfMemory):
        memory = ConfMemory(base_conf)

    rng = random.Random(seed_from_job_id(job_id))
    pop_size = max(2, concurrency)
    population = _seed_population(rng, base_conf, tool, specs, pop_size)
    trials_done = 0
    mutation_strength = 0.25
    stall_generations = 0
    last_best = float("-inf")

    while not timed_out() and trials_done < max_trials:
        population.sort(key=lambda member: member.score, reverse=True)
        champion = population[0]
        batch: list[tuple[dict[str, Any], dict[str, Any]]] = []
        batch_size = min(concurrency, max_trials - trials_done)

        for slot in range(batch_size):
            if champion.score > float("-inf") and slot < max(1, pop_size // 2):
                parent = population[slot % max(1, (pop_size + 1) // 2)]
                child_params = mutate_params(
                    rng,
                    parent.params,
                    base_conf,
                    tool,
                    specs,
                    strength=mutation_strength,
                )
            elif champion.score > float("-inf") and rng.random() < 0.7:
                child_params = mutate_params(
                    rng,
                    champion.params,
                    base_conf,
                    tool,
                    specs,
                    strength=min(1.0, mutation_strength * 1.5),
                )
            else:
                child_params = suggest_random_params(rng, base_conf, tool, specs)

            conf = build_conf_from_params(base_conf, tool, child_params)
            if memory.remember(conf):
                batch.append((conf, child_params))

        if not batch:
            mutation_strength = min(1.0, mutation_strength + 0.15)
            stall_generations += 1
            if stall_generations > 3:
                logger.info("PBT exhausted unique configs")
                break
            continue

        offspring = _eval_param_batch(
            batch=batch,
            concurrency=concurrency,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
            label="pbt",
        )
        trials_done += len(offspring)
        population = _merge_population(population, offspring, pop_size)

        current_best = population[0].score
        if current_best > last_best + 1e-6:
            last_best = current_best
            stall_generations = 0
            mutation_strength = max(0.15, mutation_strength * 0.92)
        else:
            stall_generations += 1
            mutation_strength = min(1.0, mutation_strength + 0.08)


def run_cascade_search(
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
    memory: Any,
) -> None:
    """Three-stage search: space-fill → local refine → focused PBT."""
    from app.optimization.search_runners import ConfMemory

    if not isinstance(memory, ConfMemory):
        memory = ConfMemory(base_conf)

    tracker = SearchTracker()
    stage1 = max(1, int(round(max_trials * 0.35)))
    stage2 = max(1, int(round(max_trials * 0.30)))
    stage3 = max(0, max_trials - stage1 - stage2)
    trials_done = 0
    seed = seed_from_job_id(job_id)

    logger.info(
        "Cascade stages: explore=%s refine=%s exploit=%s",
        stage1,
        stage2,
        stage3,
    )

    # Stage 1 — Sobol space-filling exploration (parallel batches)
    planned = build_quasi_sample_confs(
        "sobol",
        n=stage1,
        base_conf=base_conf,
        tool=tool,
        specs=specs,
        seed=seed,
    )
    idx = 0
    while not timed_out() and trials_done < stage1 and idx < len(planned):
        batch: list[tuple[dict[str, Any], dict[str, Any]]] = []
        while (
            len(batch) < concurrency
            and idx < len(planned)
            and trials_done + len(batch) < stage1
        ):
            params = planned[idx]
            idx += 1
            conf = build_conf_from_params(base_conf, tool, params)
            if memory.remember(conf):
                batch.append((conf, params))
        if not batch:
            break
        results = _eval_param_batch(
            batch=batch,
            concurrency=concurrency,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
            label="cascade-explore",
            tracker=tracker,
        )
        trials_done += len(results)

    if timed_out() or trials_done >= max_trials:
        return

    # Stage 2 — coordinate descent around best so far
    anchor_params = tracker.best_params or extract_params_from_conf(base_conf, tool, specs)
    neighbors = generate_local_neighbors(
        anchor_params,
        base_conf,
        tool,
        specs,
        max_neighbors=stage2 * 2,
    )
    rng = random.Random(seed + 1)
    if len(neighbors) < stage2:
        extras = build_quasi_sample_confs(
            "lhs",
            n=stage2,
            base_conf=base_conf,
            tool=tool,
            specs=specs,
            seed=seed + 2,
        )
        neighbors.extend(extras)

    idx = 0
    refine_done = 0
    while not timed_out() and refine_done < stage2 and idx < len(neighbors):
        batch = []
        while (
            len(batch) < concurrency
            and idx < len(neighbors)
            and refine_done + len(batch) < stage2
        ):
            params = neighbors[idx]
            idx += 1
            conf = build_conf_from_params(base_conf, tool, params)
            if memory.remember(conf):
                batch.append((conf, params))
        if not batch:
            break
        results = _eval_param_batch(
            batch=batch,
            concurrency=concurrency,
            timed_out=timed_out,
            evaluate=evaluate,
            record_result=record_result,
            label="cascade-refine",
            tracker=tracker,
        )
        refine_done += len(results)
        trials_done += len(results)

    if timed_out() or stage3 <= 0 or trials_done >= max_trials:
        return

    # Stage 3 — focused PBT around the best config discovered so far
    focused_base = tracker.best_conf or base_conf
    remaining = min(stage3, max_trials - trials_done)
    run_pbt_search(
        job_id=f"{job_id}-cascade-exploit",
        base_conf=focused_base,
        tool=tool,
        specs=specs,
        concurrency=concurrency,
        max_trials=remaining,
        timed_out=timed_out,
        evaluate=evaluate,
        record_result=record_result,
        memory=memory,
    )
