import { AutoModeConfig } from "../api/client";
import { clampParamInterval, defaultParamInterval, ParamInterval } from "./paramBounds";
import { paramIntervalsFromAutoConfig } from "./autoModeSync";

const STORAGE_KEY = "effortless:manual-param-defaults:v1";

export interface ManualParamDefaults {
  tool: string;
  params: string[];
  paramIntervals: Record<string, ParamInterval>;
}

export function manualParamDefaultsFromAutoConfig(config: AutoModeConfig): ManualParamDefaults {
  return {
    tool: config.tool.toLowerCase().trim(),
    params: [...config.params],
    paramIntervals: paramIntervalsFromAutoConfig(config),
  };
}

export function loadManualParamDefaults(): ManualParamDefaults | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ManualParamDefaults>;
    if (!parsed || typeof parsed !== "object") return null;
    if (!Array.isArray(parsed.params) || parsed.params.length === 0) return null;
    if (typeof parsed.tool !== "string" || !parsed.tool.trim()) return null;
    return {
      tool: parsed.tool.toLowerCase().trim(),
      params: parsed.params.filter((p): p is string => typeof p === "string" && p.length > 0),
      paramIntervals:
        parsed.paramIntervals && typeof parsed.paramIntervals === "object"
          ? (parsed.paramIntervals as Record<string, ParamInterval>)
          : {},
    };
  } catch {
    return null;
  }
}

export function saveManualParamDefaults(defaults: ManualParamDefaults): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        tool: defaults.tool.toLowerCase().trim(),
        params: defaults.params,
        paramIntervals: defaults.paramIntervals,
      }),
    );
  } catch {
    // Ignore quota / private-mode errors.
  }
}

/** Keep manual worker-card defaults aligned with saved auto-mode tunable config. */
export function syncManualParamDefaultsFromAutoConfig(config: AutoModeConfig): void {
  if (config.params.length === 0) return;
  saveManualParamDefaults(manualParamDefaultsFromAutoConfig(config));
}

export function buildSelectedParamIntervals(
  tool: string,
  baseConf: Record<string, unknown>,
  paramNames: string[],
): Record<string, ParamInterval> {
  const toolKey = tool.toLowerCase().trim();
  const saved = loadManualParamDefaults();
  const useSaved = saved?.tool === toolKey;
  const intervals: Record<string, ParamInterval> = {};

  for (const param of paramNames) {
    const options = baseConf[`${toolKey}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";
    const savedInterval = useSaved ? saved.paramIntervals[param] : undefined;
    intervals[param] = savedInterval
      ? clampParamInterval(toolKey, param, savedInterval)
      : defaultParamInterval(toolKey, param, baseValue);
  }

  return intervals;
}
