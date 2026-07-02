from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.repo import ensure_repo_imports


@dataclass(frozen=True)
class TuneSpec:
    name: str
    min: float | int | None = None
    max: float | int | None = None
    step: float | int | None = None
    values: tuple[Any, ...] | None = None
    linear: bool = False
    value_type: str | None = None


# Phase-1 search grids from docs/config-optimization-plan.md
GATK_SEARCH_STEPS: dict[str, float | int] = {
    "standard_min_confidence_threshold_for_calling": 2.5,
    "min_base_quality_score": 2,
    "min_mapping_quality_score": 5,
}

GATK_ENUM_SUBSETS: dict[str, list[Any]] = {
    "pcr_indel_model": ["NONE", "CONSERVATIVE"],
}


def _tool_param_definitions(tool: str) -> dict[str, dict[str, Any]]:
    ensure_repo_imports()
    from templates.tool_params import (
        BCFTOOLS_QUALITY_PARAMS,
        DEEPVARIANT_QUALITY_PARAMS,
        GATK_QUALITY_PARAMS,
    )

    tool_key = tool.lower().strip()
    mapping = {
        "gatk": GATK_QUALITY_PARAMS,
        "deepvariant": DEEPVARIANT_QUALITY_PARAMS,
        "bcftools": BCFTOOLS_QUALITY_PARAMS,
    }
    if tool_key not in mapping:
        raise ValueError(f"Unsupported tool for param search: {tool}")
    return mapping[tool_key]


def coerce_param_value(tool: str, param_name: str, value: Any) -> Any:
    """Cast grid/random values to the tool param type (e.g. int not 8.0)."""
    try:
        definitions = _tool_param_definitions(tool)
    except ValueError:
        return value
    param_def = definitions.get(param_name)
    if not param_def:
        return value
    param_type = param_def["type"]
    if param_type == "int":
        if isinstance(value, bool):
            return value
        return int(round(float(value)))
    if param_type == "float":
        return float(value)
    return value


def _default_step(param_def: dict[str, Any]) -> float | int:
    if param_def["type"] == "int":
        span = int(param_def["max"]) - int(param_def["min"])
        return max(1, span // 4)
    span = float(param_def["max"]) - float(param_def["min"])
    return max(0.1, round(span / 4.0, 3))


def resolve_tune_specs(
    tool: str,
    param_names: list[str],
    param_intervals: dict[str, Any] | None = None,
) -> list[TuneSpec]:
    if not param_names:
        raise ValueError("params must list at least one conf parameter name")

    definitions = _tool_param_definitions(tool)
    specs: list[TuneSpec] = []
    intervals = param_intervals or {}

    for raw_name in param_names:
        name = raw_name.strip()
        if not name:
            raise ValueError("params entries must be non-empty strings")
        if name not in definitions:
            raise ValueError(f"Unknown {tool} parameter: {name}")

        param_def = definitions[name]
        param_type = param_def["type"]
        override = intervals.get(name) or {}

        if param_type == "enum":
            if override.get("values"):
                values = [str(v) for v in override["values"]]
            else:
                subset = GATK_ENUM_SUBSETS.get(name) if tool.lower() == "gatk" else None
                values = subset or list(param_def["allowed_values"])
            specs.append(TuneSpec(name=name, values=tuple(values)))
        elif param_type == "bool":
            if override.get("values"):
                bool_values: list[bool] = []
                for raw in override["values"]:
                    text = str(raw).strip().lower()
                    if text in ("true", "1", "yes"):
                        bool_values.append(True)
                    elif text in ("false", "0", "no"):
                        bool_values.append(False)
                if not bool_values:
                    bool_values = [False, True]
            else:
                bool_values = [False, True]
            specs.append(TuneSpec(name=name, values=tuple(bool_values)))
        elif param_type in ("int", "float"):
            step = override.get("step")
            if step is None:
                step = GATK_SEARCH_STEPS.get(name, _default_step(param_def))
            low = override.get("min", param_def["min"])
            high = override.get("max", param_def["max"])
            specs.append(
                TuneSpec(
                    name=name,
                    min=low,
                    max=high,
                    step=step,
                    linear=any(k in override for k in ("min", "max", "step")),
                    value_type=param_type,
                )
            )
        else:
            raise ValueError(f"Parameter '{name}' type '{param_type}' is not searchable")

    return specs
