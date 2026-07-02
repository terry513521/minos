from copy import deepcopy
from itertools import product
from typing import Any

from app.optimization.algorithms import is_adaptive_algorithm, normalize_algorithm
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
    concurrency: int = 1,
    param_split: bool = True,
    algorithm: str = "grid",
    adaptive_max_trials: int = 30,
) -> int:
    """Trials to run: 1 base + search variants (grid, param-split, or adaptive cap)."""
    algo = normalize_algorithm(algorithm)
    if is_adaptive_algorithm(algo):
        return 1 + max(1, adaptive_max_trials)

    if param_split and concurrency > 1 and len(param_names) > 1:
        total = 1
        for group in split_params_for_lanes(param_names, concurrency):
            total += max(0, len(build_search_space(base_conf, tool, group, param_intervals)) - 1)
        return total

    return len(build_search_space(base_conf, tool, param_names, param_intervals))


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
    param_split: bool,
    limit_seconds: int,
    algorithm: str,
    adaptive_max_trials: int = 30,
    vcf_cache_enabled: bool = False,
    gatk_persistent_container: bool = False,
    source_window: str | None = None,
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
        concurrency=concurrency,
        param_split=param_split,
        algorithm=algo,
        adaptive_max_trials=adaptive_max_trials,
    )

    if is_adaptive_algorithm(algo):
        mode = algo
    elif param_split and concurrency > 1 and len(params) > 1:
        mode = "param_split"
    else:
        mode = "full_grid"

    plan: dict[str, Any] = {
        "window": window,
        "source_window": source_window,
        "tool": tool,
        "algorithm": algo,
        "mode": mode,
        "concurrency": concurrency,
        "limit_seconds": limit_seconds,
        "params": list(params),
        "param_count": len(params),
        "full_cartesian_grid": full_cartesian,
        "planned_trials": planned_trials,
        "adaptive_max_trials": adaptive_max_trials if is_adaptive_algorithm(algo) else None,
        "vcf_cache_enabled": vcf_cache_enabled,
        "gatk_persistent_container": gatk_persistent_container and tool.lower() == "gatk",
        "trial_threads": trial_threads,
        "trial_memory_gb": trial_memory_gb,
        "axes": summarize_param_axes(base_conf, tool, params, param_intervals),
        "lanes": [],
    }

    if mode == "param_split":
        for index, lane_params in enumerate(split_params_for_lanes(params, concurrency), start=1):
            lane_intervals = filter_param_intervals(param_intervals, lane_params)
            lane_variants = len(build_search_space(base_conf, tool, lane_params, lane_intervals))
            lane_axes = summarize_param_axes(base_conf, tool, lane_params, lane_intervals)
            lane_product = 1
            for axis in lane_axes:
                lane_product *= max(1, int(axis["value_count"]))
            plan["lanes"].append(
                {
                    "lane": index,
                    "params": lane_params,
                    "param_pairs": max(0, len(lane_params) - 1),
                    "variant_count": lane_variants,
                    "grid_product": lane_product,
                    "axes": lane_axes,
                }
            )
    else:
        plan["grid_product"] = full_cartesian
        plan["parallel_workers"] = concurrency

    return plan


def format_optimization_plan(plan: dict[str, Any]) -> str:
    """Human-readable multi-line summary for worker logs."""
    lines = [
        "=== Optimization plan ===",
        f"window: {plan['window']}",
    ]
    if plan.get("source_window"):
        lines.append(f"round window: {plan['source_window']} (benchmark uses random slice)")
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

    if plan["mode"] == "param_split":
        lines.append(f"lanes: {len(plan['lanes'])} (different param groups per parallel lane)")
        for lane in plan["lanes"]:
            params_label = " + ".join(lane["params"])
            pairs = lane["param_pairs"]
            pair_note = f", {pairs} param pair(s) in lane" if pairs else ""
            lines.append(
                f"  lane {lane['lane']}: [{params_label}] -> "
                f"{lane['grid_product']} grid{pair_note}, {lane['variant_count']} configs"
            )
    elif plan["mode"] in ("random", "optuna"):
        lines.append(
            f"search: {plan['mode']} up to {plan['adaptive_max_trials']} trials after base "
            f"(full grid reference: {plan['full_cartesian_grid']} configs)"
        )
    else:
        workers = plan.get("parallel_workers", 1)
        lines.append(
            f"search: full grid {plan.get('grid_product', plan['full_cartesian_grid'])} configs, "
            f"up to {workers} trials in parallel"
        )

    extras: list[str] = []
    if plan.get("vcf_cache_enabled"):
        extras.append("VCF cache on")
    if plan.get("gatk_persistent_container"):
        extras.append("persistent GATK containers")
    if extras:
        lines.append("accelerators: " + ", ".join(extras))

    return "\n".join(lines)
