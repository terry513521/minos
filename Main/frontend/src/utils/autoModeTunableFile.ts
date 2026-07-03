import { AlgorithmOption } from "../types/workerAssignment";
import { getToolOptions, parseToolOptionValue, setToolOptions } from "./confEdit";
import { downloadConfFile } from "./confDisplay";
import { clampParamInterval, ParamInterval } from "./paramBounds";

export const AUTO_MODE_INTERVALS_FILE_KIND = "minos-auto-mode-intervals";
export const AUTO_MODE_INTERVALS_FILE_VERSION = 1;

/** @deprecated Legacy full-settings export; import still accepted. */
export const AUTO_MODE_TUNABLE_FILE_KIND = "minos-auto-mode-tunable";
export const AUTO_MODE_TUNABLE_FILE_VERSION = 1;

export interface AutoModeIntervalsFile {
  kind: typeof AUTO_MODE_INTERVALS_FILE_KIND;
  version: number;
  tool: string;
  params: string[];
  param_intervals: Record<string, ParamInterval>;
}

export interface AutoModeIntervalsImport {
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
  baseConf?: Record<string, unknown>;
  workerAlgorithms?: Record<string, AlgorithmOption>;
  workerTrialThreads?: Record<string, number>;
  workerTrialMemoryGb?: Record<string, number>;
  workerConcurrency?: Record<string, number>;
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

export function buildAutoModeIntervalsFile(input: {
  tool: string;
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
}): AutoModeIntervalsFile {
  const param_intervals: Record<string, ParamInterval> = {};
  for (const param of input.params) {
    const interval = input.paramIntervals[param];
    if (!interval) continue;
    param_intervals[param] = { ...interval };
  }
  return {
    kind: AUTO_MODE_INTERVALS_FILE_KIND,
    version: AUTO_MODE_INTERVALS_FILE_VERSION,
    tool: input.tool,
    params: [...input.params],
    param_intervals,
  };
}

function parseIntervalsPayload(
  parsed: Record<string, unknown>,
  tool: string,
): { ok: true; data: AutoModeIntervalsImport } | { ok: false; error: string } {
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

  const data: AutoModeIntervalsImport = {
    params,
    paramIntervals: normalizeImportedIntervals(tool, params, paramIntervals),
  };

  if (isRecord(parsed.base_conf)) {
    data.baseConf = structuredClone(parsed.base_conf);
  }

  const workerAlgorithms = parseStringStringRecord(parsed.worker_algorithms);
  if (workerAlgorithms) {
    data.workerAlgorithms = workerAlgorithms as Record<string, AlgorithmOption>;
  }
  const workerTrialThreads = parseStringNumberRecord(parsed.worker_trial_threads);
  if (workerTrialThreads) data.workerTrialThreads = workerTrialThreads;
  const workerTrialMemoryGb = parseStringNumberRecord(parsed.worker_trial_memory_gb);
  if (workerTrialMemoryGb) data.workerTrialMemoryGb = workerTrialMemoryGb;
  const workerConcurrency = parseStringNumberRecord(parsed.worker_concurrency);
  if (workerConcurrency) data.workerConcurrency = workerConcurrency;

  return { ok: true, data };
}

export function parseAutoModeIntervalsFile(
  text: string,
  tool: string,
): { ok: true; data: AutoModeIntervalsImport } | { ok: false; error: string } {
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
    return { ok: false, error: "Intervals file must be a JSON object" };
  }

  const kind = parsed.kind;
  if (
    kind != null &&
    kind !== AUTO_MODE_INTERVALS_FILE_KIND &&
    kind !== AUTO_MODE_TUNABLE_FILE_KIND
  ) {
    return { ok: false, error: `Unrecognized file kind: ${String(kind)}` };
  }

  if (
    parsed.version != null &&
    parsed.version !== AUTO_MODE_INTERVALS_FILE_VERSION &&
    parsed.version !== AUTO_MODE_TUNABLE_FILE_VERSION
  ) {
    return {
      ok: false,
      error: `Unsupported file version ${String(parsed.version)}`,
    };
  }

  return parseIntervalsPayload(parsed, tool);
}

export type AutoModeTunableImportResult =
  | { kind: "intervals"; data: AutoModeIntervalsImport }
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
    const intervals = parseAutoModeIntervalsFile(text, tool);
    if (intervals.ok) {
      return { ok: true, result: { kind: "intervals", data: intervals.data } };
    }

    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return intervals;
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

    return intervals;
  }

  const merged = mergeDotConfIntoBase(currentBaseConf, tool, text);
  return { ok: true, result: { kind: "conf", baseConf: merged } };
}

export function downloadAutoModeIntervalsFile(file: AutoModeIntervalsFile): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "auto-mode-intervals.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

/** @deprecated Conf export removed from auto mode panel; kept for other callers. */
export function downloadAutoModeTunableConf(
  baseConf: Record<string, unknown>,
  fileName = "auto-mode-tunable",
): void {
  downloadConfFile(baseConf, fileName);
}
