import { WorkerBestScoreResult, WorkerRecord } from "../api/client";
import { WorkerAssignment } from "../types/workerAssignment";

export function isWorkerJobActive(
  best: WorkerBestScoreResult | "loading" | undefined,
  assignment: WorkerAssignment | undefined,
): boolean {
  if (assignment?.dispatching) return true;
  if (best && best !== "loading" && best.ok) {
    return best.status === "optimizing" || best.status === "stopping";
  }
  return false;
}

/** Idle workers keep API/name order; active workers move to the end (latest active last). */
export function sortWorkersForDisplay(
  workers: WorkerRecord[],
  bestByWorker: Record<string, WorkerBestScoreResult | "loading">,
  assignments: Record<string, WorkerAssignment>,
  activeWorkerOrder: Record<string, number>,
): WorkerRecord[] {
  return [...workers].sort((a, b) => {
    const aActive = isWorkerJobActive(bestByWorker[a.id], assignments[a.id]);
    const bActive = isWorkerJobActive(bestByWorker[b.id], assignments[b.id]);

    if (aActive !== bActive) {
      return aActive ? 1 : -1;
    }

    if (aActive && bActive) {
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
): Record<string, number> | null {
  let next: Record<string, number> | null = null;
  let maxOrder = Math.max(0, ...Object.values(current));

  for (const worker of workers) {
    const id = worker.id;
    const active = isWorkerJobActive(bestByWorker[id], assignments[id]);
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
