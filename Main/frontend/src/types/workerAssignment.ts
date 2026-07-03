import { AutoModeStatus, CandidatePreview, FindCandidatesResponse, WorkerRecord } from "../api/client";
import { defaultSelectedParams, listToolOptionKeys } from "../utils/candidateAssign";
import {
  applyWorkerTunableDefaults,
  paramIntervalsForWorker,
  selectedParamsForWorker,
} from "../utils/workerTunableStorage";
import {
  buildSelectedParamIntervals,
  ensureManualDefaultsHydrated,
  workerDefaultAlgorithm,
  workerDefaultConcurrency,
  workerDefaultTrialMemoryGb,
  workerDefaultTrialThreads,
} from "../utils/manualParamDefaults";
import { defaultParamInterval, ParamInterval } from "../utils/paramBounds";
import { isWorkerJobRunning } from "../utils/workerJobStatus";

export const TOOLKIT_OPTIONS = ["gatk", "bcftools", "deepvariant"] as const;
export type ToolkitOption = (typeof TOOLKIT_OPTIONS)[number];

export const ALGORITHM_OPTIONS = ["optuna", "gp", "random", "sobol", "lhs"] as const;
export type AlgorithmOption = (typeof ALGORITHM_OPTIONS)[number];

export const DEFAULT_TOOLKIT: ToolkitOption = "gatk";
export const DEFAULT_ALGORITHM: AlgorithmOption = "optuna";
export const DEFAULT_LIMIT_SECONDS = 1800;
export const DEFAULT_LIMIT_MINUTES = 30;
export const DEFAULT_ADAPTIVE_MAX_TRIALS = 44;
export const DEFAULT_TOTAL_TRIALS = 45;
export const DEFAULT_TRIAL_THREADS = 4;
export const DEFAULT_TRIAL_MEMORY_GB = 6;
export const MAX_TRIAL_THREADS = 100;
export const MAX_CONCURRENCY = 32;
export const CONCURRENCY_OPTIONS = [1, 2, 3, 4, 6, 8] as const;

export interface WorkerAssignment {
  candidate: CandidatePreview;
  window: string;
  tool: ToolkitOption;
  algorithm: AlgorithmOption;
  selectedParams: string[];
  /** Per-parameter search interval (min/max/step or enum values) for this worker */
  paramIntervals: Record<string, ParamInterval>;
  concurrency: number;
  limitSeconds: number;
  /** GATK Docker CPUs per trial slot (sent as base_conf.threads). */
  trialThreads: number;
  /** GATK Docker RAM in GB per trial slot (sent as base_conf.memory_gb). */
  trialMemoryGb: number;
  /** Total trials (1 base + search). Used for all supported search algorithms. */
  trialCount: number;
  dispatching: boolean;
  dispatchError: string | null;
  /** ISO timestamp when optimization was last dispatched to this worker. */
  dispatchedAt?: string | null;
  /** Set when assignment is driven by auto mode orchestration. */
  autoManaged?: boolean;
}

export function secondsToLimitMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

export function limitMinutesToSeconds(minutes: number): number {
  const parsed = Number(minutes);
  if (!Number.isFinite(parsed) || parsed <= 0) return 60;
  return Math.max(60, Math.round(parsed) * 60);
}

export function isAdaptiveAlgorithm(algorithm: AlgorithmOption | string): boolean {
  const algo = String(algorithm).toLowerCase();
  return (
    algo === "optuna" ||
    algo === "gp" ||
    algo === "random" ||
    algo === "sobol" ||
    algo === "lhs"
  );
}

export function clampTotalTrials(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_TOTAL_TRIALS;
  return Math.min(1001, Math.max(2, parsed));
}

export function adaptiveMaxTrialsFromTotal(totalTrials: number): number {
  return Math.max(1, clampTotalTrials(totalTrials) - 1);
}

export function clampTrialThreads(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_TRIAL_THREADS;
  return Math.min(MAX_TRIAL_THREADS, Math.max(1, parsed));
}

export function clampTrialMemoryGb(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_TRIAL_MEMORY_GB;
  return Math.min(128, Math.max(4, parsed));
}

export function clampConcurrency(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return 1;
  return Math.min(MAX_CONCURRENCY, Math.max(1, parsed));
}

export function buildDispatchBaseConf(
  baseConf: Record<string, unknown>,
  trialThreads: number,
  trialMemoryGb: number,
): Record<string, unknown> {
  return {
    ...baseConf,
    threads: clampTrialThreads(trialThreads),
    memory_gb: clampTrialMemoryGb(trialMemoryGb),
  };
}

export function normalizeWorkerAssignment(assignment: WorkerAssignment): WorkerAssignment {
  return {
    ...assignment,
    trialThreads: clampTrialThreads(assignment.trialThreads ?? DEFAULT_TRIAL_THREADS),
    trialMemoryGb: clampTrialMemoryGb(assignment.trialMemoryGb ?? DEFAULT_TRIAL_MEMORY_GB),
    trialCount: clampTotalTrials(assignment.trialCount ?? DEFAULT_TOTAL_TRIALS),
  };
}

export function buildDefaultParamIntervals(
  tool: ToolkitOption,
  baseConf: Record<string, unknown>,
  paramNames: string[],
): Record<string, ParamInterval> {
  const intervals: Record<string, ParamInterval> = {};
  for (const param of paramNames) {
    const options = baseConf[`${tool}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";
    intervals[param] = defaultParamInterval(tool, param, baseValue);
  }
  return intervals;
}

export function resolveAssignmentWindow(
  candidate: CandidatePreview,
  contextWindow: string,
): string {
  const fromCandidate = candidate.source_window?.trim();
  return fromCandidate || contextWindow;
}

export function createAssignment(
  candidate: CandidatePreview,
  context: FindCandidatesResponse,
  worker?: Pick<WorkerRecord, "id" | "name">,
): WorkerAssignment {
  ensureManualDefaultsHydrated();
  const tool = (context.tool?.toLowerCase() as ToolkitOption) || DEFAULT_TOOLKIT;
  const resolvedTool = TOOLKIT_OPTIONS.includes(tool) ? tool : DEFAULT_TOOLKIT;
  const keys = listToolOptionKeys(candidate.base_conf, resolvedTool);
  const workerRef = worker ? { id: worker.id, name: worker.name } : undefined;
  const fromWorker = workerRef
    ? selectedParamsForWorker(workerRef, resolvedTool, keys)
    : [];
  const selectedParams =
    fromWorker.length > 0 ? fromWorker : defaultSelectedParams(resolvedTool, keys);
  const tunableDefaults = applyWorkerTunableDefaults(
    workerRef,
    resolvedTool,
    candidate.base_conf,
    selectedParams,
  );
  const workerName = worker?.name?.trim() ?? "";
  return {
    candidate,
    window: resolveAssignmentWindow(candidate, context.window),
    tool: resolvedTool,
    algorithm: workerName
      ? tunableDefaults.algorithm || workerDefaultAlgorithm(workerName)
      : tunableDefaults.algorithm,
    selectedParams: tunableDefaults.selectedParams,
    paramIntervals: tunableDefaults.paramIntervals,
    concurrency: workerName
      ? tunableDefaults.concurrency || workerDefaultConcurrency(workerName)
      : tunableDefaults.concurrency,
    limitSeconds: tunableDefaults.limitSeconds,
    trialThreads: workerName
      ? tunableDefaults.trialThreads || workerDefaultTrialThreads(workerName)
      : tunableDefaults.trialThreads,
    trialMemoryGb: workerName
      ? tunableDefaults.trialMemoryGb || workerDefaultTrialMemoryGb(workerName)
      : tunableDefaults.trialMemoryGb,
    trialCount: tunableDefaults.trialCount,
    dispatching: false,
    dispatchError: null,
  };
}

export function assignmentParamsForTool(
  assignment: WorkerAssignment,
  tool: ToolkitOption,
  worker?: Pick<WorkerRecord, "id" | "name">,
): Pick<WorkerAssignment, "tool" | "selectedParams" | "paramIntervals"> {
  const keys = listToolOptionKeys(assignment.candidate.base_conf, tool);
  const workerRef = worker ? { id: worker.id, name: worker.name } : undefined;
  const fromWorker = workerRef ? selectedParamsForWorker(workerRef, tool, keys) : [];
  const selectedParams =
    fromWorker.length > 0 ? fromWorker : defaultSelectedParams(tool, keys);
  return {
    tool,
    selectedParams,
    paramIntervals: workerRef
      ? paramIntervalsForWorker(
          workerRef,
          tool,
          assignment.candidate.base_conf,
          selectedParams,
        )
      : buildSelectedParamIntervals(tool, assignment.candidate.base_conf, selectedParams),
  };
}

export function assignmentLabel(worker: WorkerRecord): string {
  return worker.name || worker.id.slice(0, 8);
}

export interface WorkerOptimizationSnapshot {
  ok: boolean;
  status: string | null;
}

export interface WorkerAssignmentSummary {
  workerId: string;
  workerName: string;
  candidateIndex: number | null;
  autoManaged: boolean;
  /** True while optimization is starting or running — no candidate may be assigned. */
  reassignmentLocked: boolean;
}

export function isWorkerOptimizationActive(
  optimization?: WorkerOptimizationSnapshot | null,
  assignment?: WorkerAssignment,
  autoModeStatus?: AutoModeStatus | null,
  nowMs = Date.now(),
): boolean {
  if (!optimization?.ok) return false;
  return isWorkerJobRunning(
    optimization.status,
    resolveWorkerJobStartedAt(assignment, autoModeStatus),
    resolveWorkerJobLimitSeconds(assignment, autoModeStatus),
    nowMs,
  );
}

export function resolveWorkerJobStartedAt(
  assignment: WorkerAssignment | undefined,
  autoModeStatus?: AutoModeStatus | null,
): string | null {
  if (assignment?.dispatchedAt) return assignment.dispatchedAt;
  if (assignment?.autoManaged && autoModeStatus?.started_at) {
    return autoModeStatus.started_at;
  }
  return null;
}

export function resolveWorkerJobLimitSeconds(
  assignment: WorkerAssignment | undefined,
  autoModeStatus?: AutoModeStatus | null,
): number | null {
  return assignment?.limitSeconds ?? autoModeStatus?.config?.limit_seconds ?? null;
}

export function isWorkerCandidateAssignmentLocked(
  assignment: WorkerAssignment | undefined,
  optimization?: WorkerOptimizationSnapshot | null,
  autoModeStatus?: AutoModeStatus | null,
  nowMs = Date.now(),
): boolean {
  if (assignment?.dispatching) return true;
  return isWorkerOptimizationActive(optimization, assignment, autoModeStatus, nowMs);
}

/** @deprecated Use isWorkerCandidateAssignmentLocked */
export function isBaseConfReassignmentLocked(
  assignment: WorkerAssignment | undefined,
  optimization?: WorkerOptimizationSnapshot | null,
  autoModeStatus?: AutoModeStatus | null,
  nowMs = Date.now(),
): boolean {
  return isWorkerCandidateAssignmentLocked(assignment, optimization, autoModeStatus, nowMs);
}

export function buildWorkerAssignmentSummaries(
  workers: WorkerRecord[],
  assignments: Record<string, WorkerAssignment>,
  bestByWorker: Record<string, WorkerOptimizationSnapshot | "loading"> = {},
  autoModeStatus?: AutoModeStatus | null,
  nowMs = Date.now(),
): WorkerAssignmentSummary[] {
  return workers
    .map((worker) => {
      const assignment = assignments[worker.id];
      const best = bestByWorker[worker.id];
      const optimization = best && best !== "loading" ? best : null;
      return {
        workerId: worker.id,
        workerName: assignmentLabel(worker),
        candidateIndex: assignment?.candidate.index ?? null,
        autoManaged: Boolean(assignment?.autoManaged),
        reassignmentLocked: isWorkerCandidateAssignmentLocked(
          assignment,
          optimization,
          autoModeStatus,
          nowMs,
        ),
      };
    })
    .sort((a, b) => a.workerName.localeCompare(b.workerName));
}
