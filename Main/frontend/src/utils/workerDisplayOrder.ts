import {
  WorkerBestScoreResult,
  WorkerHealthCheckResult,
  WorkerRecord,
} from "../api/client";
import { WorkerAssignment } from "../types/workerAssignment";
import { isRunTimeLimitReached } from "./workerJobStatus";

export function isWorkerOptimizing(
  best: WorkerBestScoreResult | "loading" | undefined,
  jobStartedAt?: string | null,
  jobLimitSeconds?: number | null,
  nowMs = Date.now(),
): boolean {
  if (best && best !== "loading" && best.ok) {
    if (best.status !== "optimizing" && best.status !== "stopping") return false;
    return !isRunTimeLimitReached(jobStartedAt, jobLimitSeconds, nowMs);
  }
  return false;
}

/** Poll GET /best only while a job is starting or actively running. */
export function shouldPollWorkerBest(
  best: WorkerBestScoreResult | "loading" | undefined,
  assignment: WorkerAssignment | undefined,
  jobStartedAt?: string | null,
  jobLimitSeconds?: number | null,
  nowMs = Date.now(),
): boolean {
  if (isRunTimeLimitReached(jobStartedAt, jobLimitSeconds, nowMs)) return false;
  if (assignment?.dispatching) return true;
  if (best && best !== "loading" && best.ok) {
    return isWorkerOptimizing(best, jobStartedAt, jobLimitSeconds, nowMs);
  }
  return Boolean(assignment?.dispatchedAt && !assignment.dispatchError);
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
  if (
    isWorkerOptimizing(
      best,
      assignment?.dispatchedAt,
      assignment?.limitSeconds,
      nowMs,
    )
  ) {
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
    const active = isWorkerOptimizing(
      bestByWorker[id],
      assignment?.dispatchedAt,
      assignment?.limitSeconds,
      nowMs,
    );
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
