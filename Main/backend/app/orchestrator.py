"""Run orchestration — skeleton stubs for job scheduling."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.defaults import default_tool_conf
from app.engine.candidate_finder import CandidateFinderEngine
from app.models import JobStatus, OptimizationJob, OptimizationRun, RunStatus, Worker, WorkerStatus
from app.schemas import CreateRunRequest
from app.selector import parse_window
from app.services.candidate_finder import load_history_entries


async def create_run(db: AsyncSession, body: CreateRunRequest) -> OptimizationRun:
    parsed = parse_window(body.window)

    run = OptimizationRun(
        window=parsed.window,
        chromosome=parsed.chromosome,
        start=parsed.start,
        end=parsed.end,
        tool=body.tool,
        status=RunStatus.SELECTING,
        k_candidates=body.k_candidates,
        top_m=body.top_m,
    )
    db.add(run)
    await db.flush()

    tool_key = body.tool.lower().strip()
    history = await load_history_entries(db, tool=tool_key, chromosome=parsed.chromosome)
    engine = CandidateFinderEngine()
    find_result = engine.find(parsed, history, tool=tool_key, n=body.k_candidates)

    if find_result.selected:
        bases = [
            {
                "id": scored.entry.id,
                "rank_score": scored.rank_score,
                "conf": scored.entry.conf,
                "similarity": scored.similarity,
                "score": scored.entry.score,
            }
            for scored in find_result.selected
        ]
    else:
        bases = [
            {
                "id": None,
                "rank_score": 0.0,
                "conf": default_tool_conf(tool_key),
            }
        ]

    run.base_candidates = [
        {
            "index": i,
            "base_conf": b["conf"],
            "rank_score": b.get("rank_score", 0.0),
            "history_id": b.get("id"),
        }
        for i, b in enumerate(bases)
    ]

    worker_result = await db.execute(
        select(Worker)
        .where(Worker.status == WorkerStatus.ONLINE)
        .order_by(Worker.name)
        .limit(body.max_workers)
    )
    workers = list(worker_result.scalars().all())

    run.status = RunStatus.OPTIMIZING if workers else RunStatus.QUEUED

    for i, base in enumerate(bases):
        worker = workers[i % len(workers)] if workers else None
        job = OptimizationJob(
            run_id=run.id,
            worker_id=worker.id if worker else None,
            candidate_index=i,
            base_conf=base["conf"],
            status=JobStatus.PENDING if worker else JobStatus.PENDING,
        )
        db.add(job)

    if not workers:
        run.status = RunStatus.QUEUED
        run.error_message = "No online workers registered. Jobs queued until workers connect."

    await db.commit()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: str) -> OptimizationRun | None:
    result = await db.execute(
        select(OptimizationRun)
        .where(OptimizationRun.id == run_id)
        .options(selectinload(OptimizationRun.jobs))
    )
    return result.scalar_one_or_none()


async def cancel_run(db: AsyncSession, run: OptimizationRun) -> OptimizationRun:
    if run.status in (RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED):
        return run
    run.status = RunStatus.CANCELLED
    for job in run.jobs:
        if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            job.status = JobStatus.FAILED
    await db.commit()
    await db.refresh(run)
    return run
