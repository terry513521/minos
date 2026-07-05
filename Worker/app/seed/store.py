"""Persistent local store for seed batch jobs and benchmark results."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.paths import WORKER_ROOT

_STORE_PATH = WORKER_ROOT / "runs" / "seed_results.json"
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_store() -> dict[str, Any]:
    return {
        "batch_id": None,
        "status": "idle",
        "updated_at": _now_iso(),
        "items": [],
    }


def _load_unlocked() -> dict[str, Any]:
    if not _STORE_PATH.is_file():
        return _default_store()
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_store()
    if not isinstance(data, dict):
        return _default_store()
    data.setdefault("items", [])
    return data


def _save_unlocked(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    tmp = _STORE_PATH.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_STORE_PATH)


def load_store() -> dict[str, Any]:
    with _lock:
        return deepcopy(_load_unlocked())


def replace_store(data: dict[str, Any]) -> None:
    with _lock:
        _save_unlocked(data)


def _item_index(items: list[dict[str, Any]], source_key: str) -> int | None:
    for idx, item in enumerate(items):
        if item.get("source_key") == source_key:
            return idx
    return None


def enqueue_batch(
    *,
    batch_id: str | None,
    entries: list[dict[str, Any]],
) -> tuple[str, int, int]:
    """Append pending seed items. Returns (batch_id, queued, skipped_duplicate)."""
    with _lock:
        data = _load_unlocked()
        resolved_batch = batch_id or f"seed-{uuid4().hex[:12]}"
        items = list(data.get("items") or [])
        queued = 0
        skipped = 0
        for entry in entries:
            source_key = str(entry.get("source_key") or "").strip()
            if not source_key:
                continue
            existing_idx = _item_index(items, source_key)
            if existing_idx is not None:
                existing = items[existing_idx]
                if existing.get("status") in {"pending", "running", "scored"}:
                    skipped += 1
                    continue
            record = {
                "seed_id": entry.get("seed_id") or entry.get("source_id"),
                "source_id": entry.get("source_id"),
                "source_key": source_key,
                "source_window": entry.get("source_window"),
                "target_window": entry.get("target_window"),
                "tool": str(entry.get("tool") or "gatk").lower().strip(),
                "conf": dict(entry.get("conf") or {}),
                "status": "pending",
                "success": False,
                "score": None,
                "raw_score": None,
                "variant_count": 0,
                "cached": False,
                "error": None,
                "batch_id": resolved_batch,
                "queued_at": _now_iso(),
                "started_at": None,
                "finished_at": None,
            }
            if existing_idx is not None:
                items[existing_idx] = record
            else:
                items.append(record)
            queued += 1
        data["batch_id"] = resolved_batch
        data["status"] = "running" if queued > 0 else data.get("status", "idle")
        data["items"] = items
        _save_unlocked(data)
        return resolved_batch, queued, skipped


def next_pending() -> dict[str, Any] | None:
    with _lock:
        data = _load_unlocked()
        for item in data.get("items") or []:
            if item.get("status") == "pending":
                return deepcopy(item)
        return None


def mark_running(source_key: str) -> None:
    with _lock:
        data = _load_unlocked()
        idx = _item_index(data.get("items") or [], source_key)
        if idx is None:
            return
        item = data["items"][idx]
        item["status"] = "running"
        item["started_at"] = _now_iso()
        data["status"] = "running"
        _save_unlocked(data)


def mark_result(
    source_key: str,
    *,
    success: bool,
    score: float | None = None,
    raw_score: float | None = None,
    variant_count: int = 0,
    cached: bool = False,
    error: str | None = None,
) -> None:
    with _lock:
        data = _load_unlocked()
        idx = _item_index(data.get("items") or [], source_key)
        if idx is None:
            return
        item = data["items"][idx]
        item["status"] = "scored" if success else "failed"
        item["success"] = success
        item["score"] = score
        item["raw_score"] = raw_score
        item["variant_count"] = variant_count
        item["cached"] = cached
        item["error"] = error
        item["finished_at"] = _now_iso()
        pending = any(row.get("status") == "pending" for row in data["items"])
        running = any(row.get("status") == "running" for row in data["items"])
        data["status"] = "running" if pending or running else "idle"
        _save_unlocked(data)


def status_snapshot() -> dict[str, Any]:
    with _lock:
        data = _load_unlocked()
        items = list(data.get("items") or [])
        counts = {"pending": 0, "running": 0, "scored": 0, "failed": 0}
        for item in items:
            status = str(item.get("status") or "pending")
            if status in counts:
                counts[status] += 1
        return {
            "status": data.get("status") or "idle",
            "batch_id": data.get("batch_id"),
            "total": len(items),
            **counts,
            "updated_at": data.get("updated_at"),
        }


def list_results(*, status: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        items = list(_load_unlocked().get("items") or [])
    if status:
        key = status.lower().strip()
        items = [item for item in items if str(item.get("status") or "").lower() == key]
    return deepcopy(items)
