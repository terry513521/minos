"""Map ORM models to API schemas."""

from app.models import OptimizationJob, OptimizationRun, RoundHistory, Worker
from app.schemas import (
    BaseCandidate,
    HistoryRecord,
    JobSummary,
    JobStatus,
    RankedCandidate,
    RunListItem,
    RunResponse,
    RunStatus,
    WorkerResponse,
    WorkerStatus,
)


def run_to_response(run: OptimizationRun) -> RunResponse:
    ranked = [
        RankedCandidate(
            rank=c.get("rank", i + 1),
            conf=c.get("conf", {}),
            score=float(c.get("score", 0)),
            worker_id=c.get("worker_id"),
            job_id=c.get("job_id"),
        )
        for i, c in enumerate(run.ranked_candidates or [])
    ]
    bases = [
        BaseCandidate(
            index=b.get("index", 0),
            base_conf=b.get("base_conf", {}),
            rank_score=float(b.get("rank_score", 0)),
            history_id=b.get("history_id"),
        )
        for b in run.base_candidates or []
    ]
    jobs = [
        JobSummary(
            job_id=j.id,
            worker_id=j.worker_id,
            candidate_index=j.candidate_index,
            status=JobStatus(j.status.value),
            best_score=j.best_score,
        )
        for j in (run.jobs or [])
    ]
    return RunResponse(
        run_id=run.id,
        window=run.window,
        tool=run.tool,
        status=RunStatus(run.status.value),
        winner_conf=run.winner_conf,
        winner_score=run.winner_score,
        ranked_candidates=ranked,
        base_candidates=bases,
        jobs=jobs,
        created_at=run.created_at,
        error_message=run.error_message,
    )


def run_to_list_item(run: OptimizationRun) -> RunListItem:
    return RunListItem(
        run_id=run.id,
        window=run.window,
        tool=run.tool,
        status=RunStatus(run.status.value),
        winner_score=run.winner_score,
        created_at=run.created_at,
    )


def worker_to_response(worker: Worker) -> WorkerResponse:
    return WorkerResponse(
        id=worker.id,
        name=worker.name,
        health_url=worker.health_url,
        base_url=worker.base_url,
        status=WorkerStatus(worker.status.value),
        capabilities=worker.capabilities or {},
        tags=worker.tags or [],
        version=worker.version,
        last_heartbeat=worker.last_heartbeat,
        created_at=worker.created_at,
    )


def history_to_response(row: RoundHistory) -> HistoryRecord:
    return HistoryRecord(
        id=row.id,
        window=row.window,
        chromosome=row.chromosome,
        start=row.start,
        end=row.end,
        tool=row.tool,
        conf=row.conf,
        score=row.score,
        run_id=row.run_id,
        created_at=row.created_at,
    )
