from typing import Any

from pydantic import BaseModel, Field


class ParamIntervalSpec(BaseModel):
    min: float | None = None
    max: float | None = None
    step: float | None = None
    delta: float | None = None
    values: list[str] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    cpu_count: int
    ram_total: str
    ram_available: str
    data_dir: str | None = None
    giab_ready: bool | None = None
    giab_message: str | None = None


class TrialScoreEntry(BaseModel):
    index: int
    label: str
    success: bool
    score: float | None = None
    raw_score: float | None = None
    cached: bool = False
    error: str | None = None
    is_best: bool = False
    recorded_at: str | None = None


class BestScoreResponse(BaseModel):
    status: str
    worker: str
    job_id: str | None = None
    window: str | None = None
    tool: str | None = None
    algorithm: str | None = None
    concurrency: int | None = None
    limit_seconds: int | None = None
    adaptive_max_trials: int | None = None
    params: list[str] = Field(default_factory=list)
    trial_threads: int | None = None
    trial_memory_gb: int | None = None
    benchmark_window: str | None = None
    best_score: float | None = None
    best_conf: dict[str, Any] = Field(default_factory=dict)
    trials_evaluated: int = 0
    search_space_size: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    message: str | None = None
    trials: list[TrialScoreEntry] = Field(default_factory=list)


class OptimizeRequest(BaseModel):
    job_id: str
    window: str
    tool: str
    concurrency: str
    algorithm: str
    limit: str
    base_conf: dict[str, Any] = Field(default_factory=dict)
    params: list[str] = Field(
        ...,
        min_length=1,
        description="Conf parameter names to tune inside {tool}_options, e.g. pcr_indel_model",
    )
    param_intervals: dict[str, ParamIntervalSpec] | None = Field(
        default=None,
        description="Optional per-parameter min/max/step or enum values for this worker's search slice",
    )
    adaptive_max_trials: int | None = Field(
        default=None,
        ge=0,
        le=1000,
        description="Override worker default: adaptive trials after base benchmark (0 = base only)",
    )
    include_base_benchmark: bool = Field(
        default=True,
        description="When true, score base conf once before search trials",
    )
    delta_rounds: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Delta algorithm only: refinement rounds around current best (±delta per param)",
    )


class OptimizeResponse(BaseModel):
    status: str
    worker: str
    job_id: str
    window: str
    tool: str
    concurrency: str
    algorithm: str
    limit: str
    params: list[str]
    search_space_size: int
    trials_evaluated: int = 0
    best_score: float | None = None
    best_conf: dict[str, Any] = Field(default_factory=dict)
    message: str


class StopResponse(BaseModel):
    status: str
    worker: str
    message: str


class BenchmarkRequest(BaseModel):
    window: str
    tool: str
    conf: dict[str, Any] = Field(default_factory=dict)


class BenchmarkResponse(BaseModel):
    success: bool
    window: str
    tool: str
    score: float | None = None
    raw_score: float | None = None
    variant_count: int = 0
    cached: bool = False
    error: str | None = None


class SeedBatchItem(BaseModel):
    source_id: str
    source_key: str
    source_window: str | None = None
    target_window: str
    tool: str
    conf: dict[str, Any] = Field(default_factory=dict)


class SeedBatchRequest(BaseModel):
    batch_id: str | None = None
    items: list[SeedBatchItem] = Field(default_factory=list)


class SeedBatchResponse(BaseModel):
    batch_id: str
    queued: int
    skipped_duplicate: int
    status: str


class SeedStatusResponse(BaseModel):
    status: str
    batch_id: str | None = None
    total: int = 0
    pending: int = 0
    running: int = 0
    scored: int = 0
    failed: int = 0
    updated_at: str | None = None


class SeedResultItem(BaseModel):
    seed_id: str | None = None
    source_id: str | None = None
    source_key: str
    source_window: str | None = None
    target_window: str
    tool: str
    conf: dict[str, Any] = Field(default_factory=dict)
    status: str
    success: bool = False
    score: float | None = None
    raw_score: float | None = None
    variant_count: int = 0
    cached: bool = False
    error: str | None = None
    batch_id: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SeedResultsResponse(BaseModel):
    results: list[SeedResultItem] = Field(default_factory=list)
