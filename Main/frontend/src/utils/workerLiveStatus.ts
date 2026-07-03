import {
  AutoModeStatus,
  WorkerBestScoreResult,
  WorkerDispatchResult,
  WorkerHealthCheckResult,
  WorkerRecord,
} from "../api/client";
import {
  resolveWorkerJobLimitSeconds,
  resolveWorkerJobStartedAt,
  WorkerAssignment,
} from "../types/workerAssignment";
import { isWorkerJobRunning, resolveWorkerJobStatus } from "./workerJobStatus";

export interface WorkerLiveStatus {
  workerId: string;
  workerName: string;
  connected: boolean;
  bestScore: number | null;
  displayStatus: string | null;
  trialLabel: string;
  hasConf: boolean;
  bestConf: Record<string, unknown>;
  isOptimizing: boolean;
  runStartedAt: string | null;
  runLimitSeconds: number | null;
  loadError: string | null;
}

export function formatWorkerBestScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${(score * 100).toFixed(2)}%`;
}

export function formatWorkerTrialProgress(
  evaluated: number,
  total: number | null | undefined,
  status: string | null | undefined,
): string {
  const done = Math.max(0, evaluated);
  const planned = total && total > 0 ? total : null;
  if (planned) {
    if (status === "optimizing" || status === "stopping") return `${done} / ${planned}`;
    return `${done} / ${planned} trials`;
  }
  if (done > 0) return `${done} trial${done === 1 ? "" : "s"}`;
  return "—";
}

export function workerBestStatusClass(status: string | null | undefined): string {
  if (status === "ready" || status === "idle") return "online";
  if (status === "time limited") return "warn";
  if (status === "optimizing" || status === "stopping") return "running";
  if (status === "error") return "failed";
  return "offline";
}

function trialTotal(
  best: WorkerBestScoreResult | undefined,
  dispatchResult: WorkerDispatchResult | null | undefined,
): number | null {
  if (best?.search_space_size && best.search_space_size > 0) {
    return best.search_space_size;
  }
  const fromDispatch = dispatchResult?.result?.search_space_size;
  if (typeof fromDispatch === "number" && fromDispatch > 0) {
    return fromDispatch;
  }
  return null;
}

function hasConfContent(conf: Record<string, unknown>): boolean {
  return Object.keys(conf).length > 0;
}

function isWorkerConnected(
  status: WorkerRecord["status"],
  health: WorkerHealthCheckResult | "loading" | undefined,
): boolean {
  if (health && health !== "loading") {
    return health.ok;
  }
  return status === "online" || status === "draining";
}

export function buildWorkerLiveStatuses(
  workers: WorkerRecord[],
  bestByWorker: Record<string, WorkerBestScoreResult | "loading">,
  healthByWorker: Record<string, WorkerHealthCheckResult | "loading">,
  assignments: Record<string, WorkerAssignment>,
  dispatchByWorker: Record<string, WorkerDispatchResult | null>,
  autoModeStatus: AutoModeStatus | null,
  nowMs = Date.now(),
): WorkerLiveStatus[] {
  return workers.map((worker) => {
    const assignment = assignments[worker.id];
    const health = healthByWorker[worker.id];
    const best = bestByWorker[worker.id];
    const dispatchResult = dispatchByWorker[worker.id];
    const runStartedAt = resolveWorkerJobStartedAt(assignment, autoModeStatus);
    const runLimitSeconds = resolveWorkerJobLimitSeconds(assignment, autoModeStatus);

    if (!best || best === "loading") {
      return {
        workerId: worker.id,
        workerName: worker.name,
        connected: isWorkerConnected(worker.status, health),
        bestScore: null,
        displayStatus: null,
        trialLabel: "—",
        hasConf: false,
        bestConf: {},
        isOptimizing: false,
        runStartedAt,
        runLimitSeconds,
        loadError: null,
      };
    }

    if (!best.ok) {
      return {
        workerId: worker.id,
        workerName: worker.name,
        connected: isWorkerConnected(worker.status, health),
        bestScore: null,
        displayStatus: null,
        trialLabel: "—",
        hasConf: false,
        bestConf: {},
        isOptimizing: false,
        runStartedAt,
        runLimitSeconds,
        loadError: best.error ?? "Could not load worker status",
      };
    }

    const displayStatus = resolveWorkerJobStatus(
      best.status,
      runStartedAt,
      runLimitSeconds,
      nowMs,
    );
    const isOptimizing = isWorkerJobRunning(
      best.status,
      runStartedAt,
      runLimitSeconds,
      nowMs,
    );
    const trialTotalCount = trialTotal(best, dispatchResult);

    return {
      workerId: worker.id,
      workerName: worker.name,
      connected: isWorkerConnected(worker.status, health),
      bestScore: best.best_score,
      displayStatus,
      trialLabel: formatWorkerTrialProgress(
        best.trials_evaluated,
        trialTotalCount,
        displayStatus,
      ),
      hasConf: hasConfContent(best.best_conf),
      bestConf: best.best_conf,
      isOptimizing,
      runStartedAt,
      runLimitSeconds,
      loadError: null,
    };
  });
}

export function sortWorkerLiveStatusesByScore(rows: WorkerLiveStatus[]): WorkerLiveStatus[] {
  return [...rows].sort((a, b) => {
    const aScore = a.bestScore;
    const bScore = b.bestScore;
    if (aScore != null && bScore != null && aScore !== bScore) {
      return bScore - aScore;
    }
    if (aScore != null && bScore == null) return -1;
    if (aScore == null && bScore != null) return 1;
    return a.workerName.localeCompare(b.workerName);
  });
}
