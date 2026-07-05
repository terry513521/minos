import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, HTTPException

from app.benchmark import benchmark_status, validate_benchmark_assets, validate_tool_supported
from app.benchmark.jobs import run_benchmark_exclusive
from app.config import get_settings
from app.core.logging_config import configure_worker_logging
from app.core.utils import format_bytes
from app.core.work_status import start_status_reporter, stop_status_reporter
from app.domain.schemas import (
    BenchmarkRequest,
    BenchmarkResponse,
    BestScoreResponse,
    HealthResponse,
    OptimizeRequest,
    OptimizeResponse,
    SeedBatchAcceptResponse,
    SeedBatchRequest,
    SeedResultItem,
    SeedResultsResponse,
    SeedStatusResponse,
    StopResponse,
    TrialScoreEntry,
)
from app.domain.state import best_store
from app.optimization.jobs import request_stop_optimization, submit_optimize_job, worker_busy
from app.optimization.optimizer import build_accept_response, validate_optimize_request
from app.seed.jobs import seed_busy, submit_seed_batch
from app.seed.store import list_results, status_snapshot

settings = get_settings()
logger = logging.getLogger(__name__)

_WINDOW_RE = re.compile(r"^chr\d+:\d+-\d+$", re.IGNORECASE)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    configure_worker_logging(
        settings.log_level,
        quiet_paths=tuple(
            p.strip()
            for p in settings.quiet_access_paths.split(",")
            if p.strip()
        ),
    )
    start_status_reporter(settings.status_interval_sec)
    logger.info(
        "[worker] ready — live status every %.0fs (WORKER_STATUS_INTERVAL_SEC=0 to disable)",
        settings.status_interval_sec,
    )
    yield
    stop_status_reporter()


app = FastAPI(
    title="Effortless Worker",
    description="Optimizer worker API (health, optimize, best score)",
    version="0.4.0",
    lifespan=_lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    mem = psutil.virtual_memory()
    giab = benchmark_status(settings)
    return HealthResponse(
        cpu_count=os.cpu_count() or psutil.cpu_count(logical=True) or 0,
        ram_total=format_bytes(mem.total),
        ram_available=format_bytes(mem.available),
        data_dir=giab.get("data_dir"),
        giab_ready=giab.get("ready"),
        giab_message=giab.get("message"),
    )


@app.get("/best", response_model=BestScoreResponse)
async def get_best() -> BestScoreResponse:
    snap = best_store.snapshot()
    return BestScoreResponse(
        status=snap.status,
        worker=settings.name,
        job_id=snap.job_id,
        window=snap.window,
        tool=snap.tool,
        algorithm=snap.algorithm,
        concurrency=snap.concurrency,
        limit_seconds=snap.limit_seconds,
        adaptive_max_trials=snap.adaptive_max_trials,
        params=list(snap.params),
        trial_threads=snap.trial_threads,
        trial_memory_gb=snap.trial_memory_gb,
        benchmark_window=snap.benchmark_window,
        best_score=snap.best_score,
        best_conf=snap.best_conf,
        trials_evaluated=snap.trials_evaluated,
        search_space_size=snap.search_space_size,
        started_at=snap.started_at.isoformat() if snap.started_at else None,
        updated_at=snap.updated_at.isoformat() if snap.updated_at else None,
        message=snap.message,
        trials=[
            TrialScoreEntry(
                index=trial.index,
                label=trial.label,
                success=trial.success,
                score=trial.score,
                raw_score=trial.raw_score,
                cached=trial.cached,
                error=trial.error,
                is_best=trial.is_best,
                recorded_at=trial.recorded_at.isoformat() if trial.recorded_at else None,
            )
            for trial in snap.trials
        ],
    )


async def _accept_job(body: OptimizeRequest) -> OptimizeResponse:
    if worker_busy():
        raise HTTPException(status_code=409, detail="Worker already running an optimization job")
    if seed_busy():
        raise HTTPException(status_code=409, detail="Worker is running a seed batch")

    try:
        search_space_size = await asyncio.to_thread(validate_optimize_request, body, settings)
        response = build_accept_response(body, settings, search_space_size)
        await asyncio.to_thread(submit_optimize_job, body, settings)
        return response
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/", response_model=OptimizeResponse, status_code=202)
async def post_data(body: OptimizeRequest) -> OptimizeResponse:
    return await _accept_job(body)


@app.post("/optimize", response_model=OptimizeResponse, status_code=202)
async def optimize(body: OptimizeRequest) -> OptimizeResponse:
    return await _accept_job(body)


@app.post("/benchmark", response_model=BenchmarkResponse)
async def benchmark_once(body: BenchmarkRequest) -> BenchmarkResponse:
    """Score one conf on a GIAB window (used by Main chr22 history seeding)."""
    window = body.window.strip()
    tool = body.tool.lower().strip()
    if not _WINDOW_RE.match(window):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid window {window!r}; expected chrN:start-end",
        )
    if worker_busy():
        raise HTTPException(
            status_code=409,
            detail="Worker is running an optimization job; stop it before /benchmark",
        )
    if seed_busy():
        raise HTTPException(
            status_code=409,
            detail="Worker is running a seed batch; wait for /seed/status to finish",
        )
    logger.info("POST /benchmark window=%s tool=%s", window, tool)
    try:
        await asyncio.to_thread(validate_tool_supported, tool)
        await asyncio.to_thread(validate_benchmark_assets, window, settings)
        result = await asyncio.to_thread(
            run_benchmark_exclusive,
            window=window,
            tool=tool,
            conf=body.conf,
            settings=settings,
        )
    except asyncio.CancelledError:
        logger.warning(
            "POST /benchmark cancelled for window=%s (server shutdown or client disconnect)",
            window,
        )
        raise HTTPException(
            status_code=503,
            detail="Benchmark cancelled — server is shutting down or the client disconnected",
        ) from None
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.success:
        logger.warning(
            "POST /benchmark failed window=%s tool=%s error=%s",
            window,
            tool,
            result.error,
        )

    return BenchmarkResponse(
        success=result.success,
        window=window,
        tool=tool,
        score=result.score if result.success else None,
        raw_score=result.raw_score if result.success else None,
        variant_count=result.variant_count,
        cached=result.cached,
        error=result.error,
    )


@app.post("/seed/batch", response_model=SeedBatchAcceptResponse, status_code=202)
async def seed_batch(body: SeedBatchRequest) -> SeedBatchAcceptResponse:
    """Accept a chr22 seed batch; benchmarks run locally in the background."""
    if worker_busy():
        raise HTTPException(
            status_code=409,
            detail="Worker is running an optimization job; stop it before seeding",
        )
    if not body.items:
        raise HTTPException(status_code=400, detail="items must not be empty")
    for item in body.items:
        if not _WINDOW_RE.match(item.target_window.strip()):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target_window {item.target_window!r}; expected chrN:start-end",
            )
    logger.info("POST /seed/batch items=%s batch_id=%s", len(body.items), body.batch_id)
    entries = [item.model_dump() for item in body.items]
    batch_id, queued, skipped = await asyncio.to_thread(
        submit_seed_batch,
        batch_id=body.batch_id,
        items=entries,
        settings=settings,
    )
    return SeedBatchAcceptResponse(
        status="accepted",
        batch_id=batch_id,
        queued=queued,
        skipped_duplicate=skipped,
        message=(
            f"Queued {queued} seed benchmark(s)"
            + (f", skipped {skipped} duplicate(s)" if skipped else "")
            + ". Poll GET /seed/results for completed scores."
        ),
    )


@app.get("/seed/status", response_model=SeedStatusResponse)
async def seed_status() -> SeedStatusResponse:
    snap = await asyncio.to_thread(status_snapshot)
    return SeedStatusResponse(**snap)


@app.get("/seed/results", response_model=SeedResultsResponse)
async def seed_results(status: str | None = None) -> SeedResultsResponse:
    """Return locally stored seed benchmark results (optionally filter by status)."""
    rows = await asyncio.to_thread(list_results, status=status)
    return SeedResultsResponse(
        total=len(rows),
        results=[SeedResultItem(**row) for row in rows],
    )


@app.post("/stop", response_model=StopResponse)
async def stop_optimization() -> StopResponse:
    if not await asyncio.to_thread(request_stop_optimization):
        raise HTTPException(status_code=409, detail="No optimization job is running")
    return StopResponse(
        status="stopping",
        worker=settings.name,
        message="Stop requested — finishing current trial…",
    )
