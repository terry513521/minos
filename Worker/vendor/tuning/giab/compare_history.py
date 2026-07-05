"""Batch GIAB full tests on historical round configs vs platform scores."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tuning.giab.paths import GIAB_RESULTS_DIR
from tuning.giab.quick_test import run_quick_test
from tuning.models import infer_tool_from_config
from tuning.round_ids import is_demo_round_id

logger = logging.getLogger(__name__)

COMPARE_DIR = GIAB_RESULTS_DIR / "compare_batches"
LATEST_FILE = COMPARE_DIR / "latest.json"
_DEFAULT_LIMIT = 20

_BATCH_LOCK = threading.Lock()
_BATCH_THREAD: Optional[threading.Thread] = None
_CANCEL_FLAGS: set[str] = set()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _region_short(region: str) -> str:
    text = str(region or "").strip()
    if not text or ":" not in text:
        return text
    chrom, rest = text.split(":", 1)
    if "-" not in rest:
        return text
    start_s, end_s = rest.split("-", 1)
    try:
        start = int(start_s)
        end = int(end_s)
        return f"{chrom}:{start // 1000}k-{end // 1000}k"
    except ValueError:
        return text


def pick_distinct_region_rounds(*, limit: int = _DEFAULT_LIMIT, instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest scored rounds with unique regions from merged portfolio history."""
    from tuning.instance import discover_instances, is_portfolio_mode
    from tuning.portfolio_intel import _config_usable, portfolio_round_archive
    from tuning.score_store import load_history

    picked: List[Dict[str, Any]] = []
    seen_regions: set[str] = set()

    def _append_from_rec(rid: str, region: str, rec: Dict[str, Any]) -> None:
        if region in seen_regions:
            return
        snap = rec.get("config_snapshot") or {}
        if rec.get("score_100") is None or not _config_usable(snap):
            return
        seen_regions.add(region)
        picked.append(
            {
                "round_id": rid,
                "region": region,
                "region_short": _region_short(region),
                "instance_id": rec.get("instance_id") or instance_id or "default",
                "wallet_hotkey": rec.get("wallet_hotkey"),
                "tool": rec.get("tool") or infer_tool_from_config(snap),
                "platform_score": float(rec["score_100"]),
                "rank": rec.get("rank"),
                "config_snapshot": dict(snap),
            }
        )

    if is_portfolio_mode() and len(discover_instances()) > 1:
        for row in portfolio_round_archive():
            rid = str(row.get("round_id") or "")
            if is_demo_round_id(rid):
                continue
            region = str(row.get("region") or "").strip()
            if not region:
                continue
            inst_map = row.get("instances") or {}
            rec: Optional[Dict[str, Any]] = None
            if instance_id and instance_id in inst_map:
                rec = inst_map[instance_id]
            else:
                best_iid = row.get("best_ours_instance")
                if best_iid and best_iid in inst_map:
                    rec = inst_map[best_iid]
                else:
                    scored = [
                        (iid, data)
                        for iid, data in inst_map.items()
                        if data.get("score_100") is not None
                    ]
                    if scored:
                        rec = max(scored, key=lambda pair: float(pair[1]["score_100"]))[1]
            if rec:
                _append_from_rec(rid, region, rec)
            if len(picked) >= limit:
                break
        return picked

    for rec in load_history():
        rid = str(rec.round_id or "")
        if is_demo_round_id(rid):
            continue
        region = str(rec.region or "").strip()
        if not region:
            continue
        _append_from_rec(rid, region, rec.to_dict())
        if len(picked) >= limit:
            break
    return picked


def _batch_path(batch_id: str) -> Path:
    return COMPARE_DIR / f"{batch_id}.json"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    path = _batch_path(batch_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_batch() -> Optional[Dict[str, Any]]:
    if not LATEST_FILE.is_file():
        return None
    try:
        meta = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    batch_id = str(meta.get("batch_id") or "")
    if not batch_id:
        return None
    return load_batch(batch_id)


def _save_batch(batch: Dict[str, Any]) -> None:
    batch_id = str(batch.get("batch_id") or "")
    if not batch_id:
        return
    batch["updated_at"] = _utc_now()
    _write_json(_batch_path(batch_id), batch)
    _write_json(LATEST_FILE, {"batch_id": batch_id, "updated_at": batch["updated_at"]})


def _item_from_pick(pick: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **pick,
        "status": "pending",
        "giab_score": None,
        "giab_f1_snp": None,
        "giab_f1_indel": None,
        "cache_hit": False,
        "elapsed_ms": None,
        "error": None,
    }


def _apply_giab_result(item: Dict[str, Any], result: Dict[str, Any]) -> None:
    item["cache_hit"] = bool(result.get("cache_hit"))
    item["elapsed_ms"] = result.get("elapsed_ms")
    score = result.get("score")
    if score is not None and result.get("status") == "done":
        item["giab_score"] = float(score)
        item["giab_f1_snp"] = result.get("f1_snp")
        item["giab_f1_indel"] = result.get("f1_indel")
        item["status"] = "done"
        item["error"] = None
    else:
        item["status"] = "failed"
        item["error"] = str(result.get("error") or "GIAB test failed")


def _prefetch_batch_regions(batch_id: str, items: List[Dict[str, Any]]) -> bool:
    """Warm the next few regions in the background. Returns False if cancelled."""
    from tuning.giab.quick_test import schedule_round_bam_prefetch

    seen: set[str] = set()
    for it in items[:3]:
        batch = load_batch(batch_id)
        if batch and (batch.get("cancel_requested") or _is_cancelled(batch_id)):
            return False
        region = str(it.get("region") or "").strip()
        if not region or region in seen:
            continue
        seen.add(region)
        schedule_round_bam_prefetch(region, round_id=str(it.get("round_id") or ""))
    return True


def _worker_alive_for(batch_id: str) -> bool:
    with _BATCH_LOCK:
        return (
            _BATCH_THREAD is not None
            and _BATCH_THREAD.name == batch_id
            and _BATCH_THREAD.is_alive()
        )


def _recover_stale_batch(batch: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize batches left running after a tuner restart or abandoned stop."""
    bid = str(batch.get("batch_id") or "")
    if batch.get("status") != "running" or not bid:
        return batch
    if _worker_alive_for(bid):
        return batch

    items = list(batch.get("items") or [])
    start_idx = 0
    for idx, item in enumerate(items):
        if item.get("status") == "pending":
            start_idx = idx
            break
    else:
        start_idx = len(items)

    if batch.get("cancel_requested") or start_idx < len(items):
        logger.info("Recovering stale compare batch %s at index %s", bid, start_idx)
        _finalize_batch_stopped(batch, items, start_idx)
        return load_batch(bid) or batch
    return batch


def _is_cancelled(batch_id: str) -> bool:
    return batch_id in _CANCEL_FLAGS


def _clear_cancel(batch_id: str) -> None:
    _CANCEL_FLAGS.discard(batch_id)


def _cancel_remaining_items(items: List[Dict[str, Any]], start_idx: int) -> None:
    for item in items[start_idx:]:
        if item.get("status") == "pending":
            item["status"] = "cancelled"


def _finalize_batch_stopped(batch: Dict[str, Any], items: List[Dict[str, Any]], start_idx: int) -> None:
    _cancel_remaining_items(items, start_idx)
    batch["items"] = items
    batch["status"] = "stopped"
    batch["finished_at"] = _utc_now()
    batch["current_index"] = None
    batch["current_region"] = None
    batch["cancel_requested"] = True
    _save_batch(batch)


def _run_batch_worker(batch_id: str) -> None:
    batch = load_batch(batch_id)
    if not batch:
        return
    items = batch.get("items") or []
    force = bool(batch.get("force"))

    batch = load_batch(batch_id) or batch
    if batch.get("cancel_requested") or _is_cancelled(batch_id):
        _finalize_batch_stopped(batch, items, 0)
        _clear_cancel(batch_id)
        return

    if not _prefetch_batch_regions(batch_id, items):
        batch = load_batch(batch_id) or batch
        _finalize_batch_stopped(batch, items, 0)
        _clear_cancel(batch_id)
        return

    completed = 0
    cached_hits = 0
    for idx, item in enumerate(items):
        batch = load_batch(batch_id) or batch
        if batch.get("cancel_requested") or _is_cancelled(batch_id):
            _finalize_batch_stopped(batch, items, idx)
            _clear_cancel(batch_id)
            return

        if not force and item.get("status") == "done" and item.get("giab_score") is not None:
            completed += 1
            if item.get("cache_hit"):
                cached_hits += 1
            continue

        item["status"] = "running"
        batch["current_index"] = idx
        batch["current_region"] = item.get("region")
        batch["completed"] = completed
        batch["cached_hits"] = cached_hits
        batch["items"] = items
        _save_batch(batch)

        try:
            result = run_quick_test(
                str(item.get("instance_id") or "default"),
                str(item.get("tool") or "gatk"),
                str(item.get("region") or ""),
                dict(item.get("config_snapshot") or {}),
                round_id=str(item.get("round_id") or ""),
                force=force,
                test_tier="full",
                quick_max_bp=0,
            )
            _apply_giab_result(item, result)
        except Exception as exc:
            logger.exception("Compare batch GIAB failed for %s", item.get("round_id"))
            item["status"] = "failed"
            item["error"] = str(exc)

        completed += 1
        if item.get("cache_hit"):
            cached_hits += 1
        batch["completed"] = completed
        batch["cached_hits"] = cached_hits
        batch["items"] = items
        _save_batch(batch)

        batch = load_batch(batch_id) or batch
        if batch.get("cancel_requested") or _is_cancelled(batch_id):
            _finalize_batch_stopped(batch, items, idx + 1)
            _clear_cancel(batch_id)
            return

    batch["status"] = "done"
    batch["finished_at"] = _utc_now()
    batch["current_index"] = None
    batch["current_region"] = None
    batch["cancel_requested"] = False
    batch["items"] = items
    _save_batch(batch)
    _clear_cancel(batch_id)


def _start_worker(batch_id: str) -> None:
    global _BATCH_THREAD

    def _target() -> None:
        try:
            _run_batch_worker(batch_id)
        finally:
            with _BATCH_LOCK:
                if _BATCH_THREAD and _BATCH_THREAD.name == batch_id:
                    _BATCH_THREAD = None

    thread = threading.Thread(target=_target, name=batch_id, daemon=True)
    with _BATCH_LOCK:
        _BATCH_THREAD = thread
    thread.start()


def start_compare_batch(*, limit: int = _DEFAULT_LIMIT, instance_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Queue GIAB full re-scores for the last N distinct-region rounds."""
    global _BATCH_THREAD

    with _BATCH_LOCK:
        if _BATCH_THREAD and _BATCH_THREAD.is_alive() and not force:
            latest = load_latest_batch()
            if latest and latest.get("status") == "running":
                return latest

    picks = pick_distinct_region_rounds(limit=limit, instance_id=instance_id)
    if not picks:
        return {"status": "empty", "message": "No scored rounds with configs found", "items": []}

    batch_id = uuid.uuid4().hex[:12]
    items = [_item_from_pick(pick) for pick in picks]
    batch: Dict[str, Any] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": None,
        "updated_at": _utc_now(),
        "limit": limit,
        "instance_filter": instance_id,
        "force": force,
        "cancel_requested": False,
        "total": len(items),
        "completed": 0,
        "cached_hits": 0,
        "current_index": 0,
        "current_region": items[0].get("region") if items else None,
        "items": items,
    }
    _clear_cancel(batch_id)
    _save_batch(batch)
    _start_worker(batch_id)
    return batch


def stop_compare_batch(batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Request stop — immediate if idle; otherwise after the current GIAB test."""
    batch = load_batch(batch_id) if batch_id else load_latest_batch()
    if not batch:
        return {"ok": False, "status": "idle", "message": "No active batch"}
    bid = str(batch.get("batch_id") or "")
    if batch.get("status") != "running":
        return {
            "ok": False,
            "status": batch.get("status"),
            "batch_id": bid,
            "message": "Batch is not running",
        }

    items = list(batch.get("items") or [])
    any_running = any(it.get("status") == "running" for it in items)
    _CANCEL_FLAGS.add(bid)
    batch["cancel_requested"] = True

    if not any_running and not _worker_alive_for(bid):
        start_idx = next((i for i, it in enumerate(items) if it.get("status") == "pending"), len(items))
        _finalize_batch_stopped(batch, items, start_idx)
        _clear_cancel(bid)
        return {
            "ok": True,
            "status": "stopped",
            "batch_id": bid,
            "message": "Compare batch stopped",
        }

    _save_batch(batch)
    return {
        "ok": True,
        "status": "stopping",
        "batch_id": bid,
        "message": "Stop requested — finishing current region" if any_running else "Stop requested",
    }


def compare_batch_status(batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Return batch progress; default to latest."""
    if batch_id:
        batch = load_batch(batch_id)
        if not batch:
            return {"status": "missing", "batch_id": batch_id}
        return _recover_stale_batch(batch)
    latest = load_latest_batch()
    if not latest:
        return {"status": "idle", "items": []}
    return _recover_stale_batch(latest)


def compare_batch_summary(batch: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate stats for UI header."""
    items = batch.get("items") or []
    done = [it for it in items if it.get("giab_score") is not None and it.get("platform_score") is not None]
    deltas = [float(it["giab_score"]) - float(it["platform_score"]) for it in done]
    avg_delta = round(sum(deltas) / len(deltas), 2) if deltas else None
    return {
        "total": len(items),
        "completed": sum(1 for it in items if it.get("status") in ("done", "failed")),
        "scored": len(done),
        "cached_hits": sum(1 for it in items if it.get("cache_hit")),
        "avg_delta": avg_delta,
        "status": batch.get("status"),
    }
