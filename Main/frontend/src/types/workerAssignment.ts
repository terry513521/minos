import { CandidatePreview, FindCandidatesResponse, WorkerRecord } from "../api/client";
import { defaultSelectedParams, listToolOptionKeys } from "../utils/candidateAssign";
import {
  defaultParamInterval,
  ParamInterval,
} from "../utils/paramBounds";

export const TOOLKIT_OPTIONS = ["gatk", "bcftools", "deepvariant"] as const;
export type ToolkitOption = (typeof TOOLKIT_OPTIONS)[number];

export const ALGORITHM_OPTIONS = ["grid", "random", "optuna"] as const;
export type AlgorithmOption = (typeof ALGORITHM_OPTIONS)[number];

export const DEFAULT_TOOLKIT: ToolkitOption = "gatk";
export const DEFAULT_ALGORITHM: AlgorithmOption = "grid";
export const DEFAULT_LIMIT_SECONDS = 1800;
export const DEFAULT_LIMIT_MINUTES = 30;
export const DEFAULT_ADAPTIVE_MAX_TRIALS = 44;
export const DEFAULT_TOTAL_TRIALS = 45;
export const DEFAULT_TRIAL_THREADS = 4;
export const DEFAULT_TRIAL_MEMORY_GB = 6;

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
  /** Total trials for random/optuna (1 base + search). Ignored for grid. */
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
  return algorithm === "random" || algorithm === "optuna";
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
  return Math.min(32, Math.max(1, parsed));
}

export function clampTrialMemoryGb(value: number): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_TRIAL_MEMORY_GB;
  return Math.min(128, Math.max(4, parsed));
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
): WorkerAssignment {
  const tool = (context.tool?.toLowerCase() as ToolkitOption) || DEFAULT_TOOLKIT;
  const resolvedTool = TOOLKIT_OPTIONS.includes(tool) ? tool : DEFAULT_TOOLKIT;
  const keys = listToolOptionKeys(candidate.base_conf, resolvedTool);
  const selectedParams = defaultSelectedParams(resolvedTool, keys);
  return {
    candidate,
    window: resolveAssignmentWindow(candidate, context.window),
    tool: resolvedTool,
    algorithm: DEFAULT_ALGORITHM,
    selectedParams,
    paramIntervals: buildDefaultParamIntervals(
      resolvedTool,
      candidate.base_conf,
      selectedParams,
    ),
    concurrency: 1,
    limitSeconds: DEFAULT_LIMIT_SECONDS,
    trialThreads: DEFAULT_TRIAL_THREADS,
    trialMemoryGb: DEFAULT_TRIAL_MEMORY_GB,
    trialCount: DEFAULT_TOTAL_TRIALS,
    dispatching: false,
    dispatchError: null,
  };
}

export function assignmentParamsForTool(
  assignment: WorkerAssignment,
  tool: ToolkitOption,
): Pick<WorkerAssignment, "tool" | "selectedParams" | "paramIntervals"> {
  const keys = listToolOptionKeys(assignment.candidate.base_conf, tool);
  const selectedParams = defaultSelectedParams(tool, keys);
  return {
    tool,
    selectedParams,
    paramIntervals: buildDefaultParamIntervals(
      tool,
      assignment.candidate.base_conf,
      selectedParams,
    ),
  };
}

export function assignmentLabel(worker: WorkerRecord): string {
  return worker.name || worker.id.slice(0, 8);
}
