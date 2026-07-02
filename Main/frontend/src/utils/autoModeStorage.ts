import { AutoModeStatus } from "../api/client";

const STORAGE_KEY = "effortless:auto-mode:v1";

export interface PersistedAutoModeState {
  status: AutoModeStatus | null;
}

export function loadAutoModeState(): PersistedAutoModeState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedAutoModeState>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      status: parsed.status ?? null,
    };
  } catch {
    return null;
  }
}

export function saveAutoModeState(status: AutoModeStatus | null): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ status }));
  } catch {
    // Ignore quota / private-mode errors.
  }
}
