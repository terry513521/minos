from typing import Any

from pydantic import BaseModel, Field


class ParamIntervalSpec(BaseModel):
    min: float | None = None
    max: float | None = None
    step: float | None = None
    values: list[str] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    cpu_count: int
    ram_total: str
    ram_available: str


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
    best_score: float | None = None
    best_conf: dict[str, Any] = Field(default_factory=dict)
    trials_evaluated: int = 0
    search_space_size: int = 0
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
