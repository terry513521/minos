import { FindCandidatesResponse } from "../api/client";
import { DEFAULT_TOOLKIT, TOOLKIT_OPTIONS, ToolkitOption } from "../types/workerAssignment";

const STORAGE_KEY = "effortless:candidate-finder:v2";

export const DEFAULT_K_CANDIDATES = 6;
export const MIN_K_CANDIDATES = 1;
export const MAX_K_CANDIDATES = 16;

export interface PersistedCandidateFinderState {
  region: string;
  tool: ToolkitOption;
  kCandidates: number;
  result: FindCandidatesResponse | null;
}

export function normalizeFinderTool(raw: string | undefined): ToolkitOption {
  const tool = (raw ?? DEFAULT_TOOLKIT).toLowerCase().trim();
  return TOOLKIT_OPTIONS.includes(tool as ToolkitOption) ? (tool as ToolkitOption) : DEFAULT_TOOLKIT;
}

export function clampKCandidates(value: number | undefined): number {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_K_CANDIDATES;
  return Math.min(MAX_K_CANDIDATES, Math.max(MIN_K_CANDIDATES, parsed));
}

export function loadCandidateFinderState(): PersistedCandidateFinderState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedCandidateFinderState>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      region: typeof parsed.region === "string" ? parsed.region : "",
      tool: normalizeFinderTool(typeof parsed.tool === "string" ? parsed.tool : undefined),
      kCandidates: clampKCandidates(parsed.kCandidates),
      result: parsed.result ?? null,
    };
  } catch {
    return null;
  }
}

export function saveCandidateFinderState(state: PersistedCandidateFinderState): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...state,
        kCandidates: clampKCandidates(state.kCandidates),
      }),
    );
  } catch {
    // Ignore quota / private-mode errors.
  }
}

export function clearCandidateFinderState(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore quota / private-mode errors.
  }
}
