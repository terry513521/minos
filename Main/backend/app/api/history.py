from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import OptimizationRun, RoundHistory
from app.schemas import CreateHistoryRequest, HistoryImportResponse, HistoryRecord
from app.serializers import history_to_response
from app.services.history_import import import_history_files
from app.services.history_store import save_history_from_run, save_history_record

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/chromosomes")
async def list_history_chromosomes(db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(
        select(RoundHistory.chromosome, func.count())
        .group_by(RoundHistory.chromosome)
        .order_by(RoundHistory.chromosome)
    )
    return [{"chromosome": chrom, "count": count} for chrom, count in result.all()]


@router.get("/count")
async def history_count(
    chromosome: str | None = None,
    tool: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = select(func.count()).select_from(RoundHistory)
    if chromosome:
        query = query.where(RoundHistory.chromosome == chromosome)
    if tool:
        query = query.where(RoundHistory.tool == tool.lower())
    total = await db.scalar(query)
    return {"count": total or 0}


@router.post("", response_model=HistoryRecord, status_code=201)
async def create_history(
    body: CreateHistoryRequest,
    db: AsyncSession = Depends(get_db),
) -> HistoryRecord:
    try:
        row = await save_history_record(
            db,
            window=body.window,
            tool=body.tool,
            conf=body.conf,
            score=body.score,
            run_id=body.run_id,
            worker_id=body.worker_id,
            source_key=body.source_key,
            replace=body.replace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return history_to_response(row)


@router.post("/from-run/{run_id}", response_model=HistoryRecord, status_code=201)
async def create_history_from_run(
    run_id: str,
    replace: bool = False,
    db: AsyncSession = Depends(get_db),
) -> HistoryRecord:
    result = await db.execute(select(OptimizationRun).where(OptimizationRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        row = await save_history_from_run(db, run, replace=replace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return history_to_response(row)


@router.post("/import", response_model=HistoryImportResponse)
async def import_history(
    replace: bool = False,
    db: AsyncSession = Depends(get_db),
) -> HistoryImportResponse:
    settings = get_settings()
    result = await import_history_files(db, settings.history_path_list, replace=replace)
    return HistoryImportResponse(**result.__dict__)


@router.get("", response_model=list[HistoryRecord])
async def list_history(
    chromosome: str | None = None,
    tool: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[HistoryRecord]:
    query = select(RoundHistory).order_by(RoundHistory.created_at.desc()).limit(min(limit, 500))
    if chromosome:
        query = query.where(RoundHistory.chromosome == chromosome)
    if tool:
        query = query.where(RoundHistory.tool == tool.lower())
    result = await db.execute(query)
    return [history_to_response(r) for r in result.scalars().all()]
