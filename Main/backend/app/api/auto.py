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
    restart_auto_mode_session,
    start_auto_mode,
    update_auto_mode_tunable_config,
)

router = APIRouter(prefix="/auto", tags=["auto"])


@router.get("/mode", response_model=AutoModeStatus)
async def get_auto_mode() -> AutoModeStatus:
    return auto_mode_store.status()


@router.put("/mode", response_model=AutoModeStatus)
async def set_auto_mode(body: AutoModeUpdateRequest) -> AutoModeStatus:
    return auto_mode_store.set_enabled(body.enabled)


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
