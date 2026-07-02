from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import OptimizationRun
from app.orchestrator import cancel_run, create_run, get_run
from app.schemas import CreateRunRequest, RunListItem, RunResponse
from app.serializers import run_to_list_item, run_to_response

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=201)
async def start_run(body: CreateRunRequest, db: AsyncSession = Depends(get_db)) -> RunResponse:
    try:
        run = await create_run(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(
        select(OptimizationRun)
        .where(OptimizationRun.id == run.id)
        .options(selectinload(OptimizationRun.jobs))
    )
    run = result.scalar_one()
    return run_to_response(run)


@router.get("", response_model=list[RunListItem])
async def list_runs(db: AsyncSession = Depends(get_db)) -> list[RunListItem]:
    result = await db.execute(select(OptimizationRun).order_by(OptimizationRun.created_at.desc()).limit(100))
    return [run_to_list_item(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run_detail(run_id: str, db: AsyncSession = Depends(get_db)) -> RunResponse:
    run = await get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_to_response(run)


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run_endpoint(run_id: str, db: AsyncSession = Depends(get_db)) -> RunResponse:
    run = await get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run = await cancel_run(db, run)
    return run_to_response(run)
