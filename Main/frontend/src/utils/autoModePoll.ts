import { api, AutoModeStatus } from "../api/client";
import { AUTO_MODE_CHANGED_EVENT } from "../components/AutoModePanel";
import { loadAutoModeState, saveAutoModeState } from "./autoModeStorage";
import { syncManualParamDefaultsFromAutoConfig } from "./manualParamDefaults";

type Subscriber = (status: AutoModeStatus | null) => void;
type PauseFn = () => boolean;

const POLL_MS = 5000;

let latest: AutoModeStatus | null = loadAutoModeState()?.status ?? null;
let intervalId: number | null = null;
let inFlight = false;
const subscribers = new Set<Subscriber>();
const pauseFns = new Set<PauseFn>();

function notify() {
  for (const fn of subscribers) {
    fn(latest);
  }
}

async function tick() {
  if (inFlight) return;
  if ([...pauseFns].some((fn) => fn())) return;
  inFlight = true;
  try {
    const next = await api.getAutoMode();
    saveAutoModeState(next);
    syncManualParamDefaultsFromAutoConfig(next.config, {
      syncPerWorkerTunables: next.enabled,
    });
    latest = next;
    notify();
    window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
  } catch {
    /* keep last known status */
  } finally {
    inFlight = false;
  }
}

function ensurePolling() {
  if (intervalId != null) return;
  void tick();
  intervalId = window.setInterval(() => {
    void tick();
  }, POLL_MS);
}

function stopPolling() {
  if (intervalId != null) {
    window.clearInterval(intervalId);
    intervalId = null;
  }
}

export function getAutoModeSnapshot(): AutoModeStatus | null {
  return latest;
}

export function subscribeAutoMode(
  fn: Subscriber,
  options?: { pause?: PauseFn },
): () => void {
  subscribers.add(fn);
  if (options?.pause) pauseFns.add(options.pause);
  fn(latest);
  if (subscribers.size === 1) {
    ensurePolling();
  }
  return () => {
    subscribers.delete(fn);
    if (options?.pause) pauseFns.delete(options.pause);
    if (subscribers.size === 0) {
      stopPolling();
    }
  };
}

export function refreshAutoModeNow(): Promise<AutoModeStatus | null> {
  return tick().then(() => latest);
}
