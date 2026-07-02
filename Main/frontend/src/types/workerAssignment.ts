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
  dispatching: boolean;
  dispatchError: string | null;
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
    window: context.window,
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
