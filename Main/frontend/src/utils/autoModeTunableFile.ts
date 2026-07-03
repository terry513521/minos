import { AlgorithmOption } from "../types/workerAssignment";
import { getToolOptions, parseToolOptionValue, setToolOptions } from "./confEdit";
import { confToDotConf, downloadConfFile } from "./confDisplay";
import { ParamInterval } from "./paramBounds";

export const AUTO_MODE_TUNABLE_FILE_KIND = "minos-auto-mode-tunable";
export const AUTO_MODE_TUNABLE_FILE_VERSION = 1;

export interface AutoModeTunableSettingsFile {
  kind: typeof AUTO_MODE_TUNABLE_FILE_KIND;
  version: number;
  tool: string;
  params: string[];
  param_intervals: Record<string, ParamInterval>;
  worker_algorithms: Record<string, AlgorithmOption>;
  worker_trial_threads: Record<string, number>;
  worker_trial_memory_gb: Record<string, number>;
  worker_concurrency: Record<string, number>;
  base_conf: Record<string, unknown>;
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

export function buildAutoModeTunableSettingsFile(input: {
  tool: string;
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
  workerAlgorithms: Record<string, AlgorithmOption>;
  workerTrialThreads: Record<string, number>;
  workerTrialMemoryGb: Record<string, number>;
  workerConcurrency: Record<string, number>;
  baseConf: Record<string, unknown>;
}): AutoModeTunableSettingsFile {
  return {
    kind: AUTO_MODE_TUNABLE_FILE_KIND,
    version: AUTO_MODE_TUNABLE_FILE_VERSION,
    tool: input.tool,
    params: [...input.params],
    param_intervals: { ...input.paramIntervals },
    worker_algorithms: { ...input.workerAlgorithms },
    worker_trial_threads: { ...input.workerTrialThreads },
    worker_trial_memory_gb: { ...input.workerTrialMemoryGb },
    worker_concurrency: { ...input.workerConcurrency },
    base_conf: structuredClone(input.baseConf),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function parseParamIntervals(
  raw: unknown,
): Record<string, ParamInterval> | null {
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

export function parseAutoModeTunableSettingsFile(
  text: string,
): { ok: true; file: AutoModeTunableSettingsFile } | { ok: false; error: string } {
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

  if (parsed.kind !== AUTO_MODE_TUNABLE_FILE_KIND) {
    return { ok: false, error: "Unrecognized settings file (missing minos-auto-mode-tunable kind)" };
  }

  if (parsed.version !== AUTO_MODE_TUNABLE_FILE_VERSION) {
    return {
      ok: false,
      error: `Unsupported settings version ${String(parsed.version)} (expected ${AUTO_MODE_TUNABLE_FILE_VERSION})`,
    };
  }

  if (typeof parsed.tool !== "string" || !parsed.tool.trim()) {
    return { ok: false, error: "Settings file is missing tool" };
  }

  if (!Array.isArray(parsed.params) || !parsed.params.every((p) => typeof p === "string")) {
    return { ok: false, error: "Settings file params must be a string array" };
  }

  const paramIntervals = parseParamIntervals(parsed.param_intervals);
  if (!paramIntervals) {
    return { ok: false, error: "Settings file param_intervals are invalid" };
  }

  const workerAlgorithms = parseStringStringRecord(parsed.worker_algorithms);
  if (!workerAlgorithms) {
    return { ok: false, error: "Settings file worker_algorithms are invalid" };
  }

  const workerTrialThreads = parseStringNumberRecord(parsed.worker_trial_threads);
  if (!workerTrialThreads) {
    return { ok: false, error: "Settings file worker_trial_threads are invalid" };
  }

  const workerTrialMemoryGb = parseStringNumberRecord(parsed.worker_trial_memory_gb);
  if (!workerTrialMemoryGb) {
    return { ok: false, error: "Settings file worker_trial_memory_gb are invalid" };
  }

  const workerConcurrency = parseStringNumberRecord(parsed.worker_concurrency);
  if (!workerConcurrency) {
    return { ok: false, error: "Settings file worker_concurrency are invalid" };
  }

  if (!isRecord(parsed.base_conf)) {
    return { ok: false, error: "Settings file base_conf must be an object" };
  }

  return {
    ok: true,
    file: {
      kind: AUTO_MODE_TUNABLE_FILE_KIND,
      version: AUTO_MODE_TUNABLE_FILE_VERSION,
      tool: parsed.tool.trim(),
      params: [...parsed.params],
      param_intervals: paramIntervals,
      worker_algorithms: workerAlgorithms as Record<string, AlgorithmOption>,
      worker_trial_threads: workerTrialThreads,
      worker_trial_memory_gb: workerTrialMemoryGb,
      worker_concurrency: workerConcurrency,
      base_conf: structuredClone(parsed.base_conf),
    },
  };
}

export type AutoModeTunableImportResult =
  | { kind: "settings"; file: AutoModeTunableSettingsFile }
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
    const settings = parseAutoModeTunableSettingsFile(text);
    if (settings.ok) {
      if (settings.file.tool !== tool) {
        return {
          ok: false,
          error: `Settings file tool is ${settings.file.tool}; this panel is for ${tool}`,
        };
      }
      return { ok: true, result: { kind: "settings", file: settings.file } };
    }

    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return settings;
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

    return settings;
  }

  const merged = mergeDotConfIntoBase(currentBaseConf, tool, text);
  return { ok: true, result: { kind: "conf", baseConf: merged } };
}

export function downloadAutoModeTunableConf(
  baseConf: Record<string, unknown>,
  fileName = "auto-mode-tunable",
): void {
  downloadConfFile(baseConf, fileName);
}

export function downloadAutoModeTunableSettings(file: AutoModeTunableSettingsFile): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "auto-mode-tunable.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

export function autoModeTunableConfPreview(baseConf: Record<string, unknown>): string {
  return confToDotConf(baseConf);
}
