from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BestSnapshot:
    job_id: str | None = None
    window: str | None = None
    tool: str | None = None
    best_score: float | None = None
    best_conf: dict[str, Any] = field(default_factory=dict)
    trials_evaluated: int = 0
    search_space_size: int = 0
    status: str = "idle"
    message: str | None = None
    updated_at: datetime | None = None


class BestStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = BestSnapshot()

    def begin_job(
        self,
        job_id: str,
        window: str,
        tool: str,
        *,
        search_space_size: int = 0,
    ) -> None:
        with self._lock:
            self._snapshot = BestSnapshot(
                job_id=job_id,
                window=window,
                tool=tool,
                status="optimizing",
                search_space_size=search_space_size,
                message="Running base benchmark",
                updated_at=datetime.now(timezone.utc),
            )

    def set_progress(self, *, trials_evaluated: int, message: str | None = None) -> None:
        with self._lock:
            self._snapshot.trials_evaluated = trials_evaluated
            if message:
                self._snapshot.message = message
            self._snapshot.updated_at = datetime.now(timezone.utc)

    def update_best(
        self,
        *,
        score: float,
        conf: dict[str, Any],
        trials_evaluated: int,
        message: str | None = None,
    ) -> None:
        with self._lock:
            current = self._snapshot.best_score
            if current is None or score > current:
                self._snapshot.best_score = score
                self._snapshot.best_conf = deepcopy(conf)
            self._snapshot.trials_evaluated = trials_evaluated
            if message:
                self._snapshot.message = message
            self._snapshot.updated_at = datetime.now(timezone.utc)

    def finish_job(self, *, message: str) -> None:
        with self._lock:
            self._snapshot.status = "ready"
            self._snapshot.message = message
            self._snapshot.updated_at = datetime.now(timezone.utc)

    def fail_job(self, *, message: str) -> None:
        with self._lock:
            self._snapshot.status = "error"
            self._snapshot.message = message
            self._snapshot.updated_at = datetime.now(timezone.utc)

    def snapshot(self) -> BestSnapshot:
        with self._lock:
            snap = self._snapshot
            return BestSnapshot(
                job_id=snap.job_id,
                window=snap.window,
                tool=snap.tool,
                best_score=snap.best_score,
                best_conf=deepcopy(snap.best_conf),
                trials_evaluated=snap.trials_evaluated,
                search_space_size=snap.search_space_size,
                status=snap.status,
                message=snap.message,
                updated_at=snap.updated_at,
            )


best_store = BestStateStore()
