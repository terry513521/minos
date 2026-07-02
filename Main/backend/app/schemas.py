from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    SELECTING = "selecting"
    OPTIMIZING = "optimizing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class WorkerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    DISABLED = "disabled"


class SearchBudget(BaseModel):
    max_trials: int = 12
    timeout_seconds: int = 3600


class PolicyOverride(BaseModel):
    important_params: list[str] | None = None
    search_method: str | None = None
    search_budget: SearchBudget | None = None


class CreateRunRequest(BaseModel):
    window: str = Field(..., examples=["chr20:10000000-15000000"])
    tool: str = "gatk"
    bam_path: str | None = None
    truth_vcf_path: str | None = None
    reference_path: str | None = None
    k_candidates: int = Field(2, ge=1, le=16)
    max_workers: int = Field(2, ge=1, le=32)
    top_m: int = Field(5, ge=1, le=50)
    policy_override: PolicyOverride | None = None


class RankedCandidate(BaseModel):
    rank: int
    conf: dict[str, Any]
    score: float
    worker_id: str | None = None
    job_id: str | None = None


class BaseCandidate(BaseModel):
    index: int
    base_conf: dict[str, Any]
    rank_score: float
    history_id: str | None = None


class FindCandidatesRequest(BaseModel):
    window: str = Field(..., examples=["chr20:10000000-15000000"])
    tool: str = "gatk"
    k_candidates: int = Field(2, ge=1, le=16)
    min_similarity: float = Field(0.2, ge=0.0, le=1.0)


class CandidatePreview(BaseModel):
    index: int
    base_conf: dict[str, Any]
    rank_score: float
    history_id: str | None = None
    source_window: str | None = None
    history_score: float | None = None
    similarity: float | None = None


class FindCandidatesResponse(BaseModel):
    window: str
    chromosome: str
    tool: str
    k_candidates: int
    candidates: list[CandidatePreview]
    used_default: bool = False
    history_matched: int = 0
    coordinate_matched: int = 0
    total_history: int = 0
    ranked_pool_size: int = 0
    min_similarity: float = 0.2


class JobSummary(BaseModel):
    job_id: str
    worker_id: str | None
    candidate_index: int
    status: JobStatus
    best_score: float | None = None


class RunResponse(BaseModel):
    run_id: str
    window: str
    tool: str
    status: RunStatus
    winner_conf: dict[str, Any] | None = None
    winner_score: float | None = None
    ranked_candidates: list[RankedCandidate] = Field(default_factory=list)
    base_candidates: list[BaseCandidate] = Field(default_factory=list)
    jobs: list[JobSummary] = Field(default_factory=list)
    created_at: datetime
    error_message: str | None = None


class RunListItem(BaseModel):
    run_id: str
    window: str
    tool: str
    status: RunStatus
    winner_score: float | None = None
    created_at: datetime


class WorkerCreate(BaseModel):
    name: str
    health_url: str | None = None
    base_url: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class WorkerUpdate(BaseModel):
    health_url: str | None = None
    base_url: str | None = None
    status: WorkerStatus | None = None


class WorkerResponse(BaseModel):
    id: str
    name: str
    health_url: str | None
    base_url: str | None
    status: WorkerStatus
    capabilities: dict[str, Any]
    tags: list[str]
    version: str | None
    last_heartbeat: datetime | None
    created_at: datetime


class WorkerRegisterResponse(BaseModel):
    worker: WorkerResponse
    registration_token: str


class WorkerHealthCheckResponse(BaseModel):
    worker_id: str
    ok: bool
    status_code: int | None = None
    health: dict[str, Any] | None = None
    error: str | None = None


class WorkerTrialRecord(BaseModel):
    index: int
    label: str
    success: bool
    score: float | None = None
    raw_score: float | None = None
    cached: bool = False
    is_best: bool = False
    error: str | None = None
    completed_at: str | None = None


class WorkerBestScoreResponse(BaseModel):
    worker_id: str
    ok: bool
    status_code: int | None = None
    status: str | None = None
    job_id: str | None = None
    window: str | None = None
    tool: str | None = None
    best_score: float | None = None
    best_conf: dict[str, Any] = Field(default_factory=dict)
    trials_evaluated: int = 0
    search_space_size: int = 0
    updated_at: str | None = None
    message: str | None = None
    stop_requested: bool = False
    trials: list[WorkerTrialRecord] = Field(default_factory=list)
    error: str | None = None


class ParamIntervalSpec(BaseModel):
    min: float | None = None
    max: float | None = None
    step: float | None = None
    values: list[str] | None = None


class WorkerDispatchRequest(BaseModel):
    window: str
    tool: str
    base_conf: dict[str, Any]
    params: list[str] = Field(..., min_length=1)
    param_intervals: dict[str, ParamIntervalSpec] | None = None
    concurrency: int = Field(default=1, ge=1, le=32)
    algorithm: str = "grid"
    limit_seconds: int = Field(default=1800, ge=60, le=86400)
    candidate_index: int | None = None


class WorkerDispatchResponse(BaseModel):
    worker_id: str
    ok: bool
    status_code: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class WorkerStopResponse(BaseModel):
    worker_id: str
    ok: bool
    status_code: int | None = None
    status: str | None = None
    message: str | None = None
    error: str | None = None


class HistoryRecord(BaseModel):
    id: str
    window: str
    chromosome: str
    start: int
    end: int
    tool: str
    conf: dict[str, Any]
    score: float
    run_id: str | None = None
    created_at: datetime


class CreateHistoryRequest(BaseModel):
    window: str = Field(..., examples=["chr20:10000000-15000000"])
    tool: str = "gatk"
    conf: dict[str, Any]
    score: float = Field(..., ge=0.0, le=1.0)
    run_id: str | None = None
    worker_id: str | None = None
    source_key: str | None = None
    replace: bool = False


class HistoryImportResponse(BaseModel):
    files: int
    parsed: int
    imported: int
    skipped_unscored: int
    skipped_invalid: int
    skipped_duplicate: int


class OptimizerPolicy(BaseModel):
    tool: str
    important_params: list[str]
    search_method: str
    search_budget: SearchBudget
    param_bounds: dict[str, Any] = Field(default_factory=dict)
    k_candidates: int = 2
    top_m: int = 5
    similarity_weights: dict[str, float] = Field(
        default_factory=lambda: {"score": 0.6, "similarity": 0.4}
    )


class HealthResponse(BaseModel):
    status: str
    service: str = "effortless-control-plane"


class PlatformRoundResponse(BaseModel):
    enabled: bool
    polled_at: datetime | None = None
    error: str | None = None
    has_active_round: bool = False
    round_id: str | None = None
    status: str | None = None
    region: str | None = None
    chromosome: str | None = None
    time_remaining_seconds: int | None = None
    start_time: str | None = None
    submission_end_time: str | None = None
    scoring_end_time: str | None = None
    phase_deadline_at: str | None = None
    optimize_deadline_at: str | None = None
    num_mutations: int | None = None
    downsampled_coverage: int | None = None
    has_submitted: bool = False
    demo_mode: bool = False
    hotkey_ss58: str | None = None
