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

export const DEFAULT_DEEPVARIANT_PARAMS = [
  "min_mapping_quality",
  "qual_filter",
  "min_base_quality",
] as const;

const DEFAULT_PARAMS_BY_TOOL: Record<string, readonly string[]> = {
  gatk: DEFAULT_FINE_TUNE_PARAMS,
  deepvariant: DEFAULT_DEEPVARIANT_PARAMS,
};

export function defaultSelectedParams(tool: string, available: string[]): string[] {
  const fromSaved = savedDefaultSelectedParams(tool, available);
  if (fromSaved.length > 0) return fromSaved;

  const availableSet = new Set(available);
  const preferred = DEFAULT_PARAMS_BY_TOOL[tool.toLowerCase()] ?? DEFAULT_FINE_TUNE_PARAMS;
  const matched = preferred.filter((param) => availableSet.has(param));
  if (matched.length > 0) return matched;
  return available.slice(0, 3);
}

export const CANDIDATE_DRAG_MIME = "application/x-effortless-candidate";

export interface CandidateDragPayload {
  index: number;
}
