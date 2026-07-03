import { AutoModeConfig } from "../api/client";
import {
  AlgorithmOption,
  ALGORITHM_OPTIONS,
  clampConcurrency,
  clampTotalTrials,
  clampTrialMemoryGb,
  clampTrialThreads,
  DEFAULT_ALGORITHM,
  DEFAULT_LIMIT_SECONDS,
  DEFAULT_AUTO_TOTAL_TRIALS,
  DEFAULT_TOTAL_TRIALS,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
  ToolkitOption,
  TOOLKIT_OPTIONS,
  WorkerAssignment,
} from "../types/workerAssignment";
import {
  workerAlgorithmsFromAutoConfig,
  workerConcurrencyFromAutoConfig,
  workerLimitSecondsFromAutoConfig,
  workerSettingForName,
  workerTrialCountsFromAutoConfig,
  workerTrialMemoryGbFromAutoConfig,
  workerTrialThreadsFromAutoConfig,
} from "./autoModeSync";
import { buildSelectedParamIntervals } from "./manualParamDefaults";
import { clampParamInterval, defaultParamInterval, ParamInterval } from "./paramBounds";

const STORAGE_KEY = "effortless:per-worker-tunable:v1";

export interface WorkerTunableDefaults {
  tool: string;
  selectedParams: string[];
  paramIntervals: Record<string, ParamInterval>;
  algorithm: AlgorithmOption;
  concurrency: number;
  limitSeconds: number;
  trialThreads: number;
  trialMemoryGb: number;
  trialCount: number;
}

interface StoredPerWorkerTunables {
  version: 1;
  byWorkerName: Record<string, WorkerTunableDefaults>;
  byWorkerId: Record<string, WorkerTunableDefaults>;
}

function normalizeAlgorithm(raw: string | undefined): AlgorithmOption {
  if (raw && ALGORITHM_OPTIONS.includes(raw as AlgorithmOption)) {
    return raw as AlgorithmOption;
  }
  return DEFAULT_ALGORITHM;
}

function normalizeTool(raw: string | undefined): ToolkitOption {
  const tool = (raw ?? "gatk").toLowerCase().trim();
  return TOOLKIT_OPTIONS.includes(tool as ToolkitOption) ? (tool as ToolkitOption) : "gatk";
}

function normalizeProfile(raw: unknown): WorkerTunableDefaults | null {
  if (!raw || typeof raw !== "object") return null;
  const parsed = raw as Partial<WorkerTunableDefaults>;
  if (!Array.isArray(parsed.selectedParams)) return null;
  const selectedParams = parsed.selectedParams.filter(
    (param): param is string => typeof param === "string" && param.length > 0,
  );
  if (selectedParams.length === 0) return null;

  const paramIntervals: Record<string, ParamInterval> = {};
  if (parsed.paramIntervals && typeof parsed.paramIntervals === "object") {
    for (const [name, interval] of Object.entries(parsed.paramIntervals)) {
      if (!interval || typeof interval !== "object") continue;
      paramIntervals[name] = interval as ParamInterval;
    }
  }

  return {
    tool: normalizeTool(parsed.tool),
    selectedParams,
    paramIntervals,
    algorithm: normalizeAlgorithm(parsed.algorithm),
    concurrency: clampConcurrency(Number(parsed.concurrency) || 1),
    limitSeconds: Math.max(60, Math.round(Number(parsed.limitSeconds) || DEFAULT_LIMIT_SECONDS)),
    trialThreads: clampTrialThreads(Number(parsed.trialThreads) || DEFAULT_TRIAL_THREADS),
    trialMemoryGb: clampTrialMemoryGb(Number(parsed.trialMemoryGb) || DEFAULT_TRIAL_MEMORY_GB),
    trialCount: clampTotalTrials(Number(parsed.trialCount) || DEFAULT_TOTAL_TRIALS),
  };
}

function emptyStore(): StoredPerWorkerTunables {
  return { version: 1, byWorkerName: {}, byWorkerId: {} };
}

function loadStore(): StoredPerWorkerTunables {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return emptyStore();
    const parsed = JSON.parse(raw) as Partial<StoredPerWorkerTunables>;
    if (!parsed || typeof parsed !== "object") return emptyStore();
    const byWorkerName: Record<string, WorkerTunableDefaults> = {};
    const byWorkerId: Record<string, WorkerTunableDefaults> = {};
    if (parsed.byWorkerName && typeof parsed.byWorkerName === "object") {
      for (const [name, profile] of Object.entries(parsed.byWorkerName)) {
        const normalized = normalizeProfile(profile);
        if (normalized) byWorkerName[name] = normalized;
      }
    }
    if (parsed.byWorkerId && typeof parsed.byWorkerId === "object") {
      for (const [id, profile] of Object.entries(parsed.byWorkerId)) {
        const normalized = normalizeProfile(profile);
        if (normalized) byWorkerId[id] = normalized;
      }
    }
    return { version: 1, byWorkerName, byWorkerId };
  } catch {
    return emptyStore();
  }
}

function saveStore(store: StoredPerWorkerTunables): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Ignore quota / private-mode errors.
  }
}

function workerNameKey(workerName: string | undefined | null): string | null {
  const trimmed = workerName?.trim();
  return trimmed ? trimmed : null;
}

export function profileFromAssignment(assignment: WorkerAssignment): WorkerTunableDefaults {
  return {
    tool: assignment.tool,
    selectedParams: [...assignment.selectedParams],
    paramIntervals: { ...assignment.paramIntervals },
    algorithm: assignment.algorithm,
    concurrency: assignment.concurrency,
    limitSeconds: assignment.limitSeconds,
    trialThreads: assignment.trialThreads,
    trialMemoryGb: assignment.trialMemoryGb,
    trialCount: assignment.trialCount,
  };
}

export function saveWorkerTunableDefaults(
  worker: { id: string; name?: string | null },
  assignment: WorkerAssignment,
): void {
  if (assignment.autoManaged || assignment.selectedParams.length === 0) return;
  const profile = profileFromAssignment(assignment);
  const store = loadStore();
  const nameKey = workerNameKey(worker.name);
  if (nameKey) {
    store.byWorkerName[nameKey] = profile;
    const lower = nameKey.toLowerCase();
    const matched = Object.keys(store.byWorkerName).find((key) => key.toLowerCase() === lower);
    if (matched && matched !== nameKey) {
      delete store.byWorkerName[matched];
    }
  }
  if (worker.id) {
    store.byWorkerId[worker.id] = profile;
  }
  saveStore(store);
}

export function getWorkerTunableDefaults(
  worker: { id: string; name?: string | null },
  tool?: string,
): WorkerTunableDefaults | null {
  const store = loadStore();
  const toolKey = tool?.toLowerCase().trim();
  const nameKey = workerNameKey(worker.name);
  const candidates: WorkerTunableDefaults[] = [];
  if (nameKey && store.byWorkerName[nameKey]) {
    candidates.push(store.byWorkerName[nameKey]);
  } else if (nameKey) {
    const lower = nameKey.toLowerCase();
    const matched = Object.entries(store.byWorkerName).find(
      ([key]) => key.toLowerCase() === lower,
    );
    if (matched) candidates.push(matched[1]);
  }
  if (worker.id && store.byWorkerId[worker.id]) {
    candidates.push(store.byWorkerId[worker.id]);
  }
  if (candidates.length === 0) return null;
  if (!toolKey) return candidates[0];
  return candidates.find((profile) => profile.tool === toolKey) ?? null;
}

export function selectedParamsForWorker(
  worker: { id: string; name?: string | null },
  tool: string,
  available: string[],
): string[] {
  const availableSet = new Set(available);
  const saved = getWorkerTunableDefaults(worker, tool);
  if (saved) {
    const fromSaved = saved.selectedParams.filter((param) => availableSet.has(param));
    if (fromSaved.length > 0) return fromSaved;
  }
  return [];
}

export function paramIntervalsForWorker(
  worker: { id: string; name?: string | null },
  tool: string,
  baseConf: Record<string, unknown>,
  paramNames: string[],
): Record<string, ParamInterval> {
  const toolKey = tool.toLowerCase().trim();
  const saved = getWorkerTunableDefaults(worker, toolKey);
  if (!saved || saved.tool !== toolKey) {
    return buildSelectedParamIntervals(toolKey, baseConf, paramNames);
  }

  const intervals: Record<string, ParamInterval> = {};
  for (const param of paramNames) {
    const options = baseConf[`${toolKey}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";
    const savedInterval = saved.paramIntervals[param];
    intervals[param] = savedInterval
      ? clampParamInterval(toolKey, param, savedInterval)
      : defaultParamInterval(toolKey, param, baseValue);
  }
  return intervals;
}

export function applyWorkerTunableDefaults(
  worker: { id: string; name?: string | null } | undefined,
  tool: ToolkitOption,
  baseConf: Record<string, unknown>,
  selectedParams: string[],
): Pick<
  WorkerAssignment,
  | "algorithm"
  | "selectedParams"
  | "paramIntervals"
  | "concurrency"
  | "limitSeconds"
  | "trialThreads"
  | "trialMemoryGb"
  | "trialCount"
> {
  if (!worker) {
    return {
      selectedParams,
      paramIntervals: buildSelectedParamIntervals(tool, baseConf, selectedParams),
      algorithm: DEFAULT_ALGORITHM,
      concurrency: 1,
      limitSeconds: DEFAULT_LIMIT_SECONDS,
      trialThreads: DEFAULT_TRIAL_THREADS,
      trialMemoryGb: DEFAULT_TRIAL_MEMORY_GB,
      trialCount: DEFAULT_TOTAL_TRIALS,
    };
  }

  const saved = getWorkerTunableDefaults(worker, tool);
  return {
    selectedParams,
    paramIntervals: paramIntervalsForWorker(worker, tool, baseConf, selectedParams),
    algorithm: saved?.algorithm ?? DEFAULT_ALGORITHM,
    concurrency: saved?.concurrency ?? 1,
    limitSeconds: saved?.limitSeconds ?? DEFAULT_LIMIT_SECONDS,
    trialThreads: saved?.trialThreads ?? DEFAULT_TRIAL_THREADS,
    trialMemoryGb: saved?.trialMemoryGb ?? DEFAULT_TRIAL_MEMORY_GB,
    trialCount: saved?.trialCount ?? DEFAULT_TOTAL_TRIALS,
  };
}

export function syncPerWorkerTunablesFromAutoConfig(config: AutoModeConfig): void {
  if (config.params.length === 0) return;
  const store = loadStore();
  const algorithms = workerAlgorithmsFromAutoConfig(config);
  const trialThreads = workerTrialThreadsFromAutoConfig(config);
  const trialMemoryGb = workerTrialMemoryGbFromAutoConfig(config);
  const concurrency = workerConcurrencyFromAutoConfig(config);
  const limitSeconds = workerLimitSecondsFromAutoConfig(config);
  const trialCounts = workerTrialCountsFromAutoConfig(config);
  const paramIntervals = Object.fromEntries(
    Object.entries(config.param_intervals).map(([name, spec]) => [
      name,
      {
        min: spec.min,
        max: spec.max,
        step: spec.step,
        values: spec.values,
      },
    ]),
  );

  for (const workerName of config.worker_names) {
    store.byWorkerName[workerName] = {
      tool: config.tool.toLowerCase().trim(),
      selectedParams: [...config.params],
      paramIntervals: { ...paramIntervals },
      algorithm: normalizeAlgorithm(workerSettingForName(algorithms, workerName)),
      concurrency: clampConcurrency(
        workerSettingForName(concurrency, workerName) ?? config.concurrency,
      ),
      limitSeconds: Math.max(
        60,
        Math.round(workerSettingForName(limitSeconds, workerName) ?? config.limit_seconds),
      ),
      trialThreads: clampTrialThreads(
        workerSettingForName(trialThreads, workerName) ?? DEFAULT_TRIAL_THREADS,
      ),
      trialMemoryGb: clampTrialMemoryGb(
        workerSettingForName(trialMemoryGb, workerName) ?? DEFAULT_TRIAL_MEMORY_GB,
      ),
      trialCount: clampTotalTrials(
        workerSettingForName(trialCounts, workerName) ?? DEFAULT_AUTO_TOTAL_TRIALS,
      ),
    };
  }
  saveStore(store);
}
