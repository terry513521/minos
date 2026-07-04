"""Coordinate refinement: perturb each param by ±delta around the current best."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.benchmark import BenchmarkResult
from app.optimization.adaptive_search import build_conf_from_params
from app.optimization.evolutionary_search import (
    SearchTracker,
    _eval_param_batch,
    _index_on_axis,
    extract_params_from_conf,
)
from app.optimization.param_specs import TuneSpec, coerce_param_value
from app.optimization.search import _read_param_value
from app.optimization.search_runners import ConfMemory

logger = logging.getLogger(__name__)

DEFAULT_DELTA_ROUNDS = 5


def resolve_delta_rounds(raw: int | None, *, max_trials: int, param_count: int) -> int:
    if raw is not None and raw >= 1:
        return int(raw)
    per_round = max(1, param_count * 2)
    return max(1, min(DEFAULT_DELTA_ROUNDS, max_trials // per_round or DEFAULT_DELTA_ROUNDS))


def _delta_for_spec(spec: TuneSpec, override: dict[str, Any] | None) -> float | int | None:
    if override and override.get("delta") is not None:
        return override["delta"]
    if spec.delta is not None:
        return spec.delta
    if spec.step is not None:
        return spec.step
    return None


def _clamp_numeric(
    value: float | int,
    spec: TuneSpec,
    tool: str,
    param_name: str,
) -> Any:
    low = spec.min
    high = spec.max
    if low is not None and value < float(low):
        value = float(low)
    if high is not None and value > float(high):
        value = float(high)
    return coerce_param_value(tool, param_name, value)


def generate_delta_neighbors(
    params: dict[str, Any],
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    param_intervals: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Single-parameter ±delta moves around a promising config."""
    intervals = param_intervals or {}
    neighbors: list[dict[str, Any]] = []
    seen: set[str] = set()

    for spec in specs:
        override = intervals.get(spec.name) or {}
        delta = _delta_for_spec(spec, override)
        current = params.get(spec.name)
        if current is None:
            current = _read_param_value(base_conf, tool, spec.name)
        if current is None:
            continue

        if spec.values is not None:
            values = list(spec.values)
            if len(values) <= 1:
                continue
            idx = _index_on_axis(values, current)
            for step in (-1, 1):
                new_idx = idx + step
                if 0 <= new_idx < len(values):
                    candidate = dict(params)
                    candidate[spec.name] = values[new_idx]
                    key = str(sorted(candidate.items()))
                    if key not in seen:
                        seen.add(key)
                        neighbors.append(candidate)
            continue

        if delta is None:
            continue

        try:
            center = float(current)
            step = float(delta)
        except (TypeError, ValueError):
            continue
        if step <= 0:
            continue

        for sign in (-1, 1):
            raw = center + sign * step
            new_val = _clamp_numeric(raw, spec, tool, spec.name)
            if new_val == current:
                continue
            candidate = dict(params)
            candidate[spec.name] = new_val
            key = str(sorted(candidate.items()))
            if key not in seen:
                seen.add(key)
                neighbors.append(candidate)

    return neighbors


def run_delta_search(
    *,
    base_conf: dict[str, Any],
    anchor_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    param_intervals: dict[str, Any] | None,
    concurrency: int,
    max_trials: int,
    delta_rounds: int,
    timed_out: Callable[[], bool],
    evaluate: Callable[[dict[str, Any]], BenchmarkResult],
    record_result: Callable[[BenchmarkResult, str], None],
    memory: ConfMemory,
) -> None:
    """Refine around the best conf: each round tries ±delta on every tuned param."""
    tracker = SearchTracker()
    anchor_params = extract_params_from_conf(anchor_conf, tool, specs)
    if anchor_params:
        tracker.best_params = dict(anchor_params)

    trials_done = 0
    rounds = resolve_delta_rounds(delta_rounds, max_trials=max_trials, param_count=len(specs))

    for round_idx in range(rounds):
        if timed_out() or trials_done >= max_trials:
            break

        center_params = tracker.best_params or extract_params_from_conf(anchor_conf, tool, specs)
        if not center_params:
            center_params = extract_params_from_conf(base_conf, tool, specs)
        if not center_params:
            logger.info("Delta search has no anchor parameters")
            break

        neighbor_sets = generate_delta_neighbors(
            center_params,
            base_conf,
            tool,
            specs,
            param_intervals,
        )
        if not neighbor_sets:
            logger.info("Delta round %s produced no neighbors", round_idx + 1)
            break

        round_improved = False
        idx = 0
        while not timed_out() and trials_done < max_trials and idx < len(neighbor_sets):
            batch: list[tuple[dict[str, Any], dict[str, Any]]] = []
            while (
                len(batch) < concurrency
                and idx < len(neighbor_sets)
                and trials_done + len(batch) < max_trials
            ):
                params = neighbor_sets[idx]
                idx += 1
                conf = build_conf_from_params(base_conf, tool, params)
                if memory.remember(conf):
                    batch.append((conf, params))
            if not batch:
                break

            before_score = tracker.best_score
            results = _eval_param_batch(
                batch=batch,
                concurrency=concurrency,
                timed_out=timed_out,
                evaluate=evaluate,
                record_result=record_result,
                label=f"delta-r{round_idx + 1}",
                tracker=tracker,
            )
            trials_done += len(results)
            if tracker.best_score > before_score:
                round_improved = True

        if not round_improved and round_idx > 0:
            logger.info("Delta search stopped after round %s (no improvement)", round_idx + 1)
            break
