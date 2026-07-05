"""Multi-hotkey portfolio instance paths and profile metadata."""

from __future__ import annotations

import contextvars
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
TUNING_DIR = ROOT_DIR / "tuning"
INSTANCES_ROOT = ROOT_DIR / "instances"

PORTFOLIO_IDS: Tuple[str, ...] = ("gatk", "newgatk", "oldgatk", "precision")

# Default live portfolio: triple GATK when oldgatk slot is active (see MINOS_PORTFOLIO_ACTIVE).
DEFAULT_ACTIVE_PORTFOLIO: Tuple[str, ...] = ("gatk", "newgatk", "oldgatk")

# Default variant-calling tool per portfolio slot. A slot's `.env`
# MINER_TEMPLATE always wins over this; the profile default only applies when
# the env does not pin a tool.
PORTFOLIO_PROFILES: Dict[str, Dict[str, Any]] = {
    "gatk": {
        "id": "gatk",
        "role": "primary",
        "label": "GATK sliger1",
        "tagline": "GATK HaplotypeCaller — sliger/sliger1 (primary)",
        "preset": "minos_baseline",
        "pm2_name": "minos-miner-gatk",
        "emoji": "◉",
        "tune_model": "balanced",
        "tool": "gatk",
        "champion": True,
    },
    "newgatk": {
        "id": "newgatk",
        "role": "secondary",
        "label": "GATK fencer1",
        "tagline": "GATK HaplotypeCaller — fencer/fencer1 (secondary, shared history)",
        "preset": "minos_baseline",
        "pm2_name": "minos-miner-newgatk",
        "emoji": "◎",
        "tune_model": "balanced",
        "tool": "gatk",
    },
    "oldgatk": {
        "id": "oldgatk",
        "role": "tertiary",
        "label": "GATK dagger1",
        "tagline": "GATK HaplotypeCaller — dagger/dagger1 (tertiary, shared history)",
        "preset": "minos_baseline",
        "pm2_name": "minos-miner-oldgatk",
        "emoji": "◈",
        "tune_model": "balanced",
        "tool": "gatk",
    },
    "precision": {
        "id": "precision",
        "label": "GATK fencer1",
        "tagline": "GATK precision-heavy — fencer/fencer1 (stricter filters)",
        "preset": "minos_precision_focused",
        "pm2_name": "minos-miner-precision",
        "emoji": "◇",
        "tool": "gatk",
    },
}

# Variant-calling tools the tuning layer understands.
SUPPORTED_TOOLS: Tuple[str, ...] = ("gatk", "deepvariant", "bcftools")
DEFAULT_TOOL = "gatk"

_request_instance: contextvars.ContextVar[str] = contextvars.ContextVar("minos_instance", default="")


def bind_instance(instance_id: str) -> contextvars.Token[str]:
    return _request_instance.set(instance_id)


def reset_instance(token: contextvars.Token[str]) -> None:
    _request_instance.reset(token)


def current_instance_id() -> str:
    ctx = _request_instance.get()
    if ctx:
        return ctx
    iid = os.getenv("MINOS_INSTANCE", "").strip()
    return iid or "default"


def is_portfolio_mode() -> bool:
    if os.getenv("MINOS_PORTFOLIO", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return bool(list_portfolio_instances())


def instance_root(instance_id: Optional[str] = None) -> Path:
    iid = instance_id or current_instance_id()
    if iid == "default":
        return ROOT_DIR
    return INSTANCES_ROOT / iid


def configs_dir(instance_id: Optional[str] = None) -> Path:
    return instance_root(instance_id) / "configs"


def gatk_conf_path(instance_id: Optional[str] = None) -> Path:
    return configs_dir(instance_id) / "gatk.conf"


def instance_tool(instance_id: Optional[str] = None) -> str:
    """Variant-calling tool for an instance.

    Resolution order (most authoritative first):
      1. ``.env`` MINER_TEMPLATE
      2. on-disk config — exactly one ``<tool>.conf`` present is unambiguous
      3. profile default
      4. ``gatk``
    """
    iid = instance_id or current_instance_id()
    env_tool = (merged_env(iid).get("MINER_TEMPLATE") or "").strip().lower()
    if env_tool in SUPPORTED_TOOLS:
        return env_tool
    if env_tool:
        # Unknown / deprecated template (e.g. freebayes) — fall back to default.
        return DEFAULT_TOOL

    cfg_dir = configs_dir(iid)
    present = [t for t in SUPPORTED_TOOLS if (cfg_dir / f"{t}.conf").is_file()]
    if len(present) == 1:
        return present[0]

    profile_tool = (PORTFOLIO_PROFILES.get(iid, {}).get("tool") or "").strip().lower()
    if profile_tool in SUPPORTED_TOOLS:
        return profile_tool
    return DEFAULT_TOOL


def tool_conf_path(instance_id: Optional[str] = None, tool: Optional[str] = None) -> Path:
    """Path to the active tool's <tool>.conf for an instance."""
    iid = instance_id or current_instance_id()
    resolved = (tool or instance_tool(iid)).strip().lower()
    return configs_dir(iid) / f"{resolved}.conf"


def portfolio_tools() -> List[str]:
    """Distinct tools across active portfolio instances (order-preserving)."""
    seen: List[str] = []
    for iid in discover_instances():
        t = instance_tool(iid)
        if t not in seen:
            seen.append(t)
    return seen


def is_multi_tool_portfolio() -> bool:
    """True when active hotkeys run more than one distinct tool (divergence is then moot)."""
    return len(portfolio_tools()) > 1


def unified_gatk_portfolio() -> bool:
    """True when every active portfolio hotkey runs GATK (shared history, same tune path)."""
    instances = list_portfolio_instances()
    if not instances:
        return False
    return all(instance_tool(iid) == "gatk" for iid in instances)


def uses_unified_gatk_tuning(instance_id: Optional[str] = None) -> bool:
    """GATK hotkey on the unified solo path (not co-champion / rival split)."""
    iid = instance_id or current_instance_id()
    if instance_tool(iid) != "gatk":
        return False
    if unified_gatk_portfolio():
        return True
    return is_multi_tool_portfolio()


def data_dir(instance_id: Optional[str] = None) -> Path:
    iid = instance_id or current_instance_id()
    if iid == "default":
        return TUNING_DIR / "data"
    return instance_root(iid) / "tuning" / "data"


def backup_dir(instance_id: Optional[str] = None) -> Path:
    iid = instance_id or current_instance_id()
    if iid == "default":
        return TUNING_DIR / "backups"
    return instance_root(iid) / "tuning" / "backups"


def output_dir(instance_id: Optional[str] = None) -> Path:
    override = os.getenv("MINOS_OUTPUT_DIR", "").strip()
    if override and instance_id is None:
        return Path(override)
    iid = instance_id or current_instance_id()
    if iid == "default":
        return ROOT_DIR / "output"
    return instance_root(iid) / "output"


def overnight_state_path(instance_id: Optional[str] = None) -> Path:
    return data_dir(instance_id) / "overnight_autotune_state.json"


def overnight_log_path(instance_id: Optional[str] = None) -> Path:
    return data_dir(instance_id) / "overnight_autotune.log"


def history_path(instance_id: Optional[str] = None) -> Path:
    return data_dir(instance_id) / "round_history.json"


def submit_control_path(instance_id: Optional[str] = None) -> Path:
    return data_dir(instance_id) / "submit_control.json"


def instance_env_path(instance_id: Optional[str] = None) -> Path:
    iid = instance_id or current_instance_id()
    if iid == "default":
        return ROOT_DIR / ".env"
    return instance_root(iid) / ".env"


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(raw)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        out[key] = value
    return out


def merged_env(instance_id: Optional[str] = None) -> Dict[str, str]:
    """Root .env layered with instance .env (instance wins)."""
    merged = parse_env_file(ROOT_DIR / ".env")
    iid = instance_id or current_instance_id()
    if iid != "default":
        merged.update(parse_env_file(instance_env_path(iid)))
    return merged


def wallet_credentials(instance_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    env = merged_env(instance_id)
    name = env.get("WALLET_NAME", "").strip() or None
    hotkey = env.get("WALLET_HOTKEY", "").strip() or None
    return name, hotkey


def active_portfolio_ids() -> Tuple[str, ...]:
    """Which instance slots are live (from MINOS_PORTFOLIO_ACTIVE or default dual)."""
    raw = os.getenv("MINOS_PORTFOLIO_ACTIVE", "").strip()
    if not raw:
        return DEFAULT_ACTIVE_PORTFOLIO
    ids = tuple(x.strip() for x in raw.split(",") if x.strip())
    return ids or DEFAULT_ACTIVE_PORTFOLIO


def list_portfolio_instances() -> List[str]:
    """Active portfolio instances that are fully initialized on disk.

    A slot is "ready" when it has an ``.env`` and the config file for its tool
    (``gatk.conf`` for a GATK slot, ``bcftools.conf`` for a BCFtools slot).
    """
    found: List[str] = []
    for pid in active_portfolio_ids():
        if pid not in PORTFOLIO_PROFILES:
            continue
        if not instance_env_path(pid).is_file():
            continue
        if tool_conf_path(pid).is_file() or gatk_conf_path(pid).is_file():
            found.append(pid)
    return found


def discover_instances() -> List[str]:
    portfolio = list_portfolio_instances()
    if portfolio:
        return portfolio
    return ["default"]


def resolve_default_instance() -> str:
    explicit = os.getenv("MINOS_DEFAULT_INSTANCE", "").strip()
    if explicit:
        return explicit
    portfolio = list_portfolio_instances()
    # Default the UI to the GATK champion (the primary registered earner).
    for pid in portfolio:
        if instance_tool(pid) == "gatk":
            return pid
    if portfolio:
        return portfolio[0]
    return "default"


def configure_process_instance() -> None:
    """Call once at miner/UI process start after dotenv."""
    iid = current_instance_id()
    if iid == "default":
        return
    os.environ.setdefault("MINOS_CONFIG_DIR", str(configs_dir(iid)))
    os.environ.setdefault("MINOS_OUTPUT_DIR", str(output_dir(iid)))


def ensure_instance_layout(instance_id: str) -> None:
    """Create instance directory tree."""
    configs_dir(instance_id).mkdir(parents=True, exist_ok=True)
    data_dir(instance_id).mkdir(parents=True, exist_ok=True)
    backup_dir(instance_id).mkdir(parents=True, exist_ok=True)
    output_dir(instance_id).mkdir(parents=True, exist_ok=True)
