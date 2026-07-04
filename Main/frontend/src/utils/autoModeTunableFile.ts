import { AlgorithmOption, adaptiveMaxTrialsFromTotal, clampTotalTrials, DEFAULT_AUTO_TOTAL_TRIALS } from "../types/workerAssignment";
import { getToolOptions, parseToolOptionValue, setToolOptions } from "./confEdit";
import { confToDotConf, downloadConfFile } from "./confDisplay";
import { clampParamInterval, ParamInterval, buildToolReferenceConf } from "./paramBounds";

export const AUTO_MODE_TUNABLE_FILE_KIND = "minos-auto-mode-tunable";
export const AUTO_MODE_TUNABLE_FILE_VERSION = 1;

/** Legacy intervals-only exports; import still accepted. */
export const AUTO_MODE_INTERVALS_FILE_KIND = "minos-auto-mode-intervals";
export const AUTO_MODE_INTERVALS_FILE_VERSION = 1;

export interface AutoModeTunableFile {
  kind: typeof AUTO_MODE_TUNABLE_FILE_KIND;
  version: number;
  tool: string;
  params: string[];
  param_intervals: Record<string, ParamInterval>;
  base_conf: Record<string, unknown>;
  worker_algorithms: Record<string, AlgorithmOption>;
  worker_trial_threads: Record<string, number>;
  worker_trial_memory_gb: Record<string, number>;
  worker_concurrency: Record<string, number>;
  worker_limit_seconds: Record<string, number>;
  worker_adaptive_max_trials: Record<string, number>;
  /** Miner-style key=value lines for the full base conf (export convenience). */
  conf_dot: string;
}

export interface AutoModeTunableImportData {
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
  baseConf?: Record<string, unknown>;
  workerAlgorithms?: Record<string, AlgorithmOption>;
  workerTrialThreads?: Record<string, number>;
  workerTrialMemoryGb?: Record<string, number>;
  workerConcurrency?: Record<string, number>;
  workerLimitSeconds?: Record<string, number>;
  workerTrialCounts?: Record<string, number>;
}

export function parseDotConfText(text: string): Record<string, string> {
  const options: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!key) continue;
    options[key] = trimmed.slice(eq + 1).trim();
  }
  return options;
}

export function parseDotConfForTool(text: string, tool: string): Record<string, unknown> {
  const raw = parseDotConfText(text);
  const parsed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    parsed[key] = parseToolOptionValue(tool, key, value);
  }
  return parsed;
}

export function mergeDotConfIntoBase(
  baseConf: Record<string, unknown>,
  tool: string,
  dotConfText: string,
): Record<string, unknown> {
  const imported = parseDotConfForTool(dotConfText, tool);
  const existing = getToolOptions(baseConf, tool);
  return setToolOptions(baseConf, tool, { ...existing, ...imported });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function parseParamIntervals(raw: unknown): Record<string, ParamInterval> | null {
  if (!isRecord(raw)) return null;
  const intervals: Record<string, ParamInterval> = {};
  for (const [name, value] of Object.entries(raw)) {
    if (!isRecord(value)) return null;
    const interval: ParamInterval = {};
    if (value.min != null) {
      const min = typeof value.min === "number" ? value.min : Number(value.min);
      if (!Number.isFinite(min)) return null;
      interval.min = min;
    }
    if (value.max != null) {
      const max = typeof value.max === "number" ? value.max : Number(value.max);
      if (!Number.isFinite(max)) return null;
      interval.max = max;
    }
    if (value.step != null) {
      const step = typeof value.step === "number" ? value.step : Number(value.step);
      if (!Number.isFinite(step)) return null;
      interval.step = step;
    }
    const values = value.values;
    if (Array.isArray(values)) {
      interval.values = values.map(String);
    }
    intervals[name] = interval;
  }
  return intervals;
}

function parseStringNumberRecord(raw: unknown): Record<string, number> | null {
  if (!isRecord(raw)) return null;
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(raw)) {
    const num = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(num)) return null;
    out[key] = num;
  }
  return out;
}

function parseStringStringRecord(raw: unknown): Record<string, string> | null {
  if (!isRecord(raw)) return null;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "string") return null;
    out[key] = value;
  }
  return out;
}

export function normalizeImportedIntervals(
  tool: string,
  params: string[],
  paramIntervals: Record<string, ParamInterval>,
): Record<string, ParamInterval> {
  const out: Record<string, ParamInterval> = {};
  for (const param of params) {
    out[param] = clampParamInterval(tool, param, paramIntervals[param] ?? {});
  }
  return out;
}

function pickWorkerRecord<T>(
  workerNames: string[],
  record: Record<string, T>,
  fallback: T,
): Record<string, T> {
  return Object.fromEntries(workerNames.map((name) => [name, record[name] ?? fallback]));
}

export function buildAutoModeTunableFile(input: {
  tool: string;
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
  baseConf: Record<string, unknown>;
  workerNames: string[];
  workerAlgorithms: Record<string, AlgorithmOption>;
  workerTrialThreads: Record<string, number>;
  workerTrialMemoryGb: Record<string, number>;
  workerConcurrency: Record<string, number>;
  workerLimitSeconds: Record<string, number>;
  workerTrialCounts: Record<string, number>;
}): AutoModeTunableFile {
  const param_intervals: Record<string, ParamInterval> = {};
  for (const param of input.params) {
    const interval = input.paramIntervals[param];
    if (!interval) continue;
    param_intervals[param] = { ...interval };
  }

  const base_conf = structuredClone(input.baseConf);

  return {
    kind: AUTO_MODE_TUNABLE_FILE_KIND,
    version: AUTO_MODE_TUNABLE_FILE_VERSION,
    tool: input.tool,
    params: [...input.params],
    param_intervals,
    base_conf,
    worker_algorithms: pickWorkerRecord(
      input.workerNames,
      input.workerAlgorithms,
      "optuna",
    ) as Record<string, AlgorithmOption>,
    worker_trial_threads: pickWorkerRecord(input.workerNames, input.workerTrialThreads, 4),
    worker_trial_memory_gb: pickWorkerRecord(input.workerNames, input.workerTrialMemoryGb, 6),
    worker_concurrency: pickWorkerRecord(input.workerNames, input.workerConcurrency, 1),
    worker_limit_seconds: pickWorkerRecord(input.workerNames, input.workerLimitSeconds, 3000),
    worker_adaptive_max_trials: Object.fromEntries(
      input.workerNames.map((name) => [
        name,
        adaptiveMaxTrialsFromTotal(input.workerTrialCounts[name] ?? DEFAULT_AUTO_TOTAL_TRIALS),
      ]),
    ),
    conf_dot: confToDotConf(base_conf),
  };
}

function parseTunablePayload(
  parsed: Record<string, unknown>,
  tool: string,
  requireFull: boolean,
): { ok: true; data: AutoModeTunableImportData } | { ok: false; error: string } {
  const fileTool = typeof parsed.tool === "string" ? parsed.tool.trim() : tool;
  if (fileTool !== tool) {
    return {
      ok: false,
      error: `File tool is ${fileTool}; this panel is for ${tool}`,
    };
  }

  const paramsRaw = parsed.params;
  if (!Array.isArray(paramsRaw) || !paramsRaw.every((p) => typeof p === "string")) {
    return { ok: false, error: "File params must be a string array" };
  }
  const params = [...paramsRaw];
  if (params.length === 0) {
    return { ok: false, error: "File must include at least one tune parameter" };
  }

  const paramIntervals = parseParamIntervals(parsed.param_intervals);
  if (!paramIntervals) {
    return { ok: false, error: "File param_intervals are invalid (expected min, max, step)" };
  }

  const missing = params.filter((param) => !(param in paramIntervals));
  if (missing.length > 0) {
    return {
      ok: false,
      error: `Missing intervals for: ${missing.slice(0, 3).join(", ")}${
        missing.length > 3 ? ` (+${missing.length - 3} more)` : ""
      }`,
    };
  }

  let baseConf: Record<string, unknown> | undefined;
  if (isRecord(parsed.base_conf)) {
    baseConf = structuredClone(parsed.base_conf);
  } else if (typeof parsed.conf_dot === "string" && parsed.conf_dot.trim()) {
    baseConf = mergeDotConfIntoBase(buildToolReferenceConf(tool), tool, parsed.conf_dot);
  }

  if (requireFull && !baseConf) {
    return { ok: false, error: "File must include base_conf (full GATK conf)" };
  }

  const workerAlgorithms = parseStringStringRecord(parsed.worker_algorithms);
  const workerTrialThreads = parseStringNumberRecord(parsed.worker_trial_threads);
  const workerTrialMemoryGb = parseStringNumberRecord(parsed.worker_trial_memory_gb);
  const workerConcurrency = parseStringNumberRecord(parsed.worker_concurrency);
  const workerLimitSeconds = parseStringNumberRecord(parsed.worker_limit_seconds);
  const workerAdaptiveMaxTrials = parseStringNumberRecord(parsed.worker_adaptive_max_trials);

  if (requireFull) {
    if (!workerAlgorithms) {
      return { ok: false, error: "File worker_algorithms are invalid" };
    }
    if (!workerTrialThreads) {
      return { ok: false, error: "File worker_trial_threads are invalid" };
    }
    if (!workerTrialMemoryGb) {
      return { ok: false, error: "File worker_trial_memory_gb are invalid" };
    }
    if (!workerConcurrency) {
      return { ok: false, error: "File worker_concurrency are invalid" };
    }
  }

  const data: AutoModeTunableImportData = {
    params,
    paramIntervals: normalizeImportedIntervals(tool, params, paramIntervals),
    baseConf,
    workerAlgorithms: workerAlgorithms as Record<string, AlgorithmOption> | undefined,
    workerTrialThreads: workerTrialThreads ?? undefined,
    workerTrialMemoryGb: workerTrialMemoryGb ?? undefined,
    workerConcurrency: workerConcurrency ?? undefined,
    workerLimitSeconds: workerLimitSeconds ?? undefined,
    workerTrialCounts: workerAdaptiveMaxTrials
      ? Object.fromEntries(
          Object.entries(workerAdaptiveMaxTrials).map(([name, adaptive]) => [
            name,
            clampTotalTrials(adaptive + 1),
          ]),
        )
      : undefined,
  };

  return { ok: true, data };
}

export function parseAutoModeTunableFile(
  text: string,
  tool: string,
): { ok: true; data: AutoModeTunableImportData } | { ok: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Invalid JSON",
    };
  }

  if (!isRecord(parsed)) {
    return { ok: false, error: "Settings file must be a JSON object" };
  }

  const kind = parsed.kind;
  if (
    kind != null &&
    kind !== AUTO_MODE_TUNABLE_FILE_KIND &&
    kind !== AUTO_MODE_INTERVALS_FILE_KIND
  ) {
    return { ok: false, error: `Unrecognized file kind: ${String(kind)}` };
  }

  if (
    parsed.version != null &&
    parsed.version !== AUTO_MODE_TUNABLE_FILE_VERSION &&
    parsed.version !== AUTO_MODE_INTERVALS_FILE_VERSION
  ) {
    return {
      ok: false,
      error: `Unsupported file version ${String(parsed.version)}`,
    };
  }

  const requireFull = kind === AUTO_MODE_TUNABLE_FILE_KIND;
  return parseTunablePayload(parsed, tool, requireFull);
}

export type AutoModeTunableImportResult =
  | { kind: "tunable"; data: AutoModeTunableImportData }
  | { kind: "conf"; baseConf: Record<string, unknown> };

export function parseAutoModeTunableImport(
  text: string,
  tool: string,
  currentBaseConf: Record<string, unknown>,
): { ok: true; result: AutoModeTunableImportResult } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) {
    return { ok: false, error: "File is empty" };
  }

  if (trimmed.startsWith("{")) {
    const tunable = parseAutoModeTunableFile(text, tool);
    if (tunable.ok) {
      return { ok: true, result: { kind: "tunable", data: tunable.data } };
    }

    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return tunable;
    }

    if (isRecord(json)) {
      const optionKeys = Object.keys(json).filter((key) => key.endsWith("_options"));
      if (optionKeys.length > 0) {
        return {
          ok: true,
          result: {
            kind: "conf",
            baseConf: structuredClone(json),
          },
        };
      }
    }

    return tunable;
  }

  const merged = mergeDotConfIntoBase(currentBaseConf, tool, text);
  return { ok: true, result: { kind: "conf", baseConf: merged } };
}

export function downloadAutoModeTunableFile(file: AutoModeTunableFile): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const base = file.tool || "auto-mode";
  anchor.download = `${base}-auto-mode-tunable.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function downloadAutoModeTunableConf(
  baseConf: Record<string, unknown>,
  fileName = "auto-mode-tunable",
): void {
  downloadConfFile(baseConf, fileName);
}
