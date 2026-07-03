from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import (
    AutoBestResponse,
    AutoModeStatus,
    AutoModeTunableConfigUpdate,
    AutoModeUpdateRequest,
    AutoStartRequest,
    AutoStartResponse,
)
from app.services.auto_mode import (
    auto_mode_store,
    collect_best_and_stop,
    get_registered_worker_names,
    persist_auto_mode_state,
    restart_auto_mode_session,
    retry_failed_auto_dispatches,
    set_auto_mode_enabled,
    start_auto_mode,
    update_auto_mode_tunable_config,
)

router = APIRouter(prefix="/auto", tags=["auto"])


@router.get("/mode", response_model=AutoModeStatus)
async def get_auto_mode(db: AsyncSession = Depends(get_db)) -> AutoModeStatus:
    from app.services.auto_mode import _heal_legacy_auto_mode_enabled

    worker_names = await get_registered_worker_names(db)
    await _heal_legacy_auto_mode_enabled(db)
    session = auto_mode_store.session
    was_running = bool(session and session.running)
    await retry_failed_auto_dispatches(db)
    status = auto_mode_store.status(worker_names)
    if was_running and not status.running:
        await persist_auto_mode_state(db)
    return status


@router.put("/mode", response_model=AutoModeStatus)
async def set_auto_mode(
    body: AutoModeUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> AutoModeStatus:
    worker_names = await get_registered_worker_names(db)
    return await set_auto_mode_enabled(db, body.enabled, worker_names)


@router.put("/config", response_model=AutoModeStatus)
async def set_auto_mode_config(
    body: AutoModeTunableConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> AutoModeStatus:
    try:
        return await update_auto_mode_tunable_config(
            db,
            params=body.params,
            param_intervals=body.param_intervals,
            worker_algorithms=body.worker_algorithms,
            worker_trial_threads=body.worker_trial_threads,
            worker_trial_memory_gb=body.worker_trial_memory_gb,
            worker_concurrency=body.worker_concurrency,
            worker_limit_seconds=body.worker_limit_seconds,
            worker_adaptive_max_trials=body.worker_adaptive_max_trials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start", response_model=AutoStartResponse)
async def start_auto(
    body: AutoStartRequest,
    db: AsyncSession = Depends(get_db),
) -> AutoStartResponse:
    try:
        return await start_auto_mode(db, region=body.region.strip(), tool=body.tool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/restart", response_model=AutoModeStatus)
async def restart_auto(db: AsyncSession = Depends(get_db)) -> AutoModeStatus:
    return await restart_auto_mode_session(db)


@router.get("/best", response_model=AutoBestResponse)
async def export_auto_best(db: AsyncSession = Depends(get_db)) -> AutoBestResponse:
    return await collect_best_and_stop(db)
