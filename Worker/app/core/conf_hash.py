from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

_RUNTIME_KEYS = frozenset({"threads", "memory_gb", "timeout", "persistent_container", "_gatk_persistent_runner"})


def conf_for_cache(conf: dict[str, Any]) -> dict[str, Any]:
    """Strip worker-only runtime keys before hashing or comparing configs."""
    cleaned = deepcopy(conf)
    for key in _RUNTIME_KEYS:
        cleaned.pop(key, None)
    return cleaned


def conf_fingerprint(*, window: str, tool: str, conf: dict[str, Any], length: int = 16) -> str:
    """Short stable id for GIAB VCF reuse."""
    payload = {
        "window": window.strip(),
        "tool": tool.lower().strip(),
        "conf": conf_for_cache(conf),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return digest[:length]
