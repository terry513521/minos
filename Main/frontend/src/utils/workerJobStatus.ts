import { computeDeadlineFromLimit } from "../hooks/useSubmissionCountdown";

export const WORKER_STATUS_TIME_LIMITED = "time limited";

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
    (rawStatus === "optimizing" || rawStatus === "stopping") &&
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
  if (rawStatus !== "optimizing" && rawStatus !== "stopping") return false;
  return !isRunTimeLimitReached(startedAt, limitSeconds, nowMs);
}
