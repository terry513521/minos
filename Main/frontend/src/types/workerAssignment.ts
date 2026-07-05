import { AutoModeStatus, CandidatePreview, FindCandidatesResponse, WorkerRecord } from "../api/client";
import { defaultSelectedParams, listToolOptionKeys, toolOptionsKey } from "../utils/candidateAssign";
import { ensureToolOptionsInBaseConf } from "../utils/confEdit";
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
import {
  isWorkerJobRunning,
  resolveWorkerJobLimitSeconds,
  resolveWorkerJobStartedAt,
} from "../utils/workerJobStatus";
import { normalizeRegion } from "../utils/window";

export const TOOLKIT_OPTIONS = ["gatk", "bcftools", "deepvariant"] as const;
export type ToolkitOption = (typeof TOOLKIT_OPTIONS)[number];

export const ALGORITHM_OPTIONS = [
  "cascade",
  "pbt",
  "grid",
  "delta",
  "optuna",
  "gp",
  "random",
  "sobol",
  "lhs",
] as const;
export type AlgorithmOption = (typeof ALGORITHM_OPTIONS)[number];

export const DEFAULT_TOOLKIT: ToolkitOption = "deepvariant";
export const DEFAULT_ALGORITHM: AlgorithmOption = "cascade";
export const DEFAULT_LIMIT_SECONDS = 1800;
export const DEFAULT_LIMIT_MINUTES = 30;
export const DEFAULT_ADAPTIVE_MAX_TRIALS = 4;
/** Benchmark-only conf check: one base trial, no search. */
export const CONF_CHECK_ADAPTIVE_MAX_TRIALS = 0;
/** Placeholder algorithm for benchmark-only dispatch (search is skipped). */
export const CONF_CHECK_ALGORITHM: AlgorithmOption = "grid";
/** Conf check defaults: lighter than manual worker assignments. */
export const CONF_CHECK_TRIAL_THREADS = 4;
export const CONF_CHECK_TRIAL_MEMORY_GB = 16;
export const DEFAULT_TOTAL_TRIALS = 5;
/** Auto-mode default: 1 base benchmark + 49 adaptive search trials. */
export const DEFAULT_AUTO_ADAPTIVE_MAX_TRIALS = 49;
export const DEFAULT_AUTO_TOTAL_TRIALS = 50;
export const DEFAULT_TRIAL_THREADS = 4;
export const DEFAULT_TRIAL_MEMORY_GB = 16;
export const TRIAL_MEMORY_GB_BY_TOOL: Record<ToolkitOption, number> = {
  gatk: 6,
  bcftools: 6,
  deepvariant: 16,
};

export function defaultTrialMemoryGbForTool(tool: ToolkitOption): number {
  return TRIAL_MEMORY_GB_BY_TOOL[tool] ?? DEFAULT_TRIAL_MEMORY_GB;
}

/** Tool is fixed by base conf (`gatk_options`, `bcftools_options`, etc.). */
export function inferToolFromBaseConf(
  baseConf: Record<string, unknown>,
  fallback: ToolkitOption = DEFAULT_TOOLKIT,
): ToolkitOption {
  for (const tool of TOOLKIT_OPTIONS) {
    const options = baseConf[toolOptionsKey(tool)];
    if (options && typeof options === "object" && !Array.isArray(options)) {
      return tool;
    }
  }
  return TOOLKIT_OPTIONS.includes(fallback) ? fallback : DEFAULT_TOOLKIT;
}
export const DEFAULT_INCLUDE_BASE_BENCHMARK = true;
export const DEFAULT_DELTA_ROUNDS = 5;
export const MAX_TRIAL_THREADS = 100;
export const MAX_CONCURRENCY = 32;
export const CONCURRENCY_OPTIONS = Array.from(
  { length: MAX_CONCURRENCY },
  (_, index) => index + 1,
);

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
  /** Score dropped base conf once before search trials when starting optimization. */
  includeBaseBenchmark: boolean;
  /** Delta algorithm: refinement rounds (±delta per param around current best). */
  deltaRounds: number;
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
  return ALGORITHM_OPTIONS.includes(algo as AlgorithmOption);
}

export function clampTotalTrials(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_TOTAL_TRIALS;
  return Math.min(1001, Math.max(2, parsed));
}

export function adaptiveMaxTrialsFromTotal(totalTrials: number): number {
  return Math.max(1, clampTotalTrials(totalTrials) - 1);
}

export function adaptiveMaxTrialsForDispatch(
  trialCount: number,
  includeBaseBenchmark: boolean,
  algorithm: AlgorithmOption | string,
): number {
  if (!isAdaptiveAlgorithm(algorithm)) {
    return DEFAULT_ADAPTIVE_MAX_TRIALS;
  }
  const total = clampTotalTrials(trialCount);
  if (includeBaseBenchmark) {
    return Math.max(1, total - 1);
  }
  return Math.max(1, total);
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
  tool?: ToolkitOption,
): Record<string, unknown> {
  const memoryGb = tool
    ? clampTrialMemoryGb(Math.max(trialMemoryGb, defaultTrialMemoryGbForTool(tool)))
    : clampTrialMemoryGb(trialMemoryGb);
  return {
    ...baseConf,
    threads: clampTrialThreads(trialThreads),
    memory_gb: memoryGb,
  };
}

export function clampDeltaRounds(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_DELTA_ROUNDS;
  return Math.min(1000, Math.max(1, parsed));
}

export function normalizeWorkerAssignment(assignment: WorkerAssignment): WorkerAssignment {
  return {
    ...assignment,
    trialThreads: clampTrialThreads(assignment.trialThreads ?? DEFAULT_TRIAL_THREADS),
    trialMemoryGb: clampTrialMemoryGb(assignment.trialMemoryGb ?? DEFAULT_TRIAL_MEMORY_GB),
    trialCount: clampTotalTrials(assignment.trialCount ?? DEFAULT_TOTAL_TRIALS),
    includeBaseBenchmark:
      assignment.includeBaseBenchmark ?? DEFAULT_INCLUDE_BASE_BENCHMARK,
    deltaRounds: clampDeltaRounds(assignment.deltaRounds ?? DEFAULT_DELTA_ROUNDS),
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

/** Region for a worker assignment: dashboard Region input, else find-result window. */
export function assignmentWindowFromRegion(
  regionInput: string | undefined | null,
  findResultWindow?: string,
): string {
  const fromInput = normalizeRegion(regionInput ?? "") ?? regionInput?.trim();
  if (fromInput) return fromInput;
  const fromFind = normalizeRegion(findResultWindow ?? "") ?? findResultWindow?.trim();
  return fromFind ?? "";
}

export function mergeAssignmentWithWorkerTunables(
  worker: { id: string; name?: string | null },
  assignment: WorkerAssignment,
): WorkerAssignment {
  if (assignment.autoManaged) return assignment;

  const tool = assignment.tool;
  const keys = listToolOptionKeys(assignment.candidate.base_conf, tool);
  const fromSaved = selectedParamsForWorker(worker, tool, keys);
  const selectedParams =
    fromSaved.length > 0
      ? fromSaved
      : assignment.selectedParams.length > 0
        ? assignment.selectedParams
        : defaultSelectedParams(tool, keys);

  const tunables = applyWorkerTunableDefaults(
    worker,
    tool,
    assignment.candidate.base_conf,
    selectedParams,
  );

  return normalizeWorkerAssignment({
    ...assignment,
    ...tunables,
    selectedParams,
  });
}

export function createAssignment(
  candidate: CandidatePreview,
  context: FindCandidatesResponse,
  worker?: Pick<WorkerRecord, "id" | "name">,
  regionInput?: string,
): WorkerAssignment {
  ensureManualDefaultsHydrated();
  const contextTool = (context.tool?.toLowerCase() as ToolkitOption) || DEFAULT_TOOLKIT;
  const contextFallback = TOOLKIT_OPTIONS.includes(contextTool) ? contextTool : DEFAULT_TOOLKIT;
  const resolvedTool = inferToolFromBaseConf(candidate.base_conf, contextFallback);
  const hydratedConf = ensureToolOptionsInBaseConf(candidate.base_conf, resolvedTool);
  const hydratedCandidate = { ...candidate, base_conf: hydratedConf };
  const keys = listToolOptionKeys(hydratedConf, resolvedTool);
  const workerRef = worker ? { id: worker.id, name: worker.name } : undefined;
  const fromWorker = workerRef
    ? selectedParamsForWorker(workerRef, resolvedTool, keys)
    : [];
  const selectedParams =
    fromWorker.length > 0 ? fromWorker : defaultSelectedParams(resolvedTool, keys);
  const tunableDefaults = applyWorkerTunableDefaults(
    workerRef,
    resolvedTool,
    hydratedConf,
    selectedParams,
  );
  const workerName = worker?.name?.trim() ?? "";
  return {
    candidate: hydratedCandidate,
    window: assignmentWindowFromRegion(regionInput, context.window),
    tool: resolvedTool,
    algorithm: workerName
      ? (tunableDefaults.algorithm ?? workerDefaultAlgorithm(workerName))
      : tunableDefaults.algorithm,
    selectedParams: tunableDefaults.selectedParams,
    paramIntervals: tunableDefaults.paramIntervals,
    concurrency: workerName
      ? (tunableDefaults.concurrency ?? workerDefaultConcurrency(workerName))
      : tunableDefaults.concurrency,
    limitSeconds: tunableDefaults.limitSeconds,
    trialThreads: workerName
      ? (tunableDefaults.trialThreads ?? workerDefaultTrialThreads(workerName))
      : tunableDefaults.trialThreads,
    trialMemoryGb: workerName
      ? (tunableDefaults.trialMemoryGb ?? workerDefaultTrialMemoryGb(workerName))
      : tunableDefaults.trialMemoryGb,
    trialCount: tunableDefaults.trialCount,
    includeBaseBenchmark: tunableDefaults.includeBaseBenchmark,
    deltaRounds: tunableDefaults.deltaRounds ?? DEFAULT_DELTA_ROUNDS,
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

export {
  resolveWorkerJobLimitSeconds,
  resolveWorkerJobStartedAt,
} from "../utils/workerJobStatus";

export interface WorkerOptimizationSnapshot {
  ok: boolean;
  status: string | null;
  started_at?: string | null;
  limit_seconds?: number | null;
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
    resolveWorkerJobStartedAt(assignment, autoModeStatus, optimization),
    resolveWorkerJobLimitSeconds(assignment, autoModeStatus, optimization),
    nowMs,
  );
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
