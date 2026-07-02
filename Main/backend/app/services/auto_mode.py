"""Overnight auto-mode orchestration for VM / Big / Igno workers."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker
from app.schemas import (
    AutoBestResponse,
    AutoDispatchAssignment,
    AutoModeConfig,
    AutoModeStatus,
    AutoSelectedCandidate,
    AutoStartResponse,
    CandidatePreview,
    ParamIntervalSpec,
    WorkerDispatchRequest,
)
from app.selector import parse_window
from app.services.candidate_finder import find_candidates
from app.services.worker_proxy import dispatch_to_worker, fetch_worker_best, stop_worker_optimization

AUTO_WORKER_NAMES: tuple[str, ...] = ("VM", "Big", "Igno")
AUTO_WORKER_ALGORITHMS: dict[str, str] = {
    "VM": "optuna",
    "Big": "optuna",
    "Igno": "random",
}
AUTO_FIND_K = 6
AUTO_SELECT_K = 3
AUTO_LIMIT_SECONDS = 45 * 60
AUTO_SCORE_WEIGHT = 0.4
AUTO_SIMILARITY_WEIGHT = 0.6
AUTO_CONCURRENCY = 2
AUTO_TOOL = "gatk"
AUTO_PARAMS = [
    "standard_min_confidence_threshold_for_calling",
    "contamination_fraction_to_filter",
    "base_quality_score_threshold",
]
AUTO_PARAM_INTERVALS: dict[str, ParamIntervalSpec] = {
    "standard_min_confidence_threshold_for_calling": ParamIntervalSpec(
        min=25.0, max=35.0, step=0.2
    ),
    "contamination_fraction_to_filter": ParamIntervalSpec(
        min=0.18, max=0.28, step=0.00001
    ),
    "base_quality_score_threshold": ParamIntervalSpec(min=25.0, max=31.0, step=1.0),
}


@dataclass
class AutoSession:
    region: str
    tool: str
    started_at: datetime
    assignments: list[AutoDispatchAssignment] = field(default_factory=list)
    selected_candidates: list[CandidatePreview] = field(default_factory=list)
    candidates_found: int = 0
    running: bool = True


def auto_mode_config() -> AutoModeConfig:
    return AutoModeConfig(
        tool=AUTO_TOOL,
        params=list(AUTO_PARAMS),
        param_intervals=dict(AUTO_PARAM_INTERVALS),
        worker_names=list(AUTO_WORKER_NAMES),
        worker_algorithms=dict(AUTO_WORKER_ALGORITHMS),
        limit_seconds=AUTO_LIMIT_SECONDS,
        concurrency=AUTO_CONCURRENCY,
        find_k=AUTO_FIND_K,
        select_k=AUTO_SELECT_K,
        score_weight=AUTO_SCORE_WEIGHT,
        similarity_weight=AUTO_SIMILARITY_WEIGHT,
    )


def _selected_candidate_models(candidates: list[CandidatePreview]) -> list[AutoSelectedCandidate]:
    return [
        AutoSelectedCandidate(
            index=candidate.index,
            composite_score=composite_candidate_score(candidate),
            history_score=candidate.history_score,
            similarity=candidate.similarity,
            base_conf=candidate.base_conf,
        )
        for candidate in candidates
    ]


class AutoModeStore:
    def __init__(self) -> None:
        self.enabled = False
        self.session: AutoSession | None = None

    def status(self) -> AutoModeStatus:
        session = self.session
        return AutoModeStatus(
            enabled=self.enabled,
            running=bool(session and session.running),
            region=session.region if session else None,
            started_at=session.started_at if session else None,
            config=auto_mode_config(),
            candidates_found=session.candidates_found if session else 0,
            selected_candidates=(
                _selected_candidate_models(session.selected_candidates) if session else []
            ),
            assignments=list(session.assignments) if session else [],
        )

    def set_enabled(self, enabled: bool) -> AutoModeStatus:
        self.enabled = enabled
        if not enabled:
            if self.session:
                self.session.running = False
        return self.status()


auto_mode_store = AutoModeStore()


def composite_candidate_score(candidate: CandidatePreview) -> float:
    score = candidate.history_score if candidate.history_score is not None else candidate.rank_score
    similarity = candidate.similarity if candidate.similarity is not None else 0.0
    return AUTO_SCORE_WEIGHT * float(score) + AUTO_SIMILARITY_WEIGHT * float(similarity)


def select_top_candidates(candidates: list[CandidatePreview], k: int) -> list[CandidatePreview]:
    ranked = sorted(candidates, key=composite_candidate_score, reverse=True)
    selected = ranked[:k]
    if not selected:
        return []
    while len(selected) < k:
        selected.append(selected[-1])
    return selected


async def resolve_workers_by_name(db: AsyncSession, names: tuple[str, ...]) -> dict[str, Worker]:
    result = await db.execute(select(Worker))
    by_lower = {worker.name.lower(): worker for worker in result.scalars().all()}
    resolved: dict[str, Worker] = {}
    missing: list[str] = []
    for name in names:
        worker = by_lower.get(name.lower())
        if worker is None:
            missing.append(name)
        else:
            resolved[name] = worker
    if missing:
        raise ValueError(f"Workers not registered: {', '.join(missing)}")
    return resolved


def build_dispatch_request(
    *,
    window: str,
    tool: str,
    base_conf: dict[str, Any],
    algorithm: str,
    candidate_index: int,
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        window=window,
        tool=tool,
        base_conf=base_conf,
        params=list(AUTO_PARAMS),
        param_intervals=dict(AUTO_PARAM_INTERVALS),
        concurrency=AUTO_CONCURRENCY,
        algorithm=algorithm,
        limit_seconds=AUTO_LIMIT_SECONDS,
        candidate_index=candidate_index,
    )


async def start_auto_mode(
    db: AsyncSession,
    *,
    region: str,
    tool: str = AUTO_TOOL,
) -> AutoStartResponse:
    if not auto_mode_store.enabled:
        raise ValueError("Auto mode is disabled")

    if auto_mode_store.session and auto_mode_store.session.running:
        raise ValueError("Auto mode session already running")

    parsed = parse_window(region)
    window = parsed.window

    find_result = await find_candidates(
        db,
        window=window,
        tool=tool,
        k_candidates=AUTO_FIND_K,
    )
    if not find_result.candidates:
        raise ValueError("No candidates found for region")

    selected = select_top_candidates(find_result.candidates, AUTO_SELECT_K)
    workers = await resolve_workers_by_name(db, AUTO_WORKER_NAMES)

    shuffled = list(selected)
    random.shuffle(shuffled)

    assignments: list[AutoDispatchAssignment] = []
    dispatch_results: list[AutoDispatchAssignment] = []

    for worker_name, candidate in zip(AUTO_WORKER_NAMES, shuffled, strict=True):
        worker = workers[worker_name]
        algorithm = AUTO_WORKER_ALGORITHMS[worker_name]
        dispatch_body = build_dispatch_request(
            window=window,
            tool=tool,
            base_conf=candidate.base_conf,
            algorithm=algorithm,
            candidate_index=candidate.index,
        )
        response = await dispatch_to_worker(db, worker.id, dispatch_body)
        assignment = AutoDispatchAssignment(
            worker_id=worker.id,
            worker_name=worker_name,
            algorithm=algorithm,
            candidate_index=candidate.index,
            composite_score=composite_candidate_score(candidate),
            history_score=candidate.history_score,
            similarity=candidate.similarity,
            base_conf=candidate.base_conf,
            window=window,
            params=list(AUTO_PARAMS),
            param_intervals=dict(AUTO_PARAM_INTERVALS),
            concurrency=AUTO_CONCURRENCY,
            limit_seconds=AUTO_LIMIT_SECONDS,
            dispatch_ok=response.ok,
            dispatch_error=response.error,
            job_id=(response.result or {}).get("job_id") if response.result else None,
        )
        assignments.append(assignment)
        dispatch_results.append(assignment)

    auto_mode_store.session = AutoSession(
        region=window,
        tool=tool,
        started_at=datetime.now(timezone.utc),
        assignments=assignments,
        selected_candidates=selected,
        candidates_found=len(find_result.candidates),
        running=True,
    )

    ok_count = sum(1 for item in dispatch_results if item.dispatch_ok)
    return AutoStartResponse(
        ok=ok_count > 0,
        region=window,
        tool=tool,
        candidates_found=len(find_result.candidates),
        candidates_selected=len(selected),
        workers_dispatched=ok_count,
        assignments=dispatch_results,
        message=(
            f"Auto mode started: {ok_count}/{len(AUTO_WORKER_NAMES)} workers dispatched"
            if ok_count
            else "Auto mode failed: no workers accepted dispatch"
        ),
    )


async def collect_best_and_stop(db: AsyncSession) -> AutoBestResponse:
    session = auto_mode_store.session
    worker_ids: list[str]
    if session and session.assignments:
        worker_ids = [item.worker_id for item in session.assignments]
    else:
        workers = await resolve_workers_by_name(db, AUTO_WORKER_NAMES)
        worker_ids = [workers[name].id for name in AUTO_WORKER_NAMES]

    best_entries: list[tuple[str, str, float, dict[str, Any]]] = []
    stop_results: list[dict[str, Any]] = []

    for worker_id in worker_ids:
        best = await fetch_worker_best(db, worker_id)
        stop = await stop_worker_optimization(db, worker_id)
        stop_results.append(
            {
                "worker_id": worker_id,
                "ok": stop.ok,
                "message": stop.message,
                "error": stop.error,
            }
        )
        if best.ok and best.best_score is not None and best.best_conf:
            worker_name = next(
                (a.worker_name for a in (session.assignments if session else []) if a.worker_id == worker_id),
                worker_id[:8],
            )
            best_entries.append((worker_id, worker_name, float(best.best_score), best.best_conf))

    if session:
        session.running = False

    if not best_entries:
        return AutoBestResponse(
            ok=False,
            best_score=None,
            best_conf={},
            worker_id=None,
            worker_name=None,
            stopped_workers=stop_results,
            message="No worker returned a best score",
        )

    winner = max(best_entries, key=lambda row: row[2])
    worker_id, worker_name, best_score, best_conf = winner
    return AutoBestResponse(
        ok=True,
        best_score=best_score,
        best_conf=best_conf,
        worker_id=worker_id,
        worker_name=worker_name,
        stopped_workers=stop_results,
        message=f"Best conf from {worker_name} (score {best_score:.4f})",
    )
