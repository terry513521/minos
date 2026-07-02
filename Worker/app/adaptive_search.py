from __future__ import annotations

import random
from copy import deepcopy
from typing import Any, Callable

from app.param_specs import TuneSpec, resolve_tune_specs
from app.search import _values_for_param, _write_param_value


def build_conf_from_params(
    base_conf: dict[str, Any],
    tool: str,
    param_values: dict[str, Any],
) -> dict[str, Any]:
    conf = deepcopy(base_conf)
    for name, value in param_values.items():
        _write_param_value(conf, tool, name, value)
    return conf


def suggest_random_params(
    rng: random.Random,
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
) -> dict[str, Any]:
    param_values: dict[str, Any] = {}
    for spec in specs:
        values = _values_for_param(base_conf, tool, spec)
        param_values[spec.name] = rng.choice(values)
    return param_values


def suggest_optuna_params(trial: Any, base_conf: dict[str, Any], tool: str, specs: list[TuneSpec]) -> dict[str, Any]:
    param_values: dict[str, Any] = {}
    for spec in specs:
        values = _values_for_param(base_conf, tool, spec)
        if spec.values is not None or len(values) <= 32:
            param_values[spec.name] = trial.suggest_categorical(spec.name, list(values))
        elif spec.value_type == "int":
            param_values[spec.name] = trial.suggest_int(
                spec.name,
                int(round(float(spec.min))),
                int(round(float(spec.max))),
                step=max(1, int(round(float(spec.step or 1)))),
            )
        elif isinstance(spec.min, int) and isinstance(spec.max, int) and isinstance(spec.step, int):
            param_values[spec.name] = trial.suggest_int(
                spec.name,
                int(spec.min),
                int(spec.max),
                step=int(spec.step),
            )
        else:
            step = float(spec.step) if spec.step is not None else None
            param_values[spec.name] = trial.suggest_float(
                spec.name,
                float(spec.min),
                float(spec.max),
                step=step,
            )
    return param_values


def resolve_search_specs(
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None,
) -> list[TuneSpec]:
    return resolve_tune_specs(tool, param_names, param_intervals)


def make_random_conf_sampler(
    base_conf: dict[str, Any],
    tool: str,
    specs: list[TuneSpec],
    *,
    seed: int | None = None,
) -> Callable[[], dict[str, Any]]:
    rng = random.Random(seed)

    def sample() -> dict[str, Any]:
        params = suggest_random_params(rng, base_conf, tool, specs)
        return build_conf_from_params(base_conf, tool, params)

    return sample


def create_optuna_study():
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    return optuna.create_study(direction="maximize")
