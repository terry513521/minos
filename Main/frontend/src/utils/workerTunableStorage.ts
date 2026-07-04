import { AutoModeConfig, api, WorkerTunableProfilePayload } from "../api/client";
import {
  AlgorithmOption,
  ALGORITHM_OPTIONS,
  clampConcurrency,
  clampDeltaRounds,
  clampTotalTrials,
  clampTrialMemoryGb,
  clampTrialThreads,
  DEFAULT_ALGORITHM,
  DEFAULT_DELTA_ROUNDS,
  DEFAULT_LIMIT_SECONDS,
  DEFAULT_AUTO_TOTAL_TRIALS,
  DEFAULT_TOTAL_TRIALS,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
  DEFAULT_INCLUDE_BASE_BENCHMARK,
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

const LEGACY_STORAGE_KEY = "effortless:per-worker-tunable:v1";

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
  includeBaseBenchmark: boolean;
  deltaRounds: number;
}

interface StoredPerWorkerTunables {
  version: 1;
  byWorkerName: Record<string, WorkerTunableDefaults>;
  byWorkerId: Record<string, WorkerTunableDefaults>;
}

let serverCache: StoredPerWorkerTunables = emptyStore();
let hydratePromise: Promise<void> | null = null;

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
  const parsed = raw as Partial<WorkerTunableDefaults> & Partial<WorkerTunableProfilePayload>;
  const selectedParamsRaw = parsed.selectedParams ?? parsed.selected_params;
  if (!Array.isArray(selectedParamsRaw)) return null;
  const selectedParams = selectedParamsRaw.filter(
    (param): param is string => typeof param === "string" && param.length > 0,
  );
  if (selectedParams.length === 0) return null;

  const intervalsRaw = parsed.paramIntervals ?? parsed.param_intervals;
  const paramIntervals: Record<string, ParamInterval> = {};
  if (intervalsRaw && typeof intervalsRaw === "object") {
    for (const [name, interval] of Object.entries(intervalsRaw)) {
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
    limitSeconds: Math.max(
      60,
      Math.round(Number(parsed.limitSeconds ?? parsed.limit_seconds) || DEFAULT_LIMIT_SECONDS),
    ),
    trialThreads: clampTrialThreads(
      Number(parsed.trialThreads ?? parsed.trial_threads) || DEFAULT_TRIAL_THREADS,
    ),
    trialMemoryGb: clampTrialMemoryGb(
      Number(parsed.trialMemoryGb ?? parsed.trial_memory_gb) || DEFAULT_TRIAL_MEMORY_GB,
    ),
    trialCount: clampTotalTrials(
      Number(parsed.trialCount ?? parsed.trial_count) || DEFAULT_TOTAL_TRIALS,
    ),
    includeBaseBenchmark:
      parsed.includeBaseBenchmark ??
      parsed.include_base_benchmark ??
      DEFAULT_INCLUDE_BASE_BENCHMARK,
    deltaRounds: clampDeltaRounds(
      Number(parsed.deltaRounds ?? parsed.delta_rounds) || DEFAULT_DELTA_ROUNDS,
    ),
  };
}

function emptyStore(): StoredPerWorkerTunables {
  return { version: 1, byWorkerName: {}, byWorkerId: {} };
}

function loadLegacyLocalStore(): StoredPerWorkerTunables {
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY);
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

function workerNameKey(workerName: string | undefined | null): string | null {
  const trimmed = workerName?.trim();
  return trimmed ? trimmed : null;
}

function profileToPayload(profile: WorkerTunableDefaults): WorkerTunableProfilePayload {
  return {
    tool: profile.tool,
    selected_params: [...profile.selectedParams],
    param_intervals: { ...profile.paramIntervals },
    algorithm: profile.algorithm,
    concurrency: profile.concurrency,
    limit_seconds: profile.limitSeconds,
    trial_threads: profile.trialThreads,
    trial_memory_gb: profile.trialMemoryGb,
    trial_count: profile.trialCount,
    include_base_benchmark: profile.includeBaseBenchmark,
    delta_rounds: profile.deltaRounds,
  };
}

function applyProfileToCache(
  worker: { id: string; name?: string | null },
  profile: WorkerTunableDefaults,
): void {
  const nameKey = workerNameKey(worker.name);
  if (nameKey) {
    serverCache.byWorkerName[nameKey] = profile;
    const lower = nameKey.toLowerCase();
    const matched = Object.keys(serverCache.byWorkerName).find((key) => key.toLowerCase() === lower);
    if (matched && matched !== nameKey) {
      delete serverCache.byWorkerName[matched];
    }
  }
  if (worker.id) {
    serverCache.byWorkerId[worker.id] = profile;
  }
}

function applyServerListToCache(
  items: Array<{
    worker_id: string;
    worker_name: string;
    profile: WorkerTunableProfilePayload;
  }>,
): void {
  serverCache = emptyStore();
  for (const item of items) {
    const profile = normalizeProfile(item.profile);
    if (!profile) continue;
    applyProfileToCache({ id: item.worker_id, name: item.worker_name }, profile);
  }
}

async function migrateLegacyLocalStoreIfNeeded(): Promise<void> {
  const legacy = loadLegacyLocalStore();
  const hasLegacy =
    Object.keys(legacy.byWorkerId).length > 0 || Object.keys(legacy.byWorkerName).length > 0;
  if (!hasLegacy) return;

  const serverList = await api.listWorkerTunableDefaults();
  if (serverList.items.length > 0) {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    return;
  }

  const workers = await api.listWorkers();
  const items: Array<{ worker_id?: string; worker_name?: string; profile: WorkerTunableProfilePayload }> =
    [];

  for (const worker of workers) {
    const profile =
      legacy.byWorkerId[worker.id] ??
      legacy.byWorkerName[worker.name] ??
      Object.entries(legacy.byWorkerName).find(
        ([name]) => name.toLowerCase() === worker.name.toLowerCase(),
      )?.[1];
    if (profile) {
      items.push({ worker_id: worker.id, profile: profileToPayload(profile) });
    }
  }

  if (items.length > 0) {
    await api.bulkSaveWorkerTunableDefaults(items);
  }
  localStorage.removeItem(LEGACY_STORAGE_KEY);
}

export function ensureWorkerTunablesHydrated(): Promise<void> {
  if (hydratePromise) return hydratePromise;
  hydratePromise = (async () => {
    try {
      await migrateLegacyLocalStoreIfNeeded();
      const response = await api.listWorkerTunableDefaults();
      applyServerListToCache(response.items);
    } catch {
      serverCache = loadLegacyLocalStore();
    }
  })();
  return hydratePromise;
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
    includeBaseBenchmark: assignment.includeBaseBenchmark,
    deltaRounds: assignment.deltaRounds,
  };
}

export function saveWorkerTunableDefaults(
  worker: { id: string; name?: string | null },
  assignment: WorkerAssignment,
): void {
  if (assignment.autoManaged || assignment.selectedParams.length === 0) return;
  const profile = profileFromAssignment(assignment);
  applyProfileToCache(worker, profile);
  void api.saveWorkerTunableDefaults(worker.id, profileToPayload(profile)).catch(() => {
    // Keep in-memory cache; server may be temporarily unavailable.
  });
}

export function getWorkerTunableDefaults(
  worker: { id: string; name?: string | null },
  tool?: string,
): WorkerTunableDefaults | null {
  const toolKey = tool?.toLowerCase().trim();
  const nameKey = workerNameKey(worker.name);
  const candidates: WorkerTunableDefaults[] = [];
  if (nameKey && serverCache.byWorkerName[nameKey]) {
    candidates.push(serverCache.byWorkerName[nameKey]);
  } else if (nameKey) {
    const lower = nameKey.toLowerCase();
    const matched = Object.entries(serverCache.byWorkerName).find(
      ([key]) => key.toLowerCase() === lower,
    );
    if (matched) candidates.push(matched[1]);
  }
  if (worker.id && serverCache.byWorkerId[worker.id]) {
    candidates.push(serverCache.byWorkerId[worker.id]);
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
  | "includeBaseBenchmark"
  | "deltaRounds"
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
      includeBaseBenchmark: DEFAULT_INCLUDE_BASE_BENCHMARK,
      deltaRounds: DEFAULT_DELTA_ROUNDS,
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
    includeBaseBenchmark: saved?.includeBaseBenchmark ?? DEFAULT_INCLUDE_BASE_BENCHMARK,
    deltaRounds: saved?.deltaRounds ?? DEFAULT_DELTA_ROUNDS,
  };
}

export async function syncPerWorkerTunablesFromAutoConfig(config: AutoModeConfig): Promise<void> {
  if (config.params.length === 0) return;

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
  const algorithms = workerAlgorithmsFromAutoConfig(config);
  const trialThreads = workerTrialThreadsFromAutoConfig(config);
  const trialMemoryGb = workerTrialMemoryGbFromAutoConfig(config);
  const concurrency = workerConcurrencyFromAutoConfig(config);
  const limitSeconds = workerLimitSecondsFromAutoConfig(config);
  const trialCounts = workerTrialCountsFromAutoConfig(config);

  let workers: Array<{ id: string; name: string }> = [];
  try {
    workers = await api.listWorkers();
  } catch {
    workers = [];
  }

  const workerByName = new Map(
    workers.map((worker) => [worker.name.toLowerCase(), worker]),
  );

  const items: Array<{ worker_id?: string; worker_name: string; profile: WorkerTunableProfilePayload }> =
    [];

  for (const workerName of config.worker_names) {
    const profile: WorkerTunableDefaults = {
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
      includeBaseBenchmark: DEFAULT_INCLUDE_BASE_BENCHMARK,
      deltaRounds: DEFAULT_DELTA_ROUNDS,
    };

    const worker = workerByName.get(workerName.toLowerCase());
    if (worker) {
      applyProfileToCache(worker, profile);
    }
    items.push({
      worker_id: worker?.id,
      worker_name: workerName,
      profile: profileToPayload(profile),
    });
  }

  try {
    if (items.length > 0) {
      const saved = await api.bulkSaveWorkerTunableDefaults(items);
      applyServerListToCache(saved.items);
    }
  } catch {
    // Cache already updated locally for known workers.
  }
}
