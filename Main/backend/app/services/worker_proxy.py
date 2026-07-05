"""HTTP proxy helpers for registered optimizer workers."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker
from app.schemas import (
    WorkerBestScoreResponse,
    WorkerBenchmarkResponse,
    WorkerDispatchRequest,
    WorkerDispatchResponse,
    WorkerSeedBatchResponse,
    WorkerSeedResultRow,
    WorkerSeedResultsFetchResponse,
    WorkerStopResponse,
    WorkerTrialScore,
)
from app.worker_urls import resolve_worker_base_url


logger = logging.getLogger(__name__)


async def get_worker(db: AsyncSession, worker_id: str) -> Worker | None:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    return result.scalar_one_or_none()


def _resolve_base(worker: Worker) -> str | None:
    return resolve_worker_base_url(worker.health_url, worker.base_url)


async def fetch_worker_best(db: AsyncSession, worker_id: str) -> WorkerBestScoreResponse:
    worker = await get_worker(db, worker_id)
    if worker is None:
        return WorkerBestScoreResponse(worker_id=worker_id, ok=False, error="Worker not found")
    if not worker.base_url:
        return WorkerBestScoreResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = _resolve_base(worker)
    if not base:
        return WorkerBestScoreResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )

    url = f"{base.rstrip('/')}/best"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            payload: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    payload = parsed
            ok = response.status_code < 400
            if not ok or payload is None:
                return WorkerBestScoreResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    error=(payload or {}).get("detail")
                    if payload
                    else response.text[:500] or "Best score fetch failed",
                )
            trials_raw = payload.get("trials")
            trials: list[WorkerTrialScore] = []
            if isinstance(trials_raw, list):
                for item in trials_raw:
                    if not isinstance(item, dict):
                        continue
                    try:
                        trials.append(WorkerTrialScore.model_validate(item))
                    except Exception:
                        continue
            return WorkerBestScoreResponse(
                worker_id=worker_id,
                ok=True,
                status_code=response.status_code,
                status=str(payload.get("status")) if payload.get("status") is not None else None,
                job_id=payload.get("job_id"),
                window=payload.get("window"),
                tool=payload.get("tool"),
                algorithm=payload.get("algorithm"),
                concurrency=payload.get("concurrency"),
                limit_seconds=payload.get("limit_seconds"),
                adaptive_max_trials=payload.get("adaptive_max_trials"),
                params=list(payload.get("params") or [])
                if isinstance(payload.get("params"), list)
                else [],
                trial_threads=payload.get("trial_threads"),
                trial_memory_gb=payload.get("trial_memory_gb"),
                benchmark_window=payload.get("benchmark_window"),
                best_score=payload.get("best_score"),
                best_conf=payload.get("best_conf")
                if isinstance(payload.get("best_conf"), dict)
                else {},
                trials_evaluated=int(payload.get("trials_evaluated") or 0),
                search_space_size=int(payload.get("search_space_size") or 0),
                started_at=payload.get("started_at"),
                updated_at=payload.get("updated_at"),
                message=payload.get("message"),
                trials=trials,
            )
    except Exception as exc:
        return WorkerBestScoreResponse(
            worker_id=worker_id,
            ok=False,
            status_code=None,
            error=str(exc),
        )


async def fetch_workers_best(
    db: AsyncSession,
    worker_ids: list[str] | None = None,
) -> list[WorkerBestScoreResponse]:
    """Fetch GET /best from many workers in one Main request (parallel upstream)."""
    if worker_ids:
        out: list[WorkerBestScoreResponse] = []
        for worker_id in worker_ids:
            out.append(await fetch_worker_best(db, worker_id))
        return out

    result = await db.execute(select(Worker).order_by(Worker.name))
    workers = list(result.scalars().all())
    if not workers:
        return []
    return list(
        await asyncio.gather(*(fetch_worker_best(db, worker.id) for worker in workers))
    )


async def dispatch_to_worker(
    db: AsyncSession,
    worker_id: str,
    body: WorkerDispatchRequest,
) -> WorkerDispatchResponse:
    worker = await get_worker(db, worker_id)
    if worker is None:
        return WorkerDispatchResponse(worker_id=worker_id, ok=False, error="Worker not found")
    if not worker.base_url:
        return WorkerDispatchResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = _resolve_base(worker)
    if not base:
        return WorkerDispatchResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )

    optimize_url = f"{base.rstrip('/')}/optimize"
    job_id = f"main-{worker_id[:8]}-{uuid.uuid4().hex[:8]}"
    payload = {
        "job_id": job_id,
        "window": body.window.strip(),
        "tool": body.tool.strip(),
        "concurrency": str(body.concurrency),
        "algorithm": body.algorithm,
        "limit": str(body.limit_seconds),
        "adaptive_max_trials": body.adaptive_max_trials,
        "include_base_benchmark": body.include_base_benchmark,
        "base_conf": body.base_conf,
        "params": body.params,
    }
    if body.param_intervals:
        payload["param_intervals"] = {
            name: spec.model_dump(exclude_none=True)
            for name, spec in body.param_intervals.items()
            if name in body.params
        }
    if body.delta_rounds is not None:
        payload["delta_rounds"] = body.delta_rounds

    try:
        timeout = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(optimize_url, json=payload)
            result_body: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    result_body = parsed
            ok = response.status_code < 400
            if ok and result_body:
                worker_status = str(result_body.get("status") or "").lower()
                if worker_status not in ("accepted", "completed"):
                    ok = False
                    error = result_body.get("message") or f"Unexpected worker status: {worker_status}"
                else:
                    error = None
            elif not ok:
                detail = result_body.get("detail") if result_body else None
                if isinstance(detail, list):
                    error = str(detail)
                elif detail:
                    error = str(detail)
                else:
                    error = response.text[:500] or f"Worker returned {response.status_code}"
            else:
                error = None
            return WorkerDispatchResponse(
                worker_id=worker_id,
                ok=ok,
                status_code=response.status_code,
                result=result_body,
                error=error,
            )
    except Exception as exc:
        return WorkerDispatchResponse(
            worker_id=worker_id,
            ok=False,
            status_code=None,
            result=None,
            error=str(exc),
        )


async def stop_worker_optimization(db: AsyncSession, worker_id: str) -> WorkerStopResponse:
    worker = await get_worker(db, worker_id)
    if worker is None:
        return WorkerStopResponse(worker_id=worker_id, ok=False, error="Worker not found")
    if not worker.base_url:
        return WorkerStopResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = _resolve_base(worker)
    if not base:
        return WorkerStopResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )

    stop_url = f"{base.rstrip('/')}/stop"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.post(stop_url)
            payload: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    payload = parsed
            ok = response.status_code < 400
            if not ok:
                detail = payload.get("detail") if payload else None
                if isinstance(detail, list):
                    error = str(detail)
                elif detail:
                    error = str(detail)
                else:
                    error = response.text[:500] or f"Worker returned {response.status_code}"
                return WorkerStopResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    error=error,
                )
            return WorkerStopResponse(
                worker_id=worker_id,
                ok=True,
                status_code=response.status_code,
                status=str(payload.get("status")) if payload and payload.get("status") is not None else None,
                message=str(payload.get("message")) if payload and payload.get("message") is not None else None,
            )
    except Exception as exc:
        return WorkerStopResponse(
            worker_id=worker_id,
            ok=False,
            status_code=None,
            error=str(exc),
        )


async def benchmark_on_worker(
    db: AsyncSession,
    *,
    worker_id: str,
    window: str,
    tool: str,
    conf: dict[str, Any],
    timeout: float = 3600.0,
) -> WorkerBenchmarkResponse:
    """POST /benchmark on a registered worker — one GIAB score, no optimization."""
    worker = await get_worker(db, worker_id)
    if worker is None:
        return WorkerBenchmarkResponse(worker_id=worker_id, ok=False, error="Worker not found")
    base = _resolve_base(worker) if worker else None
    return await post_worker_benchmark(
        base_url=base,
        worker_id=worker_id,
        window=window,
        tool=tool,
        conf=conf,
        timeout=timeout,
    )


async def post_worker_benchmark(
    *,
    base_url: str | None,
    worker_id: str,
    window: str,
    tool: str,
    conf: dict[str, Any],
    timeout: float = 3600.0,
) -> WorkerBenchmarkResponse:
    """POST /benchmark when the worker base URL is already resolved."""
    if not base_url:
        return WorkerBenchmarkResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )

    url = f"{base_url.rstrip('/')}/benchmark"
    payload = {"window": window, "tool": tool.lower().strip(), "conf": conf}
    logger.info(
        "POST %s worker_id=%s window=%s tool=%s",
        url,
        worker_id,
        window,
        tool,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(url, json=payload)
            body: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            if response.status_code >= 400 or body is None:
                return WorkerBenchmarkResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    error=(body or {}).get("detail")
                    if body
                    else response.text[:500] or "Benchmark request failed",
                )
            if not body.get("success"):
                return WorkerBenchmarkResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    window=window,
                    tool=tool,
                    error=str(body.get("error") or "Benchmark failed"),
                )
            score = body.get("score")
            return WorkerBenchmarkResponse(
                worker_id=worker_id,
                ok=True,
                status_code=response.status_code,
                window=window,
                tool=tool,
                score=float(score) if score is not None else None,
                raw_score=float(body["raw_score"]) if body.get("raw_score") is not None else None,
                variant_count=int(body.get("variant_count") or 0),
                cached=bool(body.get("cached")),
            )
    except Exception as exc:
        return WorkerBenchmarkResponse(
            worker_id=worker_id,
            ok=False,
            error=str(exc),
        )


async def post_worker_seed_batch(
    *,
    base_url: str | None,
    worker_id: str,
    items: list[dict[str, Any]],
    batch_id: str | None = None,
    timeout: float = 60.0,
) -> WorkerSeedBatchResponse:
    """POST /seed/batch on a registered worker."""
    if not base_url:
        return WorkerSeedBatchResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )
    if not items:
        return WorkerSeedBatchResponse(
            worker_id=worker_id,
            ok=False,
            error="No seed items to queue",
        )

    url = f"{base_url.rstrip('/')}/seed/batch"
    payload: dict[str, Any] = {"items": items}
    if batch_id:
        payload["batch_id"] = batch_id
    logger.info("POST %s worker_id=%s items=%s", url, worker_id, len(items))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(url, json=payload)
            body: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            if response.status_code >= 400 or body is None:
                return WorkerSeedBatchResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    error=(body or {}).get("detail")
                    if body
                    else response.text[:500] or "Seed batch request failed",
                )
            return WorkerSeedBatchResponse(
                worker_id=worker_id,
                ok=True,
                status_code=response.status_code,
                batch_id=str(body.get("batch_id") or "") or None,
                queued=int(body.get("queued") or 0),
                skipped_duplicate=int(body.get("skipped_duplicate") or 0),
                status=str(body.get("status") or "") or None,
            )
    except Exception as exc:
        return WorkerSeedBatchResponse(
            worker_id=worker_id,
            ok=False,
            error=str(exc),
        )


async def fetch_worker_seed_results(
    *,
    base_url: str | None,
    worker_id: str,
    status: str | None = "scored",
    timeout: float = 30.0,
) -> WorkerSeedResultsFetchResponse:
    """GET /seed/results from a registered worker."""
    if not base_url:
        return WorkerSeedResultsFetchResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no valid base_url configured",
        )

    url = f"{base_url.rstrip('/')}/seed/results"
    params = {"status": status} if status else None
    logger.info("GET %s worker_id=%s status=%s", url, worker_id, status)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            body: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            if response.status_code >= 400 or body is None:
                return WorkerSeedResultsFetchResponse(
                    worker_id=worker_id,
                    ok=False,
                    status_code=response.status_code,
                    error=(body or {}).get("detail")
                    if body
                    else response.text[:500] or "Seed results fetch failed",
                )
            rows_raw = body.get("results")
            results: list[WorkerSeedResultRow] = []
            if isinstance(rows_raw, list):
                for row in rows_raw:
                    if not isinstance(row, dict):
                        continue
                    source_key = str(row.get("source_key") or "").strip()
                    target_window = str(row.get("target_window") or "").strip()
                    if not source_key or not target_window:
                        continue
                    tool = str(row.get("tool") or "gatk").lower().strip()
                    conf = row.get("conf")
                    if not isinstance(conf, dict):
                        conf = {}
                    results.append(
                        WorkerSeedResultRow(
                            source_key=source_key,
                            source_id=str(row.get("source_id") or row.get("seed_id") or "") or None,
                            seed_id=str(row.get("seed_id") or "") or None,
                            source_window=str(row.get("source_window") or "") or None,
                            target_window=target_window,
                            tool=tool,
                            conf=conf,
                            status=str(row.get("status") or "") or None,
                            success=bool(row.get("success")),
                            score=float(row["score"]) if row.get("score") is not None else None,
                            error=str(row.get("error") or "") or None,
                        )
                    )
            return WorkerSeedResultsFetchResponse(
                worker_id=worker_id,
                ok=True,
                status_code=response.status_code,
                results=results,
            )
    except Exception as exc:
        return WorkerSeedResultsFetchResponse(
            worker_id=worker_id,
            ok=False,
            error=str(exc),
        )


async def resolve_worker_base_urls(
    db: AsyncSession,
    worker_ids: list[str],
) -> dict[str, str | None]:
    """Map worker id → base URL (or None when missing / invalid)."""
    out: dict[str, str | None] = {}
    for worker_id in worker_ids:
        worker = await get_worker(db, worker_id)
        out[worker_id] = _resolve_base(worker) if worker else None
    return out


async def resolve_seed_workers(
    db: AsyncSession,
    preferred_ids: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    """
    Workers Main can POST /benchmark to.

    Returns (unique dispatch ids, skipped entries, worker_id → dispatch URL).
    Skips workers with no resolvable URL or duplicate dispatch URL (same host:port).
    """
    if preferred_ids:
        candidate_ids = list(preferred_ids)
    else:
        result = await db.execute(select(Worker).order_by(Worker.name))
        candidate_ids = [worker.id for worker in result.scalars().all()]

    dispatchable: list[str] = []
    skipped: list[dict[str, str]] = []
    url_by_id: dict[str, str] = {}
    seen_urls: dict[str, str] = {}

    for worker_id in candidate_ids:
        worker = await get_worker(db, worker_id)
        if worker is None:
            skipped.append(
                {
                    "worker_id": worker_id,
                    "worker_name": None,
                    "reason": "Worker not found in database",
                }
            )
            continue

        dispatch_url = _resolve_base(worker)
        if not dispatch_url:
            skipped.append(
                {
                    "worker_id": worker.id,
                    "worker_name": worker.name,
                    "reason": (
                        "No dispatch URL — set health_url (…/health) or base_url "
                        f"(health_url={worker.health_url!r}, base_url={worker.base_url!r})"
                    ),
                }
            )
            continue

        if dispatch_url in seen_urls:
            first_id = seen_urls[dispatch_url]
            skipped.append(
                {
                    "worker_id": worker.id,
                    "worker_name": worker.name,
                    "reason": (
                        f"Duplicate dispatch URL {dispatch_url} "
                        f"(same endpoint as worker {first_id})"
                    ),
                }
            )
            continue

        seen_urls[dispatch_url] = worker.id
        dispatchable.append(worker.id)
        url_by_id[worker.id] = dispatch_url

    return dispatchable, skipped, url_by_id


async def resolve_dispatchable_worker_ids(
    db: AsyncSession,
    *,
    preferred_ids: list[str] | None = None,
) -> list[str]:
    """Workers that Main can reach (base_url or health_url-derived base), in stable order."""
    dispatchable, _, _ = await resolve_seed_workers(db, preferred_ids)
    return dispatchable


async def stop_all_workers_optimization(db: AsyncSession) -> list[dict[str, Any]]:
    """POST /stop on every registered worker."""
    result = await db.execute(select(Worker).order_by(Worker.name))
    workers = list(result.scalars().all())
    stop_results: list[dict[str, Any]] = []
    for worker in workers:
        stop = await stop_worker_optimization(db, worker.id)
        stop_results.append(
            {
                "worker_id": worker.id,
                "worker_name": worker.name,
                "ok": stop.ok,
                "message": stop.message,
                "error": stop.error,
            }
        )
    return stop_results
