from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.core.conf_hash import conf_for_cache

_RUNTIME_KEYS = frozenset({"threads", "memory_gb", "timeout", "persistent_container", "_gatk_persistent_runner"})


def _conf_key(conf: dict[str, Any]) -> str:
    return json.dumps(conf, sort_keys=True, default=str)


def tool_params_from_conf(conf: dict[str, Any], tool: str) -> dict[str, Any]:
    """
    Extract flat tool params for GIAB score_tool_on_region.

    Worker/Main use {"gatk_options": {...}}; GIAB expects the inner dict.
    """
    tool_key = tool.lower().strip()
    options_key = f"{tool_key}_options"
    inner = conf.get(options_key)
    if isinstance(inner, dict) and inner:
        return deepcopy(inner)

    if tool_key == "gatk":
        flat = {
            k: v
            for k, v in conf.items()
            if k not in _RUNTIME_KEYS and not k.endswith("_options")
        }
        if flat:
            return flat
    return deepcopy(conf_for_cache(conf))


def conf_equals(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _conf_key(a) == _conf_key(b)
