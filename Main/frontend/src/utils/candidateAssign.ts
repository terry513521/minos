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

export function defaultSelectedParams(_tool: string, _available: string[]): string[] {
  return [];
}

export const CANDIDATE_DRAG_MIME = "application/x-effortless-candidate";

export interface CandidateDragPayload {
  index: number;
}
