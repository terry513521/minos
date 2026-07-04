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
  DEFAULT_DELTA_ROUNDS,
  DEFAULT_INCLUDE_BASE_BENCHMARK,
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

export function workerSettingForName<T>(
  map: Record<string, T> | undefined,
  workerName: string,
): T | undefined {
  if (!map || !workerName.trim()) return undefined;
  const trimmed = workerName.trim();
  if (map[trimmed] !== undefined) return map[trimmed];
  const lower = trimmed.toLowerCase();
  const matchedKey = Object.keys(map).find((key) => key.toLowerCase() === lower);
  return matchedKey ? map[matchedKey] : undefined;
}

function workerSettingsFromConfig<T>(
  config: AutoModeConfig,
  map: Record<string, T> | undefined,
  fallback: T,
): Record<string, T> {
  const settings: Record<string, T> = {};
  for (const workerName of config.worker_names) {
    settings[workerName] = workerSettingForName(map, workerName) ?? fallback;
  }
  return settings;
}

export function workerAlgorithmsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, AlgorithmOption> {
  return workerSettingsFromConfig(
    config,
    config.worker_algorithms as Record<string, AlgorithmOption>,
    DEFAULT_ALGORITHM,
  );
}

export function workerTrialThreadsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  return workerSettingsFromConfig(
    config,
    config.worker_trial_threads,
    DEFAULT_TRIAL_THREADS,
  );
}

export function workerTrialMemoryGbFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  return workerSettingsFromConfig(
    config,
    config.worker_trial_memory_gb,
    DEFAULT_TRIAL_MEMORY_GB,
  );
}

export function workerConcurrencyFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  return workerSettingsFromConfig(config, config.worker_concurrency, 1);
}

export function workerLimitSecondsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  return workerSettingsFromConfig(
    config,
    config.worker_limit_seconds ?? {},
    config.limit_seconds,
  );
}

export function workerAdaptiveMaxTrialsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  return workerSettingsFromConfig(
    config,
    config.worker_adaptive_max_trials ?? {},
    config.adaptive_max_trials,
  );
}

export function workerTrialCountsFromAutoConfig(
  config: AutoModeConfig,
): Record<string, number> {
  const adaptiveByWorker = workerAdaptiveMaxTrialsFromAutoConfig(config);
  return Object.fromEntries(
    config.worker_names.map((workerName) => [
      workerName,
      clampTotalTrials(
        (workerSettingForName(adaptiveByWorker, workerName) ?? config.adaptive_max_trials) + 1,
      ),
    ]),
  );
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
    concurrency: autoAssignment.concurrency || workerSettingForName(config.worker_concurrency, autoAssignment.worker_name) || config.concurrency,
    limitSeconds:
      autoAssignment.limit_seconds ||
      workerSettingForName(workerLimitSecondsFromAutoConfig(config), autoAssignment.worker_name) ||
      config.limit_seconds,
    ...trialResourcesFromConf(autoAssignment.base_conf),
    trialCount: clampTotalTrials(
      (autoAssignment.adaptive_max_trials ??
        workerSettingForName(
          workerAdaptiveMaxTrialsFromAutoConfig(config),
          autoAssignment.worker_name,
        ) ??
        config.adaptive_max_trials) + 1,
    ),
    includeBaseBenchmark: DEFAULT_INCLUDE_BASE_BENCHMARK,
    deltaRounds: DEFAULT_DELTA_ROUNDS,
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
  const concurrencyByWorker = workerConcurrencyFromAutoConfig(status.config);
  const limitSecondsByWorker = workerLimitSecondsFromAutoConfig(status.config);
  const trialCountsByWorker = workerTrialCountsFromAutoConfig(status.config);
  const next: Record<string, WorkerAssignment> = {};
  for (const worker of workers) {
    const algorithm = workerSettingForName(
      status.config.worker_algorithms,
      worker.name,
    );
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
      concurrency: workerSettingForName(concurrencyByWorker, worker.name) ?? status.config.concurrency,
      limitSeconds:
        workerSettingForName(limitSecondsByWorker, worker.name) ?? status.config.limit_seconds,
      trialThreads: workerSettingForName(trialThreadsByWorker, worker.name) ?? DEFAULT_TRIAL_THREADS,
      trialMemoryGb:
        workerSettingForName(trialMemoryByWorker, worker.name) ?? DEFAULT_TRIAL_MEMORY_GB,
      trialCount: workerSettingForName(trialCountsByWorker, worker.name) ?? trialCountFromAutoConfig(status.config),
      includeBaseBenchmark: DEFAULT_INCLUDE_BASE_BENCHMARK,
      deltaRounds: DEFAULT_DELTA_ROUNDS,
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

export function formatParamInterval(spec: ParamInterval, algorithm?: string): string {
  if (spec.values?.length) {
    return spec.values.join(", ");
  }
  if (String(algorithm ?? "").toLowerCase() === "delta" && spec.delta != null) {
    return `±${spec.delta}`;
  }
  const parts: string[] = [];
  if (spec.min != null) parts.push(`min ${spec.min}`);
  if (spec.max != null) parts.push(`max ${spec.max}`);
  if (spec.step != null) parts.push(`step ${spec.step}`);
  if (spec.delta != null) parts.push(`delta ${spec.delta}`);
  return parts.join(" · ");
}
