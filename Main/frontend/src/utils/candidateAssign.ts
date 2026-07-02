/** Phase-1 GATK params (docs/config-optimization-plan.md) — pre-selected on assign. */
export const DEFAULT_TUNABLE_PARAMS: Record<string, string[]> = {
  gatk: [
    "pcr_indel_model",
    "standard_min_confidence_threshold_for_calling",
    "min_base_quality_score",
    "min_mapping_quality_score",
  ],
};

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

export function defaultSelectedParams(tool: string, available: string[]): string[] {
  const preferred = DEFAULT_TUNABLE_PARAMS[tool.toLowerCase()] ?? [];
  const picked = preferred.filter((name) => available.includes(name));
  if (picked.length > 0) return picked;
  return available.slice(0, Math.min(4, available.length));
}

export const CANDIDATE_DRAG_MIME = "application/x-effortless-candidate";

export interface CandidateDragPayload {
  index: number;
}
