"""Read, write, validate, and backup configs/gatk.conf."""

from __future__ import annotations

import importlib.util
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from templates.tool_params import validate_and_build_flags

from tuning.instance import backup_dir as instance_backup_dir, gatk_conf_path

import os

TUNING_DIR = Path(__file__).parent
ROOT_DIR = TUNING_DIR.parent
GATK_CONF_PATH = ROOT_DIR / "configs" / "gatk.conf"  # legacy default-instance path
BACKUP_RETENTION = int(os.getenv("GATK_BACKUP_RETENTION", "12"))


def _gatk_path(path: Optional[Path] = None) -> Path:
    return path or gatk_conf_path()


def _backup_dir() -> Path:
    return instance_backup_dir()


def _load_config_loader_module():
    """Load config_loader without importing utils package (__init__ pulls boto3)."""
    path = ROOT_DIR / "utils" / "config_loader.py"
    spec = importlib.util.spec_from_file_location("minos_config_loader", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config_loader from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONFIG_LOADER = _load_config_loader_module()
extract_tool_options = _CONFIG_LOADER.extract_tool_options


def load_gatk_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load current GATK quality parameters from the active instance gatk.conf."""
    if path is not None:
        return _load_from_path(path)
    return _load_from_path(_gatk_path())


def _load_from_path(path: Path) -> Dict[str, Any]:
    """Load key=value pairs from an arbitrary .conf path."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    try:
        return parse_config_text(text)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def parse_config_text(text: str) -> Dict[str, Any]:
    """Parse key=value lines from .conf file contents."""
    options: Dict[str, Any] = {}
    for line_num, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ValueError(f"line {line_num}: missing '='")
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if value.lower() == "true":
            options[key] = True
        elif value.lower() == "false":
            options[key] = False
        else:
            try:
                options[key] = int(value)
            except ValueError:
                try:
                    options[key] = float(value)
                except ValueError:
                    options[key] = value
    return options


def validate_config(params: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate params against GATK whitelist and ranges."""
    result = validate_and_build_flags("gatk", coerce_gatk_param_types(params))
    return result["valid"], list(result.get("errors") or [])


# --- Tool-agnostic config layer ----------------------------------------------
# GATK keeps its bespoke functions above (portfolio guardrails, rich ordering).
# These helpers let any tool (DeepVariant, BCFtools) round-trip a <tool>.conf
# with the same validation/typing/backup guarantees.


def coerce_param_types(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Cast values to the tool schema types (ints not left as float, etc.)."""
    tool = (tool or "gatk").lower()
    if tool == "gatk":
        return coerce_gatk_param_types(params)
    from tuning.tool_catalog import tool_param_defs

    defs = tool_param_defs(tool)
    out = dict(params)
    for key, value in list(out.items()):
        spec = defs.get(key)
        if spec is None or value is None:
            continue
        ptype = spec.get("type")
        try:
            if ptype == "int" and not isinstance(value, bool) and not isinstance(value, int):
                out[key] = int(round(float(value)))
            elif ptype == "float" and not isinstance(value, (int, float)):
                out[key] = float(value)
            elif ptype == "bool" and not isinstance(value, bool):
                out[key] = str(value).strip().lower() == "true" if isinstance(value, str) else bool(value)
        except (TypeError, ValueError):
            continue
    return out


def clamp_to_tool_schema(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp numeric params into their schema [min, max] so tuner output stays valid."""
    from tuning.tool_catalog import tool_param_defs

    defs = tool_param_defs(tool)
    out = dict(params)
    for key, value in list(out.items()):
        spec = defs.get(key)
        if not spec or value is None:
            continue
        ptype = spec.get("type")
        if ptype not in ("int", "float") or isinstance(value, bool):
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None:
            v = max(float(lo), v)
        if hi is not None:
            v = min(float(hi), v)
        out[key] = int(round(v)) if ptype == "int" else v
    return out


def validate_tool_config(tool: str, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate params against a tool's whitelist + ranges."""
    tool = (tool or "gatk").lower()
    result = validate_and_build_flags(tool, coerce_param_types(tool, params))
    return result["valid"], list(result.get("errors") or [])


def render_tool_config_text(
    tool: str, params: Dict[str, Any], header: Optional[List[str]] = None
) -> str:
    """Render params as <tool>.conf text in recommended order."""
    tool = (tool or "gatk").lower()
    if tool == "gatk":
        return render_config_text(params, header=header)

    from tuning.tool_catalog import ordered_tool_param_names

    lines = list(header) if header is not None else [
        f"# {tool} quality parameters",
        "# Managed via the Minos tuning UI (tuning/app.py)",
        "# Only quality-affecting params — threads, memory, timeout are auto-detected.",
        "",
    ]

    def _render(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    written = set()
    for name in ordered_tool_param_names(tool):
        if name not in params:
            continue
        lines.append(f"{name}={_render(params[name])}")
        written.add(name)
    for name in sorted(params):
        if name in written:
            continue
        lines.append(f"{name}={_render(params[name])}")
    lines.append("")
    return "\n".join(lines)


def load_tool_config(tool: Optional[str] = None, path: Optional[Path] = None) -> Dict[str, Any]:
    """Load a tool's <tool>.conf for the active instance (or an explicit path)."""
    from tuning.instance import tool_conf_path

    if path is None:
        resolved = (tool or "gatk").lower()
        path = tool_conf_path(tool=resolved)
    if not path.exists():
        return {}
    return _load_from_path(path)


def _prune_tool_backups(backups: Path, tool: str) -> None:
    if BACKUP_RETENTION <= 0 or not backups.is_dir():
        return
    files = sorted(
        backups.glob(f"{tool}.conf.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in files[BACKUP_RETENTION:]:
        try:
            old.unlink()
        except OSError:
            pass


def save_tool_config(
    tool: str,
    params: Dict[str, Any],
    *,
    backup: bool = True,
    path: Optional[Path] = None,
    sanitize: bool = True,
) -> Path:
    """Write any tool's <tool>.conf with clamping, validation, and timestamped backup."""
    tool = (tool or "gatk").lower()
    if tool == "gatk":
        return save_gatk_config(params, backup=backup, path=path, sanitize=sanitize)

    from tuning.instance import tool_conf_path

    target = path or tool_conf_path(tool=tool)
    if sanitize:
        params = clamp_to_tool_schema(tool, coerce_param_types(tool, params))
    else:
        params = coerce_param_types(tool, params)
    valid, errors = validate_tool_config(tool, params)
    if not valid:
        raise ValueError(f"Invalid {tool} config:\n" + "\n".join(errors))

    new_text = render_tool_config_text(tool, params)
    if target.exists() and target.read_text(encoding="utf-8") == new_text:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    backups = _backup_dir()
    if backup and target.exists():
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(target, backups / f"{tool}.conf.{stamp}.bak")
        _prune_tool_backups(backups, tool)

    target.write_text(new_text, encoding="utf-8")
    return target


def ensure_tool_config_valid(
    tool: Optional[str] = None,
    *,
    path: Optional[Path] = None,
    repair: bool = True,
    sanitize: bool = True,
) -> Dict[str, Any]:
    """Validate (and optionally repair) the active tool's config before a run.

    Manual submit passes sanitize=False so autotune GUARD/INVARIANT clamps are not
    applied to the operator's saved editor values.
    """
    resolved = (tool or "gatk").lower()
    if resolved == "gatk":
        return ensure_gatk_config_valid(path=path, repair=repair, sanitize=sanitize)

    cfg = load_tool_config(resolved, path)
    if not cfg:
        # No config on disk yet — seed from schema defaults so the run can proceed.
        from tuning.tool_catalog import tool_defaults

        cfg = tool_defaults(resolved)
    fixed = clamp_to_tool_schema(resolved, coerce_param_types(resolved, cfg))
    valid, errors = validate_tool_config(resolved, fixed)
    if not valid:
        raise ValueError(f"Invalid {resolved} config:\n" + "\n".join(errors))
    if repair and fixed != cfg:
        save_tool_config(resolved, fixed, backup=True, path=path)
    return fixed


def coerce_gatk_param_types(params: Dict[str, Any]) -> Dict[str, Any]:
    """Cast tuning outputs to GATK schema types (e.g. int params must not stay float)."""
    from templates.tool_params import GATK_QUALITY_PARAMS

    out = dict(params)
    for key, value in list(out.items()):
        spec = GATK_QUALITY_PARAMS.get(key)
        if spec is None or value is None:
            continue
        ptype = spec.get("type")
        try:
            if ptype == "int":
                if not isinstance(value, int):
                    out[key] = int(round(float(value)))
            elif ptype == "float":
                if not isinstance(value, (int, float)):
                    out[key] = float(value)
            elif ptype == "bool" and not isinstance(value, bool):
                if isinstance(value, str):
                    out[key] = value.strip().lower() == "true"
                else:
                    out[key] = bool(value)
        except (TypeError, ValueError):
            continue
    return out


def render_config_text(params: Dict[str, Any], header: Optional[List[str]] = None) -> str:
    """Render params as gatk.conf text (ordered, with header comments)."""
    lines = list(header) if header is not None else [
        "# GATK HaplotypeCaller Quality Parameters",
        "# Managed via Minos tuning UI (tuning/app.py)",
        "# Only quality-affecting params — threads, memory, timeout are auto-detected.",
        "",
    ]

    from tuning.param_catalog import ordered_param_names

    def _render(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    written = set()
    for name in ordered_param_names():
        if name not in params:
            continue
        lines.append(f"{name}={_render(params[name])}")
        written.add(name)

    for name in sorted(params):
        if name in written:
            continue
        lines.append(f"{name}={_render(params[name])}")

    lines.append("")
    return "\n".join(lines)


def _prune_backups(backups: Path) -> None:
    if BACKUP_RETENTION <= 0 or not backups.is_dir():
        return
    files = sorted(backups.glob("gatk.conf.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[BACKUP_RETENTION:]:
        try:
            old.unlink()
        except OSError:
            pass


def save_gatk_config(
    params: Dict[str, Any],
    *,
    backup: bool = True,
    path: Optional[Path] = None,
    sanitize: bool = True,
) -> Path:
    """Write params to gatk.conf with optional timestamped backup."""
    target = _gatk_path(path)
    try:
        from tuning.instance import list_portfolio_instances

        if sanitize and list_portfolio_instances():
            from tuning.portfolio_coordinator import _sanitize_gatk_config

            params = _sanitize_gatk_config(params)
        elif sanitize:
            from tuning.overnight_autotune import _enforce

            params = _enforce(coerce_gatk_param_types(params))
        else:
            params = coerce_gatk_param_types(params)
    except ImportError:
        params = coerce_gatk_param_types(params)
    valid, errors = validate_config(params)
    if not valid:
        raise ValueError("Invalid GATK config:\n" + "\n".join(errors))

    new_text = render_config_text(params)
    if target.exists() and target.read_text(encoding="utf-8") == new_text:
        return target

    backups = _backup_dir()
    if backup and target.exists():
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups / f"gatk.conf.{stamp}.bak"
        shutil.copy2(target, backup_path)
        _prune_backups(backups)

    target.write_text(new_text, encoding="utf-8")
    return target


def merge_config(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new dict with updates applied."""
    merged = dict(base)
    merged.update(updates)
    return merged


def diff_config(before: Dict[str, Any], after: Dict[str, Any]) -> List[Tuple[str, Any, Any]]:
    """List (param, old, new) for changed keys."""
    changes: List[Tuple[str, Any, Any]] = []
    keys = sorted(set(before) | set(after))
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes.append((key, old, new))
    return changes


def ensure_gatk_config_valid(
    *,
    path: Optional[Path] = None,
    repair: bool = True,
    sanitize: bool = True,
) -> Dict[str, Any]:
    """Load, validate, and optionally sanitize/repair gatk.conf."""
    cfg = load_gatk_config(path)
    if sanitize:
        try:
            from tuning.instance import list_portfolio_instances

            portfolio = bool(list_portfolio_instances())
        except ImportError:
            portfolio = False

        if portfolio:
            from tuning.portfolio_coordinator import _sanitize_gatk_config

            fixed = _sanitize_gatk_config(cfg)
        else:
            from tuning.overnight_autotune import _enforce

            fixed = _enforce(coerce_gatk_param_types(cfg))
    else:
        fixed = coerce_gatk_param_types(cfg)

    valid, errors = validate_config(fixed)
    if not valid:
        raise ValueError("Invalid GATK config:\n" + "\n".join(errors))

    if sanitize and repair and fixed != cfg:
        save_gatk_config(fixed, backup=True, path=path, sanitize=True)
        return fixed
    return cfg
