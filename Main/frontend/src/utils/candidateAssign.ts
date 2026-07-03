import { savedDefaultSelectedParams } from "./manualParamDefaults";

export function toolOptionsKey(tool: string): string {
  return `${tool.toLowerCase().trim()}_options`;
}

export function listToolOptionKeys(
  baseConf: Record<string, unknown>,
  tool: string,
): string[] {
  return listToolOptionEntries(baseConf, tool).map(([name]) => name);
}

export function listToolOptionEntries(
  baseConf: Record<string, unknown>,
  tool: string,
): Array<[string, string]> {
  const options = baseConf[toolOptionsKey(tool)];
  if (!options || typeof options !== "object" || Array.isArray(options)) {
    return [];
  }
  return Object.entries(options as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value]) => [name, String(value)]);
}

export const DEFAULT_FINE_TUNE_PARAMS = [
  "base_quality_score_threshold",
  "contamination_fraction_to_filter",
  "standard_min_confidence_threshold_for_calling",
] as const;

export function defaultSelectedParams(tool: string, available: string[]): string[] {
  const fromSaved = savedDefaultSelectedParams(tool, available);
  if (fromSaved.length > 0) return fromSaved;

  const availableSet = new Set(available);
  return DEFAULT_FINE_TUNE_PARAMS.filter((param) => availableSet.has(param));
}

export const CANDIDATE_DRAG_MIME = "application/x-effortless-candidate";

export interface CandidateDragPayload {
  index: number;
}
