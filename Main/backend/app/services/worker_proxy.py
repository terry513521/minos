"""HTTP proxy helpers for registered optimizer workers."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker
from app.schemas import (
    WorkerBestScoreResponse,
    WorkerDispatchRequest,
    WorkerDispatchResponse,
    WorkerStopResponse,
    WorkerTrialScore,
)
from app.worker_urls import resolve_worker_base_url


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
                best_score=payload.get("best_score"),
                best_conf=payload.get("best_conf")
                if isinstance(payload.get("best_conf"), dict)
                else {},
                trials_evaluated=int(payload.get("trials_evaluated") or 0),
                search_space_size=int(payload.get("search_space_size") or 0),
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
        "base_conf": body.base_conf,
        "params": body.params,
    }
    if body.param_intervals:
        payload["param_intervals"] = {
            name: spec.model_dump(exclude_none=True)
            for name, spec in body.param_intervals.items()
            if name in body.params
        }

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
