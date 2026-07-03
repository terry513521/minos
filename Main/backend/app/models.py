import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    SELECTING = "selecting"
    OPTIMIZING = "optimizing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    DISABLED = "disabled"


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    health_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[WorkerStatus] = mapped_column(Enum(WorkerStatus), default=WorkerStatus.OFFLINE)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    window: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    chromosome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool: Mapped[str] = mapped_column(String(32), default="gatk")
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.QUEUED)
    k_candidates: Mapped[int] = mapped_column(Integer, default=2)
    top_m: Mapped[int] = mapped_column(Integer, default=5)
    winner_conf: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    winner_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ranked_candidates: Mapped[list] = mapped_column(JSON, default=list)
    base_candidates: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    jobs: Mapped[list["OptimizationJob"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class OptimizationJob(Base):
    __tablename__ = "optimization_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("optimization_runs.id"), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workers.id"), nullable=True)
    candidate_index: Mapped[int] = mapped_column(Integer, default=0)
    base_conf: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    best_conf: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trials: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["OptimizationRun"] = relationship(back_populates="jobs")


class RoundHistory(Base):
    __tablename__ = "round_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chromosome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    window: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(32), default="gatk")
    conf: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ControlPlaneSetting(Base):
    __tablename__ = "control_plane_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class AutoModeRound(Base):
    """One auto-mode optimization round with per-worker best scores."""

    __tablename__ = "auto_mode_rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    chromosome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool: Mapped[str] = mapped_column(String(32), default="gatk")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    end_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    winner_worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    winner_worker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    winner_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    winner_conf: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    worker_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkerTunableDefaults(Base):
    """Per-worker manual tunable defaults (params, intervals, runtime settings)."""

    __tablename__ = "worker_tunable_defaults"

    worker_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
