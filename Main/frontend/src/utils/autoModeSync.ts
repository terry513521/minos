import {
  AutoDispatchAssignment,
  AutoModeConfig,
  AutoModeStatus,
  CandidatePreview,
  WorkerRecord,
} from "../api/client";
import { ParamInterval } from "./paramBounds";
import {
  AlgorithmOption,
  clampTrialMemoryGb,
  clampTrialThreads,
  clampTotalTrials,
  DEFAULT_ALGORITHM,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
  ToolkitOption,
  WorkerAssignment,
} from "../types/workerAssignment";

function trialResourcesFromConf(baseConf: Record<string, unknown>) {
  const threads = baseConf.threads;
  const memoryGb = baseConf.memory_gb;
  return {
    trialThreads: clampTrialThreads(
      typeof threads === "number" ? threads : Number(threads) || DEFAULT_TRIAL_THREADS,
    ),
    trialMemoryGb: clampTrialMemoryGb(
      typeof memoryGb === "number" ? memoryGb : Number(memoryGb) || DEFAULT_TRIAL_MEMORY_GB,
    ),
  };
}

function trialCountFromAutoConfig(config: AutoModeConfig): number {
  return clampTotalTrials(config.adaptive_max_trials + 1);
}

export function workerAlgorithmsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, AlgorithmOption> {
  const algorithms: Record<string, AlgorithmOption> = {};
  for (const workerName of config.worker_names) {
    const raw = config.worker_algorithms[workerName] ?? DEFAULT_ALGORITHM;
    algorithms[workerName] = raw as AlgorithmOption;
  }
  return algorithms;
}

export function workerTrialThreadsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  const threads: Record<string, number> = {};
  for (const workerName of config.worker_names) {
    const raw = config.worker_trial_threads?.[workerName] ?? DEFAULT_TRIAL_THREADS;
    threads[workerName] = clampTrialThreads(raw);
  }
  return threads;
}

export function workerTrialMemoryGbFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  const memory: Record<string, number> = {};
  for (const workerName of config.worker_names) {
    const raw = config.worker_trial_memory_gb?.[workerName] ?? DEFAULT_TRIAL_MEMORY_GB;
    memory[workerName] = clampTrialMemoryGb(raw);
  }
  return memory;
}

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
  sessionStartedAt?: string | null,
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
    ...trialResourcesFromConf(autoAssignment.base_conf),
    trialCount: trialCountFromAutoConfig(config),
    dispatching: false,
    dispatchError: autoAssignment.dispatch_error,
    dispatchedAt:
      autoAssignment.dispatch_ok && sessionStartedAt ? sessionStartedAt : null,
    autoManaged: true,
  };
}

export function previewAssignmentsFromAutoConfig(
  status: AutoModeStatus,
  workers: WorkerRecord[],
): Record<string, WorkerAssignment> {
  if (!status.enabled || status.running || status.assignments.length > 0) {
    return {};
  }

  const intervals = paramIntervalsFromAutoConfig(status.config);
  const trialThreadsByWorker = workerTrialThreadsFromAutoConfig(status.config);
  const trialMemoryByWorker = workerTrialMemoryGbFromAutoConfig(status.config);
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
      trialThreads: trialThreadsByWorker[worker.name] ?? DEFAULT_TRIAL_THREADS,
      trialMemoryGb: trialMemoryByWorker[worker.name] ?? DEFAULT_TRIAL_MEMORY_GB,
      trialCount: trialCountFromAutoConfig(status.config),
      dispatching: false,
      dispatchError: null,
      autoManaged: true,
    };
  }
  return next;
}

export function assignmentsAsManual(
  status: AutoModeStatus,
): Record<string, WorkerAssignment> {
  const synced = assignmentsFromAutoMode(status);
  return Object.fromEntries(
    Object.entries(synced).map(([workerId, assignment]) => [
      workerId,
      { ...assignment, autoManaged: false },
    ]),
  );
}

export function assignmentsFromAutoMode(status: AutoModeStatus): Record<string, WorkerAssignment> {
  if (!status.assignments.length) {
    return {};
  }
  const next: Record<string, WorkerAssignment> = {};
  for (const item of status.assignments) {
    next[item.worker_id] = assignmentFromAutoDispatch(
      item,
      status.config,
      status.started_at,
    );
  }
  return next;
}

/** Live auto session assignments shown on worker cards while auto mode is running. */
export function autoAssignmentsForStatus(
  status: AutoModeStatus,
): Record<string, WorkerAssignment> {
  if (status.enabled && status.running && status.assignments.length > 0) {
    return assignmentsFromAutoMode(status);
  }
  return {};
}

/** Persisted auto session converted to manual cards after auto mode is turned off. */
export function manualAssignmentsFromEndedAuto(
  status: AutoModeStatus,
): Record<string, WorkerAssignment> {
  if (!status.enabled && status.assignments.length > 0) {
    return assignmentsAsManual(status);
  }
  return {};
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
