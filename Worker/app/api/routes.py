import asyncio
import os

import psutil
from fastapi import FastAPI, HTTPException

from app.benchmark import benchmark_status
from app.config import get_settings
from app.core.utils import format_bytes
from app.domain.schemas import (
    BestScoreResponse,
    HealthResponse,
    OptimizeRequest,
    OptimizeResponse,
    StopResponse,
    TrialScoreEntry,
)
from app.domain.state import best_store
from app.optimization.jobs import request_stop_optimization, submit_optimize_job, worker_busy
from app.optimization.optimizer import build_accept_response, validate_optimize_request

settings = get_settings()

app = FastAPI(
    title="Effortless Worker",
    description="Optimizer worker API (health, optimize, best score)",
    version="0.4.0",
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


@app.post("/stop", response_model=StopResponse)
async def stop_optimization() -> StopResponse:
    if not await asyncio.to_thread(request_stop_optimization):
        raise HTTPException(status_code=409, detail="No optimization job is running")
    return StopResponse(
        status="stopping",
        worker=settings.name,
        message="Stop requested — finishing current trial…",
    )
