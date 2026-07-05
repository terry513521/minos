"""History API — list, import, sync, and chr22 seeding."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.history_origin import HISTORY_ORIGIN_LABELS, HISTORY_ORIGINS
from app.models import OptimizationRun, RoundHistory
from app.schemas import (
    CreateHistoryRequest,
    HistoryChromosomeSummary,
    HistoryImportResponse,
    HistoryOriginSummary,
    HistoryRecord,
    HistorySeedChr22Request,
    HistorySeedChr22Response,
    HistorySeedSyncRequest,
    HistorySeedSyncResponse,
)
from app.serializers import history_to_response
from app.services.history_import import import_history_api, import_history_files
from app.services.history_seed import seed_chr22_history
from app.services.history_seed_sync import sync_seed_results_from_workers
from app.services.history_store import save_history_from_run, save_history_record

router = APIRouter(prefix="/history", tags=["history"])


def _origin_filter(origin: str | None):
    if not origin:
        return None
    key = origin.lower().strip()
    if key == "import":
        key = "import"
    if key not in HISTORY_ORIGINS:
        return None
    return key


@router.get("/chromosomes", response_model=list[HistoryChromosomeSummary])
async def list_history_chromosomes(db: AsyncSession = Depends(get_db)) -> list[HistoryChromosomeSummary]:
    result = await db.execute(
        select(RoundHistory.chromosome, RoundHistory.history_origin, func.count())
        .group_by(RoundHistory.chromosome, RoundHistory.history_origin)
        .order_by(RoundHistory.chromosome)
    )
    buckets: dict[str, dict[str, int]] = {}
    for chrom, origin, count in result.all():
        row = buckets.setdefault(chrom, {"count": 0, "portfolio": 0, "seed": 0, "worker": 0, "import": 0})
        origin_key = origin if origin in HISTORY_ORIGINS else "portfolio"
        if origin_key == "import":
            row["import"] += count
        else:
            row[origin_key] += count
        row["count"] += count

    return [
        HistoryChromosomeSummary(
            chromosome=chrom,
            count=totals["count"],
            portfolio=totals["portfolio"],
            seed=totals["seed"],
            worker=totals["worker"],
            import_=totals["import"],
        )
        for chrom, totals in sorted(buckets.items())
    ]


@router.get("/origins", response_model=list[HistoryOriginSummary])
async def list_history_origins(db: AsyncSession = Depends(get_db)) -> list[HistoryOriginSummary]:
    result = await db.execute(
        select(RoundHistory.history_origin, func.count())
        .group_by(RoundHistory.history_origin)
        .order_by(RoundHistory.history_origin)
    )
    out: list[HistoryOriginSummary] = []
    for origin, count in result.all():
        key = origin if origin in HISTORY_ORIGINS else "portfolio"
        out.append(
            HistoryOriginSummary(
                origin=key,
                label=HISTORY_ORIGIN_LABELS.get(key, key),
                count=count,
            )
        )
    return out


@router.get("/count")
async def history_count(
    chromosome: str | None = None,
    tool: str | None = None,
    origin: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = select(func.count()).select_from(RoundHistory)
    if chromosome:
        query = query.where(RoundHistory.chromosome == chromosome)
    if tool:
        query = query.where(RoundHistory.tool == tool.lower())
    origin_key = _origin_filter(origin)
    if origin_key:
        query = query.where(RoundHistory.history_origin == origin_key)
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
            history_origin=body.history_origin,
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


@router.post("/sync-rounds", response_model=HistoryImportResponse)
async def sync_rounds_from_api(
    replace: bool = False,
    url: str | None = Query(default=None, description="Override MAIN_HISTORY_API_URL"),
    db: AsyncSession = Depends(get_db),
) -> HistoryImportResponse:
    settings = get_settings()
    target = (url or settings.history_api_url or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="No history API URL configured")
    try:
        result = await import_history_api(
            db,
            target,
            replace=replace,
            timeout=settings.history_api_timeout,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch or import rounds API: {exc}",
        ) from exc
    return HistoryImportResponse(**result.__dict__)


@router.post("/seed-chr22", response_model=HistorySeedChr22Response)
async def seed_chr22_from_portfolio(
    body: HistorySeedChr22Request,
    db: AsyncSession = Depends(get_db),
) -> HistorySeedChr22Response:
    try:
        return await seed_chr22_history(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync-seed-results", response_model=HistorySeedSyncResponse)
async def sync_seed_results(
    body: HistorySeedSyncRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> HistorySeedSyncResponse:
    worker_ids = None
    if body and body.worker_id and body.worker_id.strip():
        worker_ids = [body.worker_id.strip()]
    try:
        return await sync_seed_results_from_workers(db, worker_ids=worker_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[HistoryRecord])
async def list_history(
    chromosome: str | None = None,
    tool: str | None = None,
    origin: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[HistoryRecord]:
    query = select(RoundHistory).order_by(RoundHistory.created_at.desc()).limit(min(limit, 500))
    if chromosome:
        query = query.where(RoundHistory.chromosome == chromosome)
    if tool:
        query = query.where(RoundHistory.tool == tool.lower())
    origin_key = _origin_filter(origin)
    if origin_key:
        query = query.where(RoundHistory.history_origin == origin_key)
    result = await db.execute(query)
    return [history_to_response(r) for r in result.scalars().all()]
