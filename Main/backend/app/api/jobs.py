from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OptimizationJob
from app.schemas import JobStatus, JobSummary

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
async def list_jobs(db: AsyncSession = Depends(get_db)) -> list[JobSummary]:
    result = await db.execute(
        select(OptimizationJob).order_by(OptimizationJob.started_at.desc().nullslast()).limit(200)
    )
    jobs = result.scalars().all()
    return [
        JobSummary(
            job_id=j.id,
            worker_id=j.worker_id,
            candidate_index=j.candidate_index,
            status=JobStatus(j.status.value),
            best_score=j.best_score,
        )
        for j in jobs
    ]


@router.get("/{job_id}/trials")
async def get_job_trials(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(OptimizationJob).where(OptimizationJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job.id, "trials": job.trials or []}
