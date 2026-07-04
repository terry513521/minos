const STORAGE_KEY = "effortless:conf-check-worker:v1";

export function loadConfCheckWorkerId(): string | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw?.trim() || null;
  } catch {
    return null;
  }
}

export function saveConfCheckWorkerId(workerId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, workerId);
  } catch {
    // Ignore quota / private-mode errors.
  }
}
