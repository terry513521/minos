import {
  WorkerBestScoreResult,
  WorkerHealthCheckResult,
  WorkerRecord,
} from "../api/client";
import { WorkerAssignment } from "../types/workerAssignment";
import {
  isRunTimeLimitReached,
  isWorkerJobActiveStatus,
  isWorkerJobRunning,
  resolveWorkerJobLimitSeconds,
  resolveWorkerJobStartedAt,
} from "./workerJobStatus";

export function isWorkerOptimizing(
  best: WorkerBestScoreResult | "loading" | undefined,
  assignment?: WorkerAssignment,
  nowMs = Date.now(),
): boolean {
  if (best && best !== "loading" && best.ok) {
    if (!isWorkerJobActiveStatus(best.status)) return false;
    return isWorkerJobRunning(
      best.status,
      resolveWorkerJobStartedAt(assignment, undefined, best),
      resolveWorkerJobLimitSeconds(assignment, undefined, best),
      nowMs,
    );
  }
  return false;
}

/** Poll GET /best while a job is starting or actively running. */
export function shouldPollWorkerBest(
  best: WorkerBestScoreResult | "loading" | undefined,
  assignment: WorkerAssignment | undefined,
  nowMs = Date.now(),
): boolean {
  if (assignment?.dispatching) return true;
  if (best && best !== "loading" && best.ok && isWorkerJobActiveStatus(best.status)) {
    return true;
  }
  const startedAt = resolveWorkerJobStartedAt(assignment, undefined, best && best !== "loading" ? best : null);
  const limitSeconds = resolveWorkerJobLimitSeconds(assignment, undefined, best && best !== "loading" ? best : null);
  if (isRunTimeLimitReached(startedAt, limitSeconds, nowMs)) return false;
  if (assignment?.dispatchedAt && !assignment.dispatchError) return true;
  return false;
}

/** A probe was made and the worker did not accept the connection or job. */
export function isWorkerConnectionFailed(
  health: WorkerHealthCheckResult | "loading" | undefined,
  best: WorkerBestScoreResult | "loading" | undefined,
  assignment: WorkerAssignment | undefined,
): boolean {
  if (isWorkerOptimizing(best)) return false;
  if (health && health !== "loading" && !health.ok) return true;
  if (best && best !== "loading" && !best.ok) return true;
  if (assignment?.dispatchError) return true;
  return false;
}

type WorkerDisplayTier = 0 | 1 | 2;

function bestScoreForSort(
  best: WorkerBestScoreResult | "loading" | undefined,
): number | null {
  if (
    best &&
    best !== "loading" &&
    best.ok &&
    best.best_score != null &&
    !Number.isNaN(best.best_score)
  ) {
    return best.best_score;
  }
  return null;
}

function workerDisplayTier(
  best: WorkerBestScoreResult | "loading" | undefined,
  health: WorkerHealthCheckResult | "loading" | undefined,
  assignment: WorkerAssignment | undefined,
  nowMs: number,
): WorkerDisplayTier {
  if (isWorkerConnectionFailed(health, best, assignment)) return 2;
  if (isWorkerOptimizing(best, assignment, nowMs)) {
    return 1;
  }
  return 0;
}

/** Idle workers first; optimizing workers above failed (by best score); failed last. */
export function sortWorkersForDisplay(
  workers: WorkerRecord[],
  bestByWorker: Record<string, WorkerBestScoreResult | "loading">,
  healthByWorker: Record<string, WorkerHealthCheckResult | "loading">,
  assignments: Record<string, WorkerAssignment>,
  activeWorkerOrder: Record<string, number>,
  nowMs = Date.now(),
): WorkerRecord[] {
  return [...workers].sort((a, b) => {
    const aTier = workerDisplayTier(
      bestByWorker[a.id],
      healthByWorker[a.id],
      assignments[a.id],
      nowMs,
    );
    const bTier = workerDisplayTier(
      bestByWorker[b.id],
      healthByWorker[b.id],
      assignments[b.id],
      nowMs,
    );

    if (aTier !== bTier) {
      return aTier - bTier;
    }

    if (aTier === 1) {
      const aScore = bestScoreForSort(bestByWorker[a.id]);
      const bScore = bestScoreForSort(bestByWorker[b.id]);
      if (aScore != null && bScore != null && aScore !== bScore) {
        return bScore - aScore;
      }
      if (aScore != null && bScore == null) return -1;
      if (aScore == null && bScore != null) return 1;
      return (activeWorkerOrder[a.id] ?? 0) - (activeWorkerOrder[b.id] ?? 0);
    }

    return a.name.localeCompare(b.name);
  });
}

export function nextActiveWorkerOrder(
  current: Record<string, number>,
  workers: WorkerRecord[],
  bestByWorker: Record<string, WorkerBestScoreResult | "loading">,
  assignments: Record<string, WorkerAssignment>,
  nowMs = Date.now(),
): Record<string, number> | null {
  let next: Record<string, number> | null = null;
  let maxOrder = Math.max(0, ...Object.values(current));

  for (const worker of workers) {
    const id = worker.id;
    const assignment = assignments[id];
    const active = isWorkerOptimizing(bestByWorker[id], assignment, nowMs);
    const existing = current[id];

    if (active) {
      if (existing == null) {
        if (!next) next = { ...current };
        maxOrder += 1;
        next[id] = maxOrder;
      }
    } else if (existing != null) {
      if (!next) next = { ...current };
      delete next[id];
    }
  }

  return next;
}
