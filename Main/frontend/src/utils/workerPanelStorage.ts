import {
  WorkerBestScoreResult,
  WorkerDispatchResult,
  WorkerHealthCheckResult,
} from "../api/client";
import { WorkerAssignment, normalizeWorkerAssignment } from "../types/workerAssignment";

const STORAGE_KEY = "effortless:worker-panel:v1";

export interface PersistedWorkerPanelState {
  assignments: Record<string, WorkerAssignment>;
  baseConfByWorker: Record<string, Record<string, unknown>>;
  dispatchByWorker: Record<string, WorkerDispatchResult | null>;
  bestByWorker: Record<string, WorkerBestScoreResult>;
  healthByWorker: Record<string, WorkerHealthCheckResult>;
}

function sanitizeAssignment(assignment: WorkerAssignment): WorkerAssignment {
  return normalizeWorkerAssignment({
    ...assignment,
    dispatching: false,
  });
}

export function loadWorkerPanelState(): PersistedWorkerPanelState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedWorkerPanelState>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      assignments: parsed.assignments ?? {},
      baseConfByWorker: parsed.baseConfByWorker ?? {},
      dispatchByWorker: parsed.dispatchByWorker ?? {},
      bestByWorker: parsed.bestByWorker ?? {},
      healthByWorker: parsed.healthByWorker ?? {},
    };
  } catch {
    return null;
  }
}

export function saveWorkerPanelState(state: PersistedWorkerPanelState): void {
  const assignments: Record<string, WorkerAssignment> = {};
  for (const [workerId, assignment] of Object.entries(state.assignments)) {
    assignments[workerId] = sanitizeAssignment(assignment);
  }

  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        assignments,
        baseConfByWorker: state.baseConfByWorker,
        dispatchByWorker: state.dispatchByWorker,
        bestByWorker: state.bestByWorker,
        healthByWorker: state.healthByWorker,
      }),
    );
  } catch {
    // Ignore quota / private-mode errors.
  }
}

export function clearWorkerPanelEntry(workerId: string): void {
  const current = loadWorkerPanelState();
  if (!current) return;
  const next = { ...current };
  delete next.assignments[workerId];
  delete next.baseConfByWorker[workerId];
  delete next.dispatchByWorker[workerId];
  delete next.bestByWorker[workerId];
  delete next.healthByWorker[workerId];
  saveWorkerPanelState(next);
}
