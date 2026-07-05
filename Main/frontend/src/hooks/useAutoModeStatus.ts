import { useCallback, useEffect, useRef, useState } from "react";
import { AutoModeStatus } from "../api/client";
import { AUTO_MODE_CHANGED_EVENT } from "../components/AutoModePanel";
import { getAutoModeSnapshot, refreshAutoModeNow, subscribeAutoMode } from "../utils/autoModePoll";
import { saveAutoModeState } from "../utils/autoModeStorage";
import { syncManualParamDefaultsFromAutoConfig } from "../utils/manualParamDefaults";

type PausePollingFn = () => boolean;

export function useAutoModeStatus(pausePolling?: PausePollingFn) {
  const pausePollingRef = useRef(pausePolling);
  pausePollingRef.current = pausePolling;

  const [status, setStatus] = useState<AutoModeStatus | null>(() => getAutoModeSnapshot());

  const refresh = useCallback(() => refreshAutoModeNow(), []);

  useEffect(() => {
    function onChanged() {
      setStatus(getAutoModeSnapshot());
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
    const unsubscribe = subscribeAutoMode(setStatus, {
      pause: () => pausePollingRef.current?.() ?? false,
    });
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
      unsubscribe();
    };
  }, []);

  const applyStatus = useCallback((next: AutoModeStatus | null) => {
    if (next) {
      saveAutoModeState(next);
      syncManualParamDefaultsFromAutoConfig(next.config, {
        syncPerWorkerTunables: next.enabled,
      });
    }
    setStatus(next);
  }, []);

  return {
    status,
    enabled: status?.enabled ?? false,
    running: status?.running ?? false,
    refresh,
    applyStatus,
  };
}
