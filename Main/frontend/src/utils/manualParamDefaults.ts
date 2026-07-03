import { AutoModeConfig } from "../api/client";
import { loadAutoModeState } from "./autoModeStorage";
import { syncPerWorkerTunablesFromAutoConfig } from "./workerTunableStorage";
import {
  paramIntervalsFromAutoConfig,
  workerAlgorithmsFromAutoConfig,
  workerTrialMemoryGbFromAutoConfig,
  workerTrialThreadsFromAutoConfig,
  workerConcurrencyFromAutoConfig,
} from "./autoModeSync";
import { clampParamInterval, defaultParamInterval, ParamInterval } from "./paramBounds";
import {
  AlgorithmOption,
  ALGORITHM_OPTIONS,
  clampTotalTrials,
  clampTrialMemoryGb,
  clampTrialThreads,
  clampConcurrency,
  DEFAULT_ALGORITHM,
  DEFAULT_LIMIT_SECONDS,
  DEFAULT_TOTAL_TRIALS,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
} from "../types/workerAssignment";

const STORAGE_KEY_V2 = "effortless:manual-worker-defaults:v2";
const STORAGE_KEY_V1 = "effortless:manual-param-defaults:v1";

export interface ManualWorkerDefaults {
  tool: string;
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
  workerAlgorithms: Record<string, AlgorithmOption>;
  workerTrialThreads: Record<string, number>;
  workerTrialMemoryGb: Record<string, number>;
  workerConcurrency: Record<string, number>;
  limitSeconds: number;
  trialCount: number;
  concurrency: number;
}

function trialCountFromAutoConfig(config: AutoModeConfig): number {
  return clampTotalTrials(config.adaptive_max_trials + 1);
}

export function manualWorkerDefaultsFromAutoConfig(config: AutoModeConfig): ManualWorkerDefaults {
  return {
    tool: config.tool.toLowerCase().trim(),
    params: [...config.params],
    paramIntervals: paramIntervalsFromAutoConfig(config),
    workerAlgorithms: workerAlgorithmsFromAutoConfig(config),
    workerTrialThreads: workerTrialThreadsFromAutoConfig(config),
    workerTrialMemoryGb: workerTrialMemoryGbFromAutoConfig(config),
    workerConcurrency: workerConcurrencyFromAutoConfig(config),
    limitSeconds: config.limit_seconds || DEFAULT_LIMIT_SECONDS,
    trialCount: trialCountFromAutoConfig(config),
    concurrency: config.concurrency || 1,
  };
}

function normalizeAlgorithm(raw: string | undefined): AlgorithmOption {
  if (raw && ALGORITHM_OPTIONS.includes(raw as AlgorithmOption)) {
    return raw as AlgorithmOption;
  }
  return DEFAULT_ALGORITHM;
}

function resolveWorkerMapValue<T>(
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

function parseLegacyDefaults(raw: unknown): ManualWorkerDefaults | null {
  if (!raw || typeof raw !== "object") return null;
  const parsed = raw as Partial<ManualWorkerDefaults>;
  if (!Array.isArray(parsed.params) || parsed.params.length === 0) return null;
  if (typeof parsed.tool !== "string" || !parsed.tool.trim()) return null;
  return {
    tool: parsed.tool.toLowerCase().trim(),
    params: parsed.params.filter((p): p is string => typeof p === "string" && p.length > 0),
    paramIntervals:
      parsed.paramIntervals && typeof parsed.paramIntervals === "object"
        ? (parsed.paramIntervals as Record<string, ParamInterval>)
        : {},
    workerAlgorithms:
      parsed.workerAlgorithms && typeof parsed.workerAlgorithms === "object"
        ? Object.fromEntries(
            Object.entries(parsed.workerAlgorithms).map(([name, algorithm]) => [
              name,
              normalizeAlgorithm(String(algorithm)),
            ]),
          )
        : {},
    workerTrialThreads:
      parsed.workerTrialThreads && typeof parsed.workerTrialThreads === "object"
        ? Object.fromEntries(
            Object.entries(parsed.workerTrialThreads).map(([name, value]) => [
              name,
              clampTrialThreads(Number(value) || DEFAULT_TRIAL_THREADS),
            ]),
          )
        : {},
    workerTrialMemoryGb:
      parsed.workerTrialMemoryGb && typeof parsed.workerTrialMemoryGb === "object"
        ? Object.fromEntries(
            Object.entries(parsed.workerTrialMemoryGb).map(([name, value]) => [
              name,
              clampTrialMemoryGb(Number(value) || DEFAULT_TRIAL_MEMORY_GB),
            ]),
          )
        : {},
    workerConcurrency:
      parsed.workerConcurrency && typeof parsed.workerConcurrency === "object"
        ? Object.fromEntries(
            Object.entries(parsed.workerConcurrency).map(([name, value]) => [
              name,
              clampConcurrency(Number(value) || 1),
            ]),
          )
        : {},
    limitSeconds: Math.max(
      60,
      Math.round(Number(parsed.limitSeconds) || DEFAULT_LIMIT_SECONDS),
    ),
    trialCount: clampTotalTrials(Number(parsed.trialCount) || DEFAULT_TOTAL_TRIALS),
    concurrency: Math.max(1, Math.round(Number(parsed.concurrency) || 1)),
  };
}

export function loadManualWorkerDefaults(): ManualWorkerDefaults | null {
  try {
    const rawV2 = localStorage.getItem(STORAGE_KEY_V2);
    if (rawV2) {
      return parseLegacyDefaults(JSON.parse(rawV2));
    }
    const rawV1 = localStorage.getItem(STORAGE_KEY_V1);
    if (rawV1) {
      return parseLegacyDefaults(JSON.parse(rawV1));
    }
    return null;
  } catch {
    return null;
  }
}

/** Prefer saved manual defaults; fall back to cached auto-mode config from local storage. */
export function getEffectiveManualWorkerDefaults(): ManualWorkerDefaults | null {
  const saved = loadManualWorkerDefaults();
  if (saved) return saved;
  const cachedConfig = loadAutoModeState()?.status?.config;
  if (!cachedConfig || cachedConfig.params.length === 0) return null;
  return manualWorkerDefaultsFromAutoConfig(cachedConfig);
}

/** Seed manual defaults from cached auto-mode config when dedicated defaults are missing. */
export function ensureManualDefaultsHydrated(): ManualWorkerDefaults | null {
  const saved = loadManualWorkerDefaults();
  if (saved) return saved;
  const cachedConfig = loadAutoModeState()?.status?.config;
  if (!cachedConfig || cachedConfig.params.length === 0) return null;
  const effective = manualWorkerDefaultsFromAutoConfig(cachedConfig);
  saveManualWorkerDefaults(effective);
  syncPerWorkerTunablesFromAutoConfig(cachedConfig);
  return effective;
}

export function saveManualWorkerDefaults(defaults: ManualWorkerDefaults): void {
  try {
    localStorage.setItem(
      STORAGE_KEY_V2,
      JSON.stringify({
        tool: defaults.tool.toLowerCase().trim(),
        params: defaults.params,
        paramIntervals: defaults.paramIntervals,
        workerAlgorithms: defaults.workerAlgorithms,
        workerTrialThreads: defaults.workerTrialThreads,
        workerTrialMemoryGb: defaults.workerTrialMemoryGb,
        workerConcurrency: defaults.workerConcurrency,
        limitSeconds: defaults.limitSeconds,
        trialCount: defaults.trialCount,
        concurrency: defaults.concurrency,
      }),
    );
  } catch {
    // Ignore quota / private-mode errors.
  }
}

/** Keep manual worker-card defaults aligned with saved auto-mode tunable config. */
export function syncManualParamDefaultsFromAutoConfig(config: AutoModeConfig): void {
  if (config.params.length === 0) return;
  saveManualWorkerDefaults(manualWorkerDefaultsFromAutoConfig(config));
  void syncPerWorkerTunablesFromAutoConfig(config);
}

/** @deprecated Use loadManualWorkerDefaults */
export function loadManualParamDefaults(): ManualWorkerDefaults | null {
  return loadManualWorkerDefaults();
}

/** @deprecated Use saveManualWorkerDefaults */
export function saveManualParamDefaults(defaults: ManualWorkerDefaults): void {
  saveManualWorkerDefaults(defaults);
}

/** @deprecated Use manualWorkerDefaultsFromAutoConfig */
export function manualParamDefaultsFromAutoConfig(config: AutoModeConfig): ManualWorkerDefaults {
  return manualWorkerDefaultsFromAutoConfig(config);
}

export function workerDefaultAlgorithm(workerName: string): AlgorithmOption {
  const saved = getEffectiveManualWorkerDefaults();
  return normalizeAlgorithm(resolveWorkerMapValue(saved?.workerAlgorithms, workerName));
}

export function workerDefaultTrialThreads(workerName: string): number {
  const saved = getEffectiveManualWorkerDefaults();
  const value = resolveWorkerMapValue(saved?.workerTrialThreads, workerName);
  return clampTrialThreads(value ?? DEFAULT_TRIAL_THREADS);
}

export function workerDefaultTrialMemoryGb(workerName: string): number {
  const saved = getEffectiveManualWorkerDefaults();
  const value = resolveWorkerMapValue(saved?.workerTrialMemoryGb, workerName);
  return clampTrialMemoryGb(value ?? DEFAULT_TRIAL_MEMORY_GB);
}

export function workerDefaultConcurrency(workerName: string): number {
  const saved = getEffectiveManualWorkerDefaults();
  const perWorker = resolveWorkerMapValue(saved?.workerConcurrency, workerName);
  if (perWorker != null) return clampConcurrency(perWorker);
  return clampConcurrency(saved?.concurrency ?? 1);
}

export function savedDefaultLimitSeconds(): number {
  const saved = getEffectiveManualWorkerDefaults();
  return saved?.limitSeconds ?? DEFAULT_LIMIT_SECONDS;
}

export function savedDefaultTrialCount(): number {
  const saved = getEffectiveManualWorkerDefaults();
  return saved?.trialCount ?? DEFAULT_TOTAL_TRIALS;
}

export function savedDefaultConcurrency(): number {
  const saved = getEffectiveManualWorkerDefaults();
  return saved?.concurrency ?? 1;
}

export function savedDefaultSelectedParams(tool: string, available: string[]): string[] {
  const availableSet = new Set(available);
  const toolKey = tool.toLowerCase().trim();
  const saved = getEffectiveManualWorkerDefaults();
  if (saved && saved.tool === toolKey) {
    const fromSaved = saved.params.filter((param) => availableSet.has(param));
    if (fromSaved.length > 0) return fromSaved;
  }
  return [];
}

export function buildSelectedParamIntervals(
  tool: string,
  baseConf: Record<string, unknown>,
  paramNames: string[],
): Record<string, ParamInterval> {
  const toolKey = tool.toLowerCase().trim();
  const saved = getEffectiveManualWorkerDefaults();
  const useSaved = saved?.tool === toolKey;
  const intervals: Record<string, ParamInterval> = {};

  for (const param of paramNames) {
    const options = baseConf[`${toolKey}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";
    const savedInterval = useSaved ? saved?.paramIntervals[param] : undefined;
    intervals[param] = savedInterval
      ? clampParamInterval(toolKey, param, savedInterval)
      : defaultParamInterval(toolKey, param, baseValue);
  }

  return intervals;
}
