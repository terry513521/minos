import { computeDeadlineFromLimit } from "../hooks/useSubmissionCountdown";

export const WORKER_STATUS_TIME_LIMITED = "time limited";

export function isWorkerJobActiveStatus(status: string | null | undefined): boolean {
  return status === "optimizing" || status === "benchmarking" || status === "stopping";
}

export interface WorkerJobTimingSource {
  started_at?: string | null;
  limit_seconds?: number | null;
}

export function resolveWorkerJobStartedAt(
  assignment: { dispatchedAt?: string | null; autoManaged?: boolean } | undefined,
  autoModeStatus?: { started_at?: string | null } | null,
  best?: WorkerJobTimingSource | null,
): string | null {
  if (best?.started_at) return best.started_at;
  if (assignment?.dispatchedAt) return assignment.dispatchedAt;
  if (assignment?.autoManaged && autoModeStatus?.started_at) {
    return autoModeStatus.started_at;
  }
  return null;
}

export function resolveWorkerJobLimitSeconds(
  assignment: { limitSeconds?: number } | undefined,
  autoModeStatus?: { config?: { limit_seconds?: number } } | null,
  best?: WorkerJobTimingSource | null,
): number | null {
  if (best?.limit_seconds != null && best.limit_seconds > 0) {
    return best.limit_seconds;
  }
  if (assignment?.limitSeconds != null && assignment.limitSeconds > 0) {
    return assignment.limitSeconds;
  }
  return autoModeStatus?.config?.limit_seconds ?? null;
}

export function isRunTimeLimitReached(
  startedAt: string | null | undefined,
  limitSeconds: number | null | undefined,
  nowMs = Date.now(),
): boolean {
  const deadline = computeDeadlineFromLimit(startedAt, limitSeconds);
  return deadline != null && nowMs >= deadline;
}

export function resolveWorkerJobStatus(
  rawStatus: string | null | undefined,
  startedAt: string | null | undefined,
  limitSeconds: number | null | undefined,
  nowMs = Date.now(),
): string | null {
  if (!rawStatus) return null;
  if (
    isWorkerJobActiveStatus(rawStatus) &&
    isRunTimeLimitReached(startedAt, limitSeconds, nowMs)
  ) {
    return WORKER_STATUS_TIME_LIMITED;
  }
  return rawStatus;
}

export function isWorkerJobRunning(
  rawStatus: string | null | undefined,
  startedAt?: string | null,
  limitSeconds?: number | null,
  nowMs = Date.now(),
): boolean {
  if (!isWorkerJobActiveStatus(rawStatus)) {
    return false;
  }
  return !isRunTimeLimitReached(startedAt, limitSeconds, nowMs);
}
