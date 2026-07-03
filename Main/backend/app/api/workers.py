import secrets
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
    WorkerStopAllResult,
    WorkerStatus,
    WorkerStopResponse,
    WorkersStopAllResponse,
    WorkerTunableBulkUpdate,
    WorkerTunableDefaultsListResponse,
    WorkerTunableDefaultsResponse,
    WorkerTunableProfileBody,
    WorkerUpdate,
)
from app.serializers import worker_to_response
from app.services.worker_proxy import (
    dispatch_to_worker,
    fetch_worker_best,
    get_worker,
    stop_all_workers_optimization,
    stop_worker_optimization,
)
from app.services.worker_tunable_defaults import (
    bulk_save_worker_tunable_defaults,
    get_worker_tunable_defaults,
    list_worker_tunable_defaults,
    save_worker_tunable_defaults,
)
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


@router.get("/tunable-defaults", response_model=WorkerTunableDefaultsListResponse)
async def list_worker_tunable_defaults_endpoint(
    db: AsyncSession = Depends(get_db),
) -> WorkerTunableDefaultsListResponse:
    return await list_worker_tunable_defaults(db)


@router.put("/tunable-defaults/bulk", response_model=WorkerTunableDefaultsListResponse)
async def bulk_update_worker_tunable_defaults(
    body: WorkerTunableBulkUpdate,
    db: AsyncSession = Depends(get_db),
) -> WorkerTunableDefaultsListResponse:
    try:
        return await bulk_save_worker_tunable_defaults(db, body.items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{worker_id}/tunable-defaults", response_model=WorkerTunableDefaultsResponse)
async def get_worker_tunable_defaults_endpoint(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerTunableDefaultsResponse:
    row = await get_worker_tunable_defaults(db, worker_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Worker tunable defaults not found")
    return row


@router.put("/{worker_id}/tunable-defaults", response_model=WorkerTunableDefaultsResponse)
async def update_worker_tunable_defaults(
    worker_id: str,
    body: WorkerTunableProfileBody,
    db: AsyncSession = Depends(get_db),
) -> WorkerTunableDefaultsResponse:
    try:
        return await save_worker_tunable_defaults(db, worker_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.post("/stop-all", response_model=WorkersStopAllResponse)
async def stop_all_workers_endpoint(
    db: AsyncSession = Depends(get_db),
) -> WorkersStopAllResponse:
    from app.services.auto_mode import auto_mode_store, persist_auto_mode_state
    from app.services.auto_round_history import record_auto_round_if_needed

    raw_results = await stop_all_workers_optimization(db)
    session = auto_mode_store.session
    was_running = bool(session and session.running)
    if session:
        session.running = False
    if was_running:
        await record_auto_round_if_needed(db, end_reason="stop_all")
    await persist_auto_mode_state(db)

    results = [WorkerStopAllResult(**row) for row in raw_results]
    stopped_ok = sum(1 for row in results if row.ok)
    return WorkersStopAllResponse(
        workers=len(results),
        stopped_ok=stopped_ok,
        results=results,
    )


@router.get("/{worker_id}/health-check", response_model=WorkerHealthCheckResponse)
async def check_worker_health(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerHealthCheckResponse:
    worker = await get_worker(db, worker_id)
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
async def fetch_worker_best_endpoint(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerBestScoreResponse:
    return await fetch_worker_best(db, worker_id)


@router.post("/{worker_id}/dispatch", response_model=WorkerDispatchResponse)
async def dispatch_to_worker_endpoint(
    worker_id: str,
    body: WorkerDispatchRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkerDispatchResponse:
    return await dispatch_to_worker(db, worker_id, body)


@router.post("/{worker_id}/stop", response_model=WorkerStopResponse)
async def stop_worker_optimization_endpoint(
    worker_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkerStopResponse:
    return await stop_worker_optimization(db, worker_id)
