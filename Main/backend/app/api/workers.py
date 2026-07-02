import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OptimizationJob, Worker, WorkerStatus as OrmWorkerStatus
from app.schemas import (
    WorkerBestScoreResponse,
    WorkerCreate,
    WorkerDispatchRequest,
    WorkerDispatchResponse,
    WorkerHealthCheckResponse,
    WorkerRegisterResponse,
    WorkerResponse,
    WorkerStatus,
    WorkerStopResponse,
    WorkerTrialScore,
    WorkerUpdate,
)
from app.serializers import worker_to_response
from app.worker_urls import normalize_worker_urls, resolve_worker_base_url

router = APIRouter(prefix="/workers", tags=["workers"])


async def _probe_health_url(url: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail=f"Health check failed ({response.status_code}): {url}",
                )
    except HTTPException:
        raise
    except Exception as exc:
        host_hint = ""
        if "192.168." in url or "10." in url or "172.16." in url or "172.17." in url:
            host_hint = (
                " Private LAN IPs (192.168.x.x) are only reachable from the same network. "
                "The control plane probes workers from its own server, not from your browser."
            )
        raise HTTPException(
            status_code=400,
            detail=f"Health check unreachable: {url} ({exc}).{host_hint}",
        ) from exc


@router.get("", response_model=list[WorkerResponse])
async def list_workers(db: AsyncSession = Depends(get_db)) -> list[WorkerResponse]:
    result = await db.execute(select(Worker).order_by(Worker.name))
    return [worker_to_response(w) for w in result.scalars().all()]


@router.post("/register", response_model=WorkerRegisterResponse, status_code=201)
async def register_worker(body: WorkerCreate, db: AsyncSession = Depends(get_db)) -> WorkerRegisterResponse:
    existing = await db.execute(select(Worker).where(Worker.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Worker name already exists: {body.name}")

    if body.health_url:
        await _probe_health_url(body.health_url.strip())

    health_url, base_url = normalize_worker_urls(body.health_url, body.base_url)

    worker = Worker(
        name=body.name.strip(),
        health_url=health_url,
        base_url=base_url,
        capabilities=body.capabilities,
        tags=body.tags,
        status=OrmWorkerStatus.OFFLINE,
    )
    db.add(worker)
    await db.commit()
    await db.refresh(worker)

    token = secrets.token_urlsafe(32)
    return WorkerRegisterResponse(worker=worker_to_response(worker), registration_token=token)


@router.delete("/{worker_id}")
async def delete_worker(worker_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")

    await db.execute(
        update(OptimizationJob)
        .where(OptimizationJob.worker_id == worker_id)
        .values(worker_id=None)
    )
    await db.delete(worker)
    await db.commit()
    return {"ok": "true", "worker_id": worker_id}


@router.patch("/{worker_id}", response_model=WorkerResponse)
async def update_worker(
    worker_id: str,
    body: WorkerUpdate | None = None,
    status: WorkerStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> WorkerResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")

    if body is not None:
        next_health = body.health_url if body.health_url is not None else worker.health_url
        next_base = body.base_url if body.base_url is not None else worker.base_url
        health_url, base_url = normalize_worker_urls(next_health, next_base)
        if body.health_url is not None:
            if health_url:
                await _probe_health_url(health_url)
            worker.health_url = health_url
        if body.base_url is not None or body.health_url is not None:
            worker.base_url = base_url
        if body.status is not None:
            worker.status = OrmWorkerStatus(body.status.value)
    elif status is not None:
        worker.status = OrmWorkerStatus(status.value)

    await db.commit()
    await db.refresh(worker)
    return worker_to_response(worker)


@router.post("/{worker_id}/heartbeat", response_model=WorkerResponse)
async def worker_heartbeat(
    worker_id: str,
    version: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> WorkerResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    worker.last_heartbeat = datetime.now(timezone.utc)
    worker.status = OrmWorkerStatus.ONLINE
    if version:
        worker.version = version
    await db.commit()
    await db.refresh(worker)
    return worker_to_response(worker)


@router.get("/{worker_id}/health-check", response_model=WorkerHealthCheckResponse)
async def check_worker_health(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerHealthCheckResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.health_url:
        return WorkerHealthCheckResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no health_url configured",
        )

    url = worker.health_url.strip()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            health: dict | None = None
            if response.headers.get("content-type", "").startswith("application/json"):
                parsed = response.json()
                if isinstance(parsed, dict):
                    health = parsed
            ok = response.status_code < 400
            return WorkerHealthCheckResponse(
                worker_id=worker_id,
                ok=ok,
                status_code=response.status_code,
                health=health,
                error=None if ok else f"Health check failed ({response.status_code})",
            )
    except Exception as exc:
        return WorkerHealthCheckResponse(
            worker_id=worker_id,
            ok=False,
            status_code=None,
            health=None,
            error=str(exc),
        )


@router.get("/{worker_id}/best", response_model=WorkerBestScoreResponse)
async def fetch_worker_best(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerBestScoreResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.base_url:
        return WorkerBestScoreResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = resolve_worker_base_url(worker.health_url, worker.base_url)
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
                    error=(payload or {}).get("detail") if payload else response.text[:500] or "Best score fetch failed",
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
                best_conf=payload.get("best_conf") if isinstance(payload.get("best_conf"), dict) else {},
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


@router.post("/{worker_id}/dispatch", response_model=WorkerDispatchResponse)
async def dispatch_to_worker(
    worker_id: str,
    body: WorkerDispatchRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkerDispatchResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.base_url:
        return WorkerDispatchResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = resolve_worker_base_url(worker.health_url, worker.base_url)
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


@router.post("/{worker_id}/stop", response_model=WorkerStopResponse)
async def stop_worker_optimization(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerStopResponse:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not worker.base_url:
        return WorkerStopResponse(
            worker_id=worker_id,
            ok=False,
            error="Worker has no base_url configured",
        )

    base = resolve_worker_base_url(worker.health_url, worker.base_url)
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
