from copy import deepcopy
from itertools import product
from typing import Any

from app.optimization.algorithms import normalize_algorithm
from app.optimization.param_specs import TuneSpec


def _tool_options_key(tool: str) -> str:
    return f"{tool.lower().strip()}_options"


def _read_param_value(base_conf: dict[str, Any], tool: str, name: str) -> Any:
    options = base_conf.get(_tool_options_key(tool), {})
    if not isinstance(options, dict):
        return None
    return options.get(name)


def _write_param_value(conf: dict[str, Any], tool: str, name: str, value: Any) -> None:
    from app.optimization.param_specs import coerce_param_value

    key = _tool_options_key(tool)
    options = conf.setdefault(key, {})
    if not isinstance(options, dict):
        options = {}
        conf[key] = options
    options[name] = coerce_param_value(tool, name, value)


def _normalize_numeric_value(spec: TuneSpec, value: Any) -> Any:
    if spec.value_type == "int":
        return int(round(float(value)))
    if spec.value_type == "float":
        return float(value)
    return value


def _numeric_candidates(base_value: Any, spec: TuneSpec) -> list[Any]:
    assert spec.min is not None and spec.max is not None and spec.step is not None

    if spec.linear:
        if spec.value_type == "int":
            step = max(1, int(round(float(spec.step))))
            low = int(round(float(spec.min)))
            high = int(round(float(spec.max)))
            values: set[int] = set()
            v = low
            while v <= high:
                values.add(v)
                v += step
            if not values:
                values.add(low)
            return sorted(values)

        if isinstance(spec.min, int) and isinstance(spec.max, int) and isinstance(spec.step, int):
            step = int(spec.step)
            low = int(spec.min)
            high = int(spec.max)
            values = set()
            v = low
            while v <= high:
                values.add(v)
                v += step
            if not values:
                values.add(low)
            return sorted(values)

        step = float(spec.step)
        low = float(spec.min)
        high = float(spec.max)
        values_f: set[float] = set()
        v = low
        while v <= high + step * 0.001:
            values_f.add(round(v, 6))
            v += step
        if not values_f:
            values_f.add(low)
        return sorted(_normalize_numeric_value(spec, v) for v in values_f)

    if spec.value_type == "int" or (
        isinstance(base_value, int) and not isinstance(base_value, bool)
    ):
        step = max(1, int(round(float(spec.step))))
        low = int(round(float(spec.min)))
        high = int(round(float(spec.max)))
        start = int(round(float(base_value))) if isinstance(base_value, (int, float)) else low
        center = max(low, min(high, start))
        values: set[int] = set()
        v = center
        while v >= low:
            values.add(v)
            v -= step
        v = center + step
        while v <= high:
            values.add(v)
            v += step
        if not values:
            values.add(low)
        return sorted(values)

    step = float(spec.step)
    low = float(spec.min)
    high = float(spec.max)
    start = float(base_value) if isinstance(base_value, (int, float)) else (low + high) / 2
    center = max(low, min(high, start))
    values_f: set[float] = set()
    v = center
    while v >= low - step * 0.001:
        values_f.add(round(v, 6))
        v -= step
    v = center + step
    while v <= high + step * 0.001:
        values_f.add(round(v, 6))
        v += step
    if not values_f:
        values_f.add(low)
    return sorted(_normalize_numeric_value(spec, v) for v in values_f)


def _values_for_param(base_conf: dict[str, Any], tool: str, spec: TuneSpec) -> list[Any]:
    if spec.values is not None:
        return list(spec.values)

    base_value = _read_param_value(base_conf, tool, spec.name)
    return _numeric_candidates(base_value, spec)


def build_search_space(
    base_conf: dict[str, Any],
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand base_conf by varying each listed conf parameter name."""
    from app.optimization.param_specs import resolve_tune_specs

    specs = resolve_tune_specs(tool, param_names, param_intervals)
    if not specs:
        return [deepcopy(base_conf)]

    axes: list[list[tuple[str, Any]]] = []
    for spec in specs:
        values = _values_for_param(base_conf, tool, spec)
        axes.append([(spec.name, value) for value in values])

    variants: list[dict[str, Any]] = []
    for combo in product(*axes):
        conf = deepcopy(base_conf)
        for name, value in combo:
            _write_param_value(conf, tool, name, value)
        variants.append(conf)

    return variants


def split_params_for_lanes(param_names: list[str], concurrency: int) -> list[list[str]]:
    """Round-robin split of tune params across parallel lanes."""
    if concurrency <= 1 or len(param_names) <= 1:
        return [list(param_names)]
    lane_count = min(concurrency, len(param_names))
    groups: list[list[str]] = [[] for _ in range(lane_count)]
    for index, name in enumerate(param_names):
        groups[index % lane_count].append(name)
    return [group for group in groups if group]


def filter_param_intervals(
    param_intervals: dict[str, Any] | None,
    param_names: list[str],
) -> dict[str, Any] | None:
    if not param_intervals:
        return None
    allowed = set(param_names)
    filtered = {name: spec for name, spec in param_intervals.items() if name in allowed}
    return filtered or None


def count_search_trials(
    base_conf: dict[str, Any],
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None,
    *,
    algorithm: str = "optuna",
    adaptive_max_trials: int = 44,
) -> int:
    """Trials to run: 1 base + search trials (algorithm-specific cap)."""
    algo = normalize_algorithm(algorithm)
    if algo == "grid":
        grid_size = full_grid_size(base_conf, tool, param_names, param_intervals)
        searchable = max(0, grid_size - 1)
        if searchable == 0:
            return 1
        return 1 + min(searchable, max(1, adaptive_max_trials))
    return 1 + max(1, adaptive_max_trials)


def summarize_param_axes(
    base_conf: dict[str, Any],
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Per-parameter value counts and preview for logging / UI."""
    from app.optimization.param_specs import resolve_tune_specs

    if not param_names:
        return []

    lane_intervals = filter_param_intervals(param_intervals, param_names)
    specs = resolve_tune_specs(tool, param_names, lane_intervals)
    axes: list[dict[str, Any]] = []
    for spec in specs:
        values = _values_for_param(base_conf, tool, spec)
        preview = values[:6]
        axes.append(
            {
                "param": spec.name,
                "value_count": len(values),
                "values_preview": preview,
                "values_truncated": len(values) > len(preview),
            }
        )
    return axes


def full_grid_size(
    base_conf: dict[str, Any],
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None,
) -> int:
    if not param_names:
        return 1
    axes = summarize_param_axes(base_conf, tool, param_names, param_intervals)
    size = 1
    for axis in axes:
        size *= max(1, int(axis["value_count"]))
    return size


def build_optimization_plan(
    *,
    window: str,
    tool: str,
    params: list[str],
    param_intervals: dict[str, Any] | None,
    base_conf: dict[str, Any],
    concurrency: int,
    limit_seconds: int,
    algorithm: str,
    adaptive_max_trials: int = 44,
    vcf_cache_enabled: bool = False,
    gatk_persistent_container: bool = False,
    benchmark_window: str | None = None,
    trial_threads: int | None = None,
    trial_memory_gb: int | None = None,
) -> dict[str, Any]:
    """Structured search plan for logs and GET /best message."""
    algo = normalize_algorithm(algorithm)
    full_cartesian = full_grid_size(base_conf, tool, params, param_intervals)
    planned_trials = count_search_trials(
        base_conf,
        tool,
        params,
        param_intervals,
        algorithm=algo,
        adaptive_max_trials=adaptive_max_trials,
    )

    plan: dict[str, Any] = {
        "window": window,
        "benchmark_window": benchmark_window,
        "tool": tool,
        "algorithm": algo,
        "mode": algo,
        "concurrency": concurrency,
        "limit_seconds": limit_seconds,
        "params": list(params),
        "param_count": len(params),
        "full_cartesian_grid": full_cartesian,
        "planned_trials": planned_trials,
        "adaptive_max_trials": adaptive_max_trials,
        "vcf_cache_enabled": vcf_cache_enabled,
        "gatk_persistent_container": gatk_persistent_container and tool.lower() == "gatk",
        "trial_threads": trial_threads,
        "trial_memory_gb": trial_memory_gb,
        "axes": summarize_param_axes(base_conf, tool, params, param_intervals),
    }

    return plan


def format_optimization_plan(plan: dict[str, Any]) -> str:
    """Human-readable multi-line summary for worker logs."""
    lines = [
        "=== Optimization plan ===",
        f"assigned window: {plan['window']}",
    ]
    benchmark_window = plan.get("benchmark_window")
    if benchmark_window and benchmark_window != plan["window"]:
        lines.append(f"benchmark slice: {benchmark_window} (random sub-window for speed)")
    lines.extend([
        f"tool: {plan['tool']}  algorithm: {plan['algorithm']}  limit: {plan['limit_seconds']}s",
        f"mode: {plan['mode']}  concurrency: {plan['concurrency']}",
    ])
    if plan.get("trial_threads") and plan.get("trial_memory_gb"):
        lines.append(
            f"per slot: {plan['trial_threads']} CPUs, {plan['trial_memory_gb']} GB RAM"
        )
    lines.extend([
        f"params ({plan['param_count']}): {', '.join(plan['params']) or '(none)'}",
        f"full Cartesian grid: {plan['full_cartesian_grid']} configs",
        f"planned trials: {plan['planned_trials']} (includes 1 base benchmark)",
    ])

    for axis in plan.get("axes", []):
        preview = ", ".join(str(v) for v in axis["values_preview"])
        suffix = ", ..." if axis["values_truncated"] else ""
        lines.append(
            f"  - {axis['param']}: {axis['value_count']} values [{preview}{suffix}]"
        )

    if plan["mode"] == "grid":
        searchable = max(0, int(plan["full_cartesian_grid"]) - 1)
        capped = min(searchable, int(plan["adaptive_max_trials"]))
        lines.append(
            f"search: grid {capped} of {plan['full_cartesian_grid']} configs after base "
            f"(cap {plan['adaptive_max_trials']} search trials)"
        )
    elif plan["mode"] in ("random", "optuna", "gp", "sobol", "lhs", "pbt", "cascade"):
        lines.append(
            f"search: {plan['mode']} up to {plan['adaptive_max_trials']} trials after base "
            f"(reference space: {plan['full_cartesian_grid']} configs)"
        )
    else:
        lines.append(
            f"search: {plan['mode']} up to {plan['adaptive_max_trials']} trials after base"
        )

    extras: list[str] = []
    if plan.get("vcf_cache_enabled"):
        extras.append("VCF cache on")
    if plan.get("gatk_persistent_container"):
        extras.append("persistent GATK containers")
    if extras:
        lines.append("accelerators: " + ", ".join(extras))

    return "\n".join(lines)
