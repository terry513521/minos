"""Overnight auto-mode orchestration for VM / Big / Igno workers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

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
from app.services.candidate_finder import load_history_entries, scored_pool_to_previews
from app.engine.candidate_finder import CandidateFinderEngine
from app.defaults import default_tool_conf
from app.services.control_plane_settings import (
    AUTO_MODE_TUNABLE_CONFIG_KEY,
    LAST_AUTO_START_REGION_KEY,
    get_control_plane_setting,
    set_control_plane_setting,
)
from app.services.worker_proxy import dispatch_to_worker, fetch_worker_best, stop_worker_optimization

SelectionReason = Literal["top_score", "most_similar", "best_composite"]

AUTO_ASSIGNMENT_STRATEGY = "score_similarity_composite"
AUTO_WORKER_NAMES: tuple[str, ...] = ("VM", "Big", "Igno")
WORKER_SELECTION_RULES: tuple[tuple[str, SelectionReason], ...] = (
    ("VM", "top_score"),
    ("Big", "most_similar"),
    ("Igno", "best_composite"),
)
AUTO_ALGORITHM = "optuna"
AUTO_ALGORITHMS: frozenset[str] = frozenset({"optuna", "gp", "random", "sobol", "lhs"})
AUTO_FIND_K = 6
AUTO_SELECT_K = 3
AUTO_LIMIT_SECONDS = 50 * 60
AUTO_ADAPTIVE_MAX_TRIALS = 44
AUTO_SCORE_WEIGHT = 0.4
AUTO_SIMILARITY_WEIGHT = 0.6
AUTO_CONCURRENCY = 1
AUTO_TRIAL_THREADS = 4
AUTO_TRIAL_MEMORY_GB = 6
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
class AutoModeTunableConfig:
    params: list[str]
    param_intervals: dict[str, ParamIntervalSpec]
    worker_algorithms: dict[str, str] = field(default_factory=dict)
    worker_trial_threads: dict[str, int] = field(default_factory=dict)
    worker_trial_memory_gb: dict[str, int] = field(default_factory=dict)


def default_worker_algorithms() -> dict[str, str]:
    return {name: AUTO_ALGORITHM for name in AUTO_WORKER_NAMES}


def default_worker_trial_threads() -> dict[str, int]:
    return {name: AUTO_TRIAL_THREADS for name in AUTO_WORKER_NAMES}


def default_worker_trial_memory_gb() -> dict[str, int]:
    return {name: AUTO_TRIAL_MEMORY_GB for name in AUTO_WORKER_NAMES}


def default_auto_tunable_config() -> AutoModeTunableConfig:
    return AutoModeTunableConfig(
        params=list(AUTO_PARAMS),
        param_intervals=dict(AUTO_PARAM_INTERVALS),
        worker_algorithms=default_worker_algorithms(),
        worker_trial_threads=default_worker_trial_threads(),
        worker_trial_memory_gb=default_worker_trial_memory_gb(),
    )


def _tunable_config_to_json(config: AutoModeTunableConfig) -> str:
    return json.dumps(
        {
            "params": config.params,
            "param_intervals": {
                name: spec.model_dump(exclude_none=True)
                for name, spec in config.param_intervals.items()
            },
            "worker_algorithms": dict(config.worker_algorithms),
            "worker_trial_threads": dict(config.worker_trial_threads),
            "worker_trial_memory_gb": dict(config.worker_trial_memory_gb),
        }
    )


def _tunable_config_from_json(raw: str) -> AutoModeTunableConfig:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("auto_mode_tunable_config must be a JSON object")
    params = payload.get("params")
    intervals_raw = payload.get("param_intervals")
    if not isinstance(params, list) or not params:
        raise ValueError("auto_mode_tunable_config.params must be a non-empty list")
    if not isinstance(intervals_raw, dict):
        raise ValueError("auto_mode_tunable_config.param_intervals must be an object")
    intervals = {
        str(name): ParamIntervalSpec(**spec)
        for name, spec in intervals_raw.items()
        if isinstance(spec, dict)
    }
    worker_algorithms_raw = payload.get("worker_algorithms")
    worker_algorithms = default_worker_algorithms()
    if isinstance(worker_algorithms_raw, dict):
        for name, algorithm in worker_algorithms_raw.items():
            if isinstance(name, str) and isinstance(algorithm, str) and name in AUTO_WORKER_NAMES:
                worker_algorithms[name] = algorithm.strip().lower()
    worker_trial_threads = default_worker_trial_threads()
    threads_raw = payload.get("worker_trial_threads")
    if isinstance(threads_raw, dict):
        for name, threads in threads_raw.items():
            if isinstance(name, str) and name in AUTO_WORKER_NAMES:
                try:
                    worker_trial_threads[name] = clamp_trial_threads(int(threads))
                except (TypeError, ValueError):
                    pass
    worker_trial_memory_gb = default_worker_trial_memory_gb()
    memory_raw = payload.get("worker_trial_memory_gb")
    if isinstance(memory_raw, dict):
        for name, memory_gb in memory_raw.items():
            if isinstance(name, str) and name in AUTO_WORKER_NAMES:
                try:
                    worker_trial_memory_gb[name] = clamp_trial_memory_gb(int(memory_gb))
                except (TypeError, ValueError):
                    pass
    return AutoModeTunableConfig(
        params=[str(p) for p in params],
        param_intervals=intervals,
        worker_algorithms=worker_algorithms,
        worker_trial_threads=worker_trial_threads,
        worker_trial_memory_gb=worker_trial_memory_gb,
    )


def validate_auto_tunable_config(config: AutoModeTunableConfig) -> None:
    if not config.params:
        raise ValueError("At least one tunable parameter is required")
    for param in config.params:
        if param not in config.param_intervals:
            raise ValueError(f"Missing search interval for parameter: {param}")
    validate_worker_algorithms(config.worker_algorithms)
    validate_worker_trial_resources(
        config.worker_trial_threads,
        config.worker_trial_memory_gb,
    )


def validate_worker_algorithms(worker_algorithms: dict[str, str]) -> None:
    for worker_name in AUTO_WORKER_NAMES:
        algorithm = worker_algorithms.get(worker_name, AUTO_ALGORITHM)
        if algorithm not in AUTO_ALGORITHMS:
            raise ValueError(
                f"Unsupported algorithm for {worker_name}: {algorithm!r} "
                f"(use {', '.join(sorted(AUTO_ALGORITHMS))})"
            )


def clamp_trial_threads(value: int) -> int:
    return max(1, min(32, int(value)))


def clamp_trial_memory_gb(value: int) -> int:
    return max(4, min(128, int(value)))


def validate_worker_trial_resources(
    worker_trial_threads: dict[str, int],
    worker_trial_memory_gb: dict[str, int],
) -> None:
    for worker_name in AUTO_WORKER_NAMES:
        threads = worker_trial_threads.get(worker_name, AUTO_TRIAL_THREADS)
        memory_gb = worker_trial_memory_gb.get(worker_name, AUTO_TRIAL_MEMORY_GB)
        if threads != clamp_trial_threads(threads):
            raise ValueError(f"CPUs per trial for {worker_name} must be between 1 and 32")
        if memory_gb != clamp_trial_memory_gb(memory_gb):
            raise ValueError(f"RAM per trial for {worker_name} must be between 4 and 128 GB")


def effective_worker_algorithms() -> dict[str, str]:
    stored = auto_mode_store.tunable.worker_algorithms
    return {name: stored.get(name, AUTO_ALGORITHM) for name in AUTO_WORKER_NAMES}


def effective_worker_trial_threads() -> dict[str, int]:
    stored = auto_mode_store.tunable.worker_trial_threads
    return {name: clamp_trial_threads(stored.get(name, AUTO_TRIAL_THREADS)) for name in AUTO_WORKER_NAMES}


def effective_worker_trial_memory_gb() -> dict[str, int]:
    stored = auto_mode_store.tunable.worker_trial_memory_gb
    return {
        name: clamp_trial_memory_gb(stored.get(name, AUTO_TRIAL_MEMORY_GB))
        for name in AUTO_WORKER_NAMES
    }


def effective_auto_params() -> list[str]:
    return list(auto_mode_store.tunable.params)


def effective_auto_param_intervals() -> dict[str, ParamIntervalSpec]:
    return dict(auto_mode_store.tunable.param_intervals)


@dataclass
class SelectedCandidateSlot:
    worker_name: str
    candidate: CandidatePreview
    selection_reason: SelectionReason = "top_score"


@dataclass
class AutoSession:
    region: str
    tool: str
    started_at: datetime
    assignments: list[AutoDispatchAssignment] = field(default_factory=list)
    selected_candidates: list[SelectedCandidateSlot] = field(default_factory=list)
    found_candidates: list[CandidatePreview] = field(default_factory=list)
    candidates_found: int = 0
    running: bool = True


def auto_mode_config() -> AutoModeConfig:
    tunable = auto_mode_store.tunable
    return AutoModeConfig(
        tool=AUTO_TOOL,
        params=list(tunable.params),
        param_intervals=dict(tunable.param_intervals),
        worker_names=list(AUTO_WORKER_NAMES),
        worker_algorithms=effective_worker_algorithms(),
        worker_trial_threads=effective_worker_trial_threads(),
        worker_trial_memory_gb=effective_worker_trial_memory_gb(),
        assignment_strategy=AUTO_ASSIGNMENT_STRATEGY,
        limit_seconds=AUTO_LIMIT_SECONDS,
        adaptive_max_trials=AUTO_ADAPTIVE_MAX_TRIALS,
        concurrency=AUTO_CONCURRENCY,
        find_k=AUTO_FIND_K,
        select_k=AUTO_SELECT_K,
        score_weight=AUTO_SCORE_WEIGHT,
        similarity_weight=AUTO_SIMILARITY_WEIGHT,
    )


def _selected_candidate_models(slots: list[SelectedCandidateSlot]) -> list[AutoSelectedCandidate]:
    return [
        AutoSelectedCandidate(
            index=slot.candidate.index,
            worker_name=slot.worker_name,
            selection_reason=slot.selection_reason,
            composite_score=composite_candidate_score(slot.candidate),
            history_score=slot.candidate.history_score,
            similarity=slot.candidate.similarity,
            source_window=slot.candidate.source_window,
            base_conf=slot.candidate.base_conf,
        )
        for slot in slots
    ]


class AutoModeStore:
    def __init__(self) -> None:
        self.enabled = False
        self.session: AutoSession | None = None
        self.last_started_region: str | None = None
        self.tunable: AutoModeTunableConfig = default_auto_tunable_config()

    def status(self) -> AutoModeStatus:
        session = self.session
        _end_session_if_time_limit_reached(session)
        time_remaining_seconds = None
        if session and session.running:
            time_remaining_seconds = _session_time_remaining_seconds(session)
        return AutoModeStatus(
            enabled=self.enabled,
            running=bool(session and session.running),
            region=session.region if session else None,
            last_started_region=self.last_started_region,
            started_at=session.started_at if session else None,
            config=auto_mode_config(),
            candidates_found=session.candidates_found if session else 0,
            found_candidates=list(session.found_candidates) if session else [],
            time_remaining_seconds=time_remaining_seconds,
            limit_seconds=AUTO_LIMIT_SECONDS if session else None,
            selected_candidates=(
                _selected_candidate_models(session.selected_candidates) if session else []
            ),
            assignments=list(session.assignments) if session else [],
        )

    def set_enabled(self, enabled: bool) -> AutoModeStatus:
        """Arm or disarm auto mode. Does not start or stop worker optimizations."""
        self.enabled = enabled
        return self.status()

    def end_session(self) -> AutoModeStatus:
        """Clear in-memory auto session so a new /auto/start can run."""
        self.session = None
        self.last_started_region = None
        return self.status()

    def set_tunable(self, config: AutoModeTunableConfig) -> AutoModeStatus:
        validate_auto_tunable_config(config)
        self.tunable = AutoModeTunableConfig(
            params=list(config.params),
            param_intervals=dict(config.param_intervals),
            worker_algorithms=dict(config.worker_algorithms),
            worker_trial_threads=dict(config.worker_trial_threads),
            worker_trial_memory_gb=dict(config.worker_trial_memory_gb),
        )
        return self.status()


auto_mode_store = AutoModeStore()


async def load_auto_mode_state(db: AsyncSession) -> None:
    """Load persisted auto-mode settings from SQLite."""
    auto_mode_store.last_started_region = await get_control_plane_setting(
        db, LAST_AUTO_START_REGION_KEY
    )
    raw_tunable = await get_control_plane_setting(db, AUTO_MODE_TUNABLE_CONFIG_KEY)
    if raw_tunable:
        try:
            auto_mode_store.tunable = _tunable_config_from_json(raw_tunable)
            validate_auto_tunable_config(auto_mode_store.tunable)
        except (ValueError, TypeError, json.JSONDecodeError):
            auto_mode_store.tunable = default_auto_tunable_config()


async def update_auto_mode_tunable_config(
    db: AsyncSession,
    *,
    params: list[str],
    param_intervals: dict[str, ParamIntervalSpec],
    worker_algorithms: dict[str, str] | None = None,
    worker_trial_threads: dict[str, int] | None = None,
    worker_trial_memory_gb: dict[str, int] | None = None,
) -> AutoModeStatus:
    if auto_mode_store.session and auto_mode_store.session.running:
        raise ValueError("Cannot edit tunable parameters while an auto session is running")
    algorithms = (
        dict(worker_algorithms)
        if worker_algorithms is not None
        else dict(auto_mode_store.tunable.worker_algorithms)
    )
    trial_threads = (
        dict(worker_trial_threads)
        if worker_trial_threads is not None
        else dict(auto_mode_store.tunable.worker_trial_threads)
    )
    trial_memory_gb = (
        dict(worker_trial_memory_gb)
        if worker_trial_memory_gb is not None
        else dict(auto_mode_store.tunable.worker_trial_memory_gb)
    )
    config = AutoModeTunableConfig(
        params=list(params),
        param_intervals=dict(param_intervals),
        worker_algorithms=algorithms,
        worker_trial_threads=trial_threads,
        worker_trial_memory_gb=trial_memory_gb,
    )
    validate_auto_tunable_config(config)
    status = auto_mode_store.set_tunable(config)
    await set_control_plane_setting(db, AUTO_MODE_TUNABLE_CONFIG_KEY, _tunable_config_to_json(config))
    return status


def _skipped_start_response(*, region: str, tool: str, message: str) -> AutoStartResponse:
    return AutoStartResponse(
        ok=False,
        skipped=True,
        region=region,
        tool=tool,
        candidates_found=0,
        candidates_selected=0,
        workers_dispatched=0,
        message=message,
    )


def candidate_history_score(candidate: CandidatePreview) -> float:
    if candidate.history_score is not None:
        return float(candidate.history_score)
    return float(candidate.rank_score)


def composite_candidate_score(candidate: CandidatePreview) -> float:
    similarity = candidate.similarity if candidate.similarity is not None else 0.0
    return AUTO_SCORE_WEIGHT * candidate_history_score(candidate) + AUTO_SIMILARITY_WEIGHT * float(
        similarity
    )


def candidate_similarity_score(candidate: CandidatePreview) -> float:
    return float(candidate.similarity) if candidate.similarity is not None else -1.0


def _candidate_identity(candidate: CandidatePreview) -> str:
    return candidate.history_id or f"index:{candidate.index}"


def _reindex_candidate(index: int, candidate: CandidatePreview) -> CandidatePreview:
    return candidate.model_copy(update={"index": index})


def build_diverse_candidate_pool(
    pool: list[CandidatePreview],
    k: int,
) -> list[CandidatePreview]:
    """Build found-candidate pool: top score, most similar, best composite, then fill."""
    if not pool or k <= 0:
        return []

    picks: list[CandidatePreview] = []
    used: set[str] = set()

    def add_best(
        score_fn: Callable[[CandidatePreview], float],
        *,
        allow_reuse: bool = False,
    ) -> None:
        available = pool if allow_reuse else [row for row in pool if _candidate_identity(row) not in used]
        if not available:
            return
        best = max(available, key=score_fn)
        identity = _candidate_identity(best)
        if identity in used:
            return
        picks.append(best)
        used.add(identity)

    add_best(candidate_history_score)
    add_best(candidate_similarity_score)
    add_best(composite_candidate_score)

    for candidate in sorted(pool, key=composite_candidate_score, reverse=True):
        if len(picks) >= k:
            break
        identity = _candidate_identity(candidate)
        if identity in used:
            continue
        picks.append(candidate)
        used.add(identity)

    return [_reindex_candidate(i, candidate) for i, candidate in enumerate(picks[:k])]


async def find_auto_candidate_pool(
    db: AsyncSession,
    *,
    window: str,
    tool: str,
    k: int = AUTO_FIND_K,
) -> list[CandidatePreview]:
    parsed = parse_window(window)
    tool_key = tool.lower().strip()
    history = await load_history_entries(db, tool=tool_key)
    engine = CandidateFinderEngine()
    result = engine.find(parsed, history, tool=tool_key, n=k)

    if result.ranked_pool:
        pool = build_diverse_candidate_pool(scored_pool_to_previews(result.ranked_pool), k)
        if pool:
            return pool

    return [
        CandidatePreview(
            index=0,
            base_conf=default_tool_conf(tool_key),
            rank_score=0.0,
            history_id=None,
            source_window=None,
            history_score=None,
            similarity=None,
        )
    ]


def assign_workers_by_metric(
    candidates: list[CandidatePreview],
    worker_names: tuple[str, ...] = AUTO_WORKER_NAMES,
) -> list[SelectedCandidateSlot]:
    """Assign VM/Big/Igno to top score, most similar, and best composite confs."""
    if not candidates or not worker_names:
        return []

    score_fns: dict[SelectionReason, Callable[[CandidatePreview], float]] = {
        "top_score": candidate_history_score,
        "most_similar": candidate_similarity_score,
        "best_composite": composite_candidate_score,
    }

    used_indices: set[int] = set()
    slots: list[SelectedCandidateSlot] = []

    for worker_name, reason in WORKER_SELECTION_RULES:
        if worker_name not in worker_names:
            continue
        score_fn = score_fns[reason]
        available = [candidate for candidate in candidates if candidate.index not in used_indices]
        if not available:
            available = list(candidates)
        pick = max(available, key=score_fn)
        used_indices.add(pick.index)
        slots.append(
            SelectedCandidateSlot(
                worker_name=worker_name,
                candidate=pick,
                selection_reason=reason,
            )
        )

    return slots


def select_top_candidates(candidates: list[CandidatePreview], k: int) -> list[CandidatePreview]:
    """Legacy helper — top-k by composite score."""
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


def candidate_dispatch_window(candidate: CandidatePreview, fallback: str) -> str:
    """Use the candidate's historical region when available, not the query round region."""
    source = (candidate.source_window or "").strip()
    if not source:
        return fallback
    try:
        return parse_window(source).window
    except ValueError:
        return fallback


def with_trial_resources(
    base_conf: dict[str, Any],
    *,
    trial_threads: int = AUTO_TRIAL_THREADS,
    trial_memory_gb: int = AUTO_TRIAL_MEMORY_GB,
) -> dict[str, Any]:
    """Attach per-trial Docker CPU/RAM for GATK benchmarks."""
    merged = dict(base_conf)
    merged["threads"] = clamp_trial_threads(trial_threads)
    merged["memory_gb"] = clamp_trial_memory_gb(trial_memory_gb)
    return merged


def build_dispatch_request(
    *,
    window: str,
    tool: str,
    base_conf: dict[str, Any],
    candidate_index: int,
    algorithm: str = AUTO_ALGORITHM,
    trial_threads: int = AUTO_TRIAL_THREADS,
    trial_memory_gb: int = AUTO_TRIAL_MEMORY_GB,
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        window=window,
        tool=tool,
        base_conf=with_trial_resources(
            base_conf,
            trial_threads=trial_threads,
            trial_memory_gb=trial_memory_gb,
        ),
        params=effective_auto_params(),
        param_intervals=effective_auto_param_intervals(),
        concurrency=AUTO_CONCURRENCY,
        algorithm=algorithm,
        limit_seconds=AUTO_LIMIT_SECONDS,
        adaptive_max_trials=AUTO_ADAPTIVE_MAX_TRIALS,
        candidate_index=candidate_index,
    )


async def stop_all_auto_workers(db: AsyncSession) -> list[dict[str, Any]]:
    """Stop optimization on every auto-mode worker (VM / Big / Igno)."""
    workers = await resolve_workers_by_name(db, AUTO_WORKER_NAMES)
    stop_results: list[dict[str, Any]] = []
    for worker_name in AUTO_WORKER_NAMES:
        worker = workers[worker_name]
        stop = await stop_worker_optimization(db, worker.id)
        stop_results.append(
            {
                "worker_id": worker.id,
                "worker_name": worker_name,
                "ok": stop.ok,
                "message": stop.message,
                "error": stop.error,
            }
        )
    return stop_results


def _session_time_remaining_seconds(session: AutoSession) -> int:
    elapsed = (datetime.now(timezone.utc) - session.started_at).total_seconds()
    return max(0, int(AUTO_LIMIT_SECONDS - elapsed))


def _end_session_if_time_limit_reached(session: AutoSession | None) -> None:
    """Mark session finished when the auto time limit has elapsed."""
    if session is None or not session.running:
        return
    if _session_time_remaining_seconds(session) <= 0:
        session.running = False


async def start_auto_mode(
    db: AsyncSession,
    *,
    region: str,
    tool: str = AUTO_TOOL,
) -> AutoStartResponse:
    if not auto_mode_store.enabled:
        raise ValueError("Auto mode is disabled")

    _end_session_if_time_limit_reached(auto_mode_store.session)

    if auto_mode_store.session and auto_mode_store.session.running:
        raise ValueError("Auto mode session already running")

    parsed = parse_window(region)
    window = parsed.window

    if auto_mode_store.last_started_region == window:
        return _skipped_start_response(
            region=window,
            tool=tool,
            message=f"Auto start skipped: same region as last round ({window})",
        )

    # Only /auto/start begins work — stop any leftover jobs first.
    await stop_all_auto_workers(db)

    find_result_candidates = await find_auto_candidate_pool(
        db,
        window=window,
        tool=tool,
        k=AUTO_FIND_K,
    )
    if not find_result_candidates:
        raise ValueError("No candidates found for region")

    selected_slots = assign_workers_by_metric(find_result_candidates)
    if not selected_slots:
        raise ValueError("No candidates found for region")

    workers = await resolve_workers_by_name(db, AUTO_WORKER_NAMES)
    worker_algorithms = effective_worker_algorithms()
    worker_trial_threads = effective_worker_trial_threads()
    worker_trial_memory_gb = effective_worker_trial_memory_gb()

    assignments: list[AutoDispatchAssignment] = []
    dispatch_results: list[AutoDispatchAssignment] = []

    for slot in selected_slots:
        worker_name = slot.worker_name
        candidate = slot.candidate
        algorithm = worker_algorithms[worker_name]
        trial_threads = worker_trial_threads[worker_name]
        trial_memory_gb = worker_trial_memory_gb[worker_name]
        worker = workers[worker_name]
        dispatch_window = candidate_dispatch_window(candidate, window)
        dispatch_body = build_dispatch_request(
            window=dispatch_window,
            tool=tool,
            base_conf=candidate.base_conf,
            candidate_index=candidate.index,
            algorithm=algorithm,
            trial_threads=trial_threads,
            trial_memory_gb=trial_memory_gb,
        )
        response = await dispatch_to_worker(db, worker.id, dispatch_body)
        assignment = AutoDispatchAssignment(
            worker_id=worker.id,
            worker_name=worker_name,
            algorithm=algorithm,
            candidate_index=candidate.index,
            selection_reason=slot.selection_reason,
            composite_score=composite_candidate_score(candidate),
            history_score=candidate.history_score,
            similarity=candidate.similarity,
            base_conf=with_trial_resources(
                candidate.base_conf,
                trial_threads=trial_threads,
                trial_memory_gb=trial_memory_gb,
            ),
            window=dispatch_window,
            params=effective_auto_params(),
            param_intervals=effective_auto_param_intervals(),
            concurrency=AUTO_CONCURRENCY,
            limit_seconds=AUTO_LIMIT_SECONDS,
            adaptive_max_trials=AUTO_ADAPTIVE_MAX_TRIALS,
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
        selected_candidates=selected_slots,
        found_candidates=list(find_result_candidates),
        candidates_found=len(find_result_candidates),
        running=True,
    )

    ok_count = sum(1 for item in dispatch_results if item.dispatch_ok)
    if ok_count > 0:
        auto_mode_store.last_started_region = window
        await set_control_plane_setting(db, LAST_AUTO_START_REGION_KEY, window)

    return AutoStartResponse(
        ok=ok_count > 0,
        skipped=False,
        region=window,
        tool=tool,
        candidates_found=len(find_result_candidates),
        candidates_selected=len(selected_slots),
        workers_dispatched=ok_count,
        found_candidates=list(find_result_candidates),
        selected_candidates=_selected_candidate_models(selected_slots),
        assignments=dispatch_results,
        message=(
            f"Auto mode started: {ok_count}/{len(AUTO_WORKER_NAMES)} workers dispatched"
            if ok_count
            else "Auto mode failed: no workers accepted dispatch"
        ),
    )


async def restart_auto_mode_session(db: AsyncSession) -> AutoModeStatus:
    """Stop auto workers and clear session state so POST /auto/start can run again."""
    await stop_all_auto_workers(db)
    auto_mode_store.end_session()
    await set_control_plane_setting(db, LAST_AUTO_START_REGION_KEY, None)
    return auto_mode_store.status()


async def collect_best_and_stop(db: AsyncSession) -> AutoBestResponse:
    session = auto_mode_store.session
    worker_ids: list[str]
    if session and session.assignments:
        worker_ids = [item.worker_id for item in session.assignments]
    else:
        workers = await resolve_workers_by_name(db, AUTO_WORKER_NAMES)
        worker_ids = [workers[name].id for name in AUTO_WORKER_NAMES]

    best_entries: list[tuple[str, str, float, dict[str, Any]]] = []

    for worker_id in worker_ids:
        best = await fetch_worker_best(db, worker_id)
        if best.ok and best.best_score is not None and best.best_conf:
            worker_name = next(
                (
                    a.worker_name
                    for a in (session.assignments if session else [])
                    if a.worker_id == worker_id
                ),
                worker_id[:8],
            )
            best_entries.append((worker_id, worker_name, float(best.best_score), best.best_conf))

    # Always stop every auto worker — work must not continue after /auto/best.
    stop_results = await stop_all_auto_workers(db)

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
