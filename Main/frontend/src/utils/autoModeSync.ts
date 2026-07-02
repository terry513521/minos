import {
  AutoDispatchAssignment,
  AutoModeConfig,
  AutoModeStatus,
  CandidatePreview,
  WorkerRecord,
} from "../api/client";
import { ParamInterval } from "./paramBounds";
import { AlgorithmOption, ToolkitOption, WorkerAssignment } from "../types/workerAssignment";

export function paramIntervalsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, ParamInterval> {
  const intervals: Record<string, ParamInterval> = {};
  for (const [name, spec] of Object.entries(config.param_intervals)) {
    intervals[name] = {
      min: spec.min,
      max: spec.max,
      step: spec.step,
      values: spec.values,
    };
  }
  return intervals;
}

export function assignmentFromAutoDispatch(
  autoAssignment: AutoDispatchAssignment,
  config: AutoModeConfig,
): WorkerAssignment {
  const candidate: CandidatePreview = {
    index: autoAssignment.candidate_index,
    base_conf: autoAssignment.base_conf,
    rank_score: autoAssignment.history_score ?? autoAssignment.composite_score,
    history_score: autoAssignment.history_score,
    similarity: autoAssignment.similarity,
    history_id: null,
    source_window: autoAssignment.window,
  };

  const paramIntervals =
    Object.keys(autoAssignment.param_intervals).length > 0
      ? Object.fromEntries(
          Object.entries(autoAssignment.param_intervals).map(([name, spec]) => [
            name,
            {
              min: spec.min,
              max: spec.max,
              step: spec.step,
              values: spec.values,
            } satisfies ParamInterval,
          ]),
        )
      : paramIntervalsFromAutoConfig(config);

  return {
    candidate,
    window: autoAssignment.window ?? "",
    tool: config.tool as ToolkitOption,
    algorithm: autoAssignment.algorithm as AlgorithmOption,
    selectedParams:
      autoAssignment.params.length > 0 ? autoAssignment.params : [...config.params],
    paramIntervals,
    concurrency: autoAssignment.concurrency || config.concurrency,
    limitSeconds: autoAssignment.limit_seconds || config.limit_seconds,
    dispatching: false,
    dispatchError: autoAssignment.dispatch_error,
    autoManaged: true,
  };
}

export function previewAssignmentsFromAutoConfig(
  status: AutoModeStatus,
  workers: WorkerRecord[],
): Record<string, WorkerAssignment> {
  if (!status.enabled || status.assignments.length > 0) {
    return {};
  }

  const intervals = paramIntervalsFromAutoConfig(status.config);
  const next: Record<string, WorkerAssignment> = {};
  for (const worker of workers) {
    const algorithm = status.config.worker_algorithms[worker.name];
    if (!algorithm) continue;
    next[worker.id] = {
      candidate: {
        index: 0,
        base_conf: {},
        rank_score: 0,
        history_id: null,
        source_window: status.region,
        history_score: null,
        similarity: null,
      },
      window: status.region ?? "",
      tool: status.config.tool as ToolkitOption,
      algorithm: algorithm as AlgorithmOption,
      selectedParams: [...status.config.params],
      paramIntervals: intervals,
      concurrency: status.config.concurrency,
      limitSeconds: status.config.limit_seconds,
      dispatching: false,
      dispatchError: null,
      autoManaged: true,
    };
  }
  return next;
}

export function assignmentsFromAutoMode(status: AutoModeStatus): Record<string, WorkerAssignment> {
  if (!status.assignments.length) {
    return {};
  }
  const next: Record<string, WorkerAssignment> = {};
  for (const item of status.assignments) {
    next[item.worker_id] = assignmentFromAutoDispatch(item, status.config);
  }
  return next;
}

export function formatParamInterval(spec: ParamInterval): string {
  if (spec.values?.length) {
    return spec.values.join(", ");
  }
  const parts: string[] = [];
  if (spec.min != null) parts.push(`min ${spec.min}`);
  if (spec.max != null) parts.push(`max ${spec.max}`);
  if (spec.step != null) parts.push(`step ${spec.step}`);
  return parts.join(" · ");
}
