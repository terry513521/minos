import { FindCandidatesResponse } from "../api/client";

const STORAGE_KEY = "effortless:candidate-finder:v1";

export interface PersistedCandidateFinderState {
  region: string;
  kCandidates: number;
  result: FindCandidatesResponse | null;
}

export function loadCandidateFinderState(): PersistedCandidateFinderState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedCandidateFinderState>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      region: typeof parsed.region === "string" ? parsed.region : "",
      kCandidates:
        typeof parsed.kCandidates === "number" && parsed.kCandidates > 0
          ? parsed.kCandidates
          : 2,
      result: parsed.result ?? null,
    };
  } catch {
    return null;
  }
}

export function saveCandidateFinderState(state: PersistedCandidateFinderState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Ignore quota / private-mode errors.
  }
}
