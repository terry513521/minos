"""Persist per-worker manual tunable defaults on the control plane."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker, WorkerTunableDefaults
from app.schemas import (
    WorkerTunableBulkItem,
    WorkerTunableDefaultsListResponse,
    WorkerTunableDefaultsResponse,
    WorkerTunableProfileBody,
)

AUTO_ALGORITHMS = frozenset({"optuna", "gp", "random", "sobol", "lhs"})
TOOLKIT_OPTIONS = frozenset({"gatk", "bcftools", "deepvariant"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_tool(raw: str | None) -> str:
    tool = (raw or "gatk").lower().strip()
    return tool if tool in TOOLKIT_OPTIONS else "gatk"


def _normalize_algorithm(raw: str | None) -> str:
    algo = (raw or "optuna").lower().strip()
    return algo if algo in AUTO_ALGORITHMS else "optuna"


def normalize_profile_body(raw: WorkerTunableProfileBody | dict) -> WorkerTunableProfileBody:
    if isinstance(raw, WorkerTunableProfileBody):
        payload = raw
    else:
        payload = WorkerTunableProfileBody.model_validate(raw)

    selected_params = [param for param in payload.selected_params if param.strip()]
    if not selected_params:
        raise ValueError("selected_params must include at least one parameter")

    return WorkerTunableProfileBody(
        tool=_normalize_tool(payload.tool),
        selected_params=selected_params,
        param_intervals=payload.param_intervals,
        algorithm=_normalize_algorithm(payload.algorithm),
        concurrency=max(1, min(32, int(payload.concurrency))),
        limit_seconds=max(60, min(86400, int(payload.limit_seconds))),
        trial_threads=max(1, min(100, int(payload.trial_threads))),
        trial_memory_gb=max(4, min(128, int(payload.trial_memory_gb))),
        trial_count=max(2, min(1001, int(payload.trial_count))),
    )


def profile_to_dict(profile: WorkerTunableProfileBody) -> dict:
    return profile.model_dump(mode="json")


def profile_from_dict(raw: dict) -> WorkerTunableProfileBody:
    return normalize_profile_body(raw)


async def list_worker_tunable_defaults(
    db: AsyncSession,
) -> WorkerTunableDefaultsListResponse:
    result = await db.execute(
        select(WorkerTunableDefaults, Worker)
        .join(Worker, Worker.id == WorkerTunableDefaults.worker_id)
        .order_by(Worker.name)
    )
    items: list[WorkerTunableDefaultsResponse] = []
    for row, worker in result.all():
        items.append(
            WorkerTunableDefaultsResponse(
                worker_id=worker.id,
                worker_name=worker.name,
                profile=profile_from_dict(row.profile),
                updated_at=row.updated_at,
            )
        )
    return WorkerTunableDefaultsListResponse(items=items)


async def get_worker_tunable_defaults(
    db: AsyncSession,
    worker_id: str,
) -> WorkerTunableDefaultsResponse | None:
    result = await db.execute(
        select(WorkerTunableDefaults, Worker)
        .join(Worker, Worker.id == WorkerTunableDefaults.worker_id)
        .where(WorkerTunableDefaults.worker_id == worker_id)
    )
    row = result.first()
    if row is None:
        return None
    defaults, worker = row
    return WorkerTunableDefaultsResponse(
        worker_id=worker.id,
        worker_name=worker.name,
        profile=profile_from_dict(defaults.profile),
        updated_at=defaults.updated_at,
    )


async def _resolve_worker(
    db: AsyncSession,
    *,
    worker_id: str | None,
    worker_name: str | None,
) -> Worker:
    if worker_id:
        result = await db.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one_or_none()
        if worker is not None:
            return worker
    if worker_name and worker_name.strip():
        name = worker_name.strip()
        result = await db.execute(select(Worker).where(Worker.name == name))
        worker = result.scalar_one_or_none()
        if worker is not None:
            return worker
        lower = name.lower()
        result = await db.execute(select(Worker))
        for candidate in result.scalars().all():
            if candidate.name.lower() == lower:
                return candidate
    raise ValueError("Worker not found")


async def save_worker_tunable_defaults(
    db: AsyncSession,
    worker_id: str,
    profile: WorkerTunableProfileBody,
    *,
    commit: bool = True,
) -> WorkerTunableDefaultsResponse:
    worker_result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = worker_result.scalar_one_or_none()
    if worker is None:
        raise ValueError("Worker not found")

    normalized = normalize_profile_body(profile)
    result = await db.execute(
        select(WorkerTunableDefaults).where(WorkerTunableDefaults.worker_id == worker_id)
    )
    row = result.scalar_one_or_none()
    now = _utcnow()
    payload = profile_to_dict(normalized)
    if row is None:
        row = WorkerTunableDefaults(worker_id=worker_id, profile=payload, updated_at=now)
        db.add(row)
    else:
        row.profile = payload
        row.updated_at = now
    if commit:
        await db.commit()
        await db.refresh(row)
    return WorkerTunableDefaultsResponse(
        worker_id=worker.id,
        worker_name=worker.name,
        profile=normalized,
        updated_at=row.updated_at,
    )


async def bulk_save_worker_tunable_defaults(
    db: AsyncSession,
    items: list[WorkerTunableBulkItem],
) -> WorkerTunableDefaultsListResponse:
    saved: list[WorkerTunableDefaultsResponse] = []
    for item in items:
        worker = await _resolve_worker(
            db,
            worker_id=item.worker_id,
            worker_name=item.worker_name,
        )
        saved.append(
            await save_worker_tunable_defaults(db, worker.id, item.profile, commit=False)
        )
    await db.commit()
    return WorkerTunableDefaultsListResponse(items=saved)
