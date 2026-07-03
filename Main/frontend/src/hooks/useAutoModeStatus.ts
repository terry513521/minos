import { useCallback, useEffect, useRef, useState } from "react";
import { api, AutoModeStatus } from "../api/client";
import { AUTO_MODE_CHANGED_EVENT } from "../components/AutoModePanel";
import { loadAutoModeState, saveAutoModeState } from "../utils/autoModeStorage";
import { syncManualParamDefaultsFromAutoConfig } from "../utils/manualParamDefaults";

type PausePollingFn = () => boolean;

export function useAutoModeStatus(pausePolling?: PausePollingFn) {
  const pausePollingRef = useRef(pausePolling);
  pausePollingRef.current = pausePolling;

  const [status, setStatus] = useState<AutoModeStatus | null>(
    () => loadAutoModeState()?.status ?? null,
  );

  const refresh = useCallback(() => {
    return api
      .getAutoMode()
      .then((next) => {
        saveAutoModeState(next);
        syncManualParamDefaultsFromAutoConfig(next.config, {
          syncPerWorkerTunables: next.enabled,
        });
        setStatus(next);
        return next;
      })
      .catch(() => null);
  }, []);

  useEffect(() => {
    void refresh();
    function onChanged() {
      void refresh();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
    const intervalId = window.setInterval(() => {
      if (pausePollingRef.current?.()) return;
      void refresh();
    }, 5000);
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
      window.clearInterval(intervalId);
    };
  }, [refresh]);

  return {
    status,
    enabled: status?.enabled ?? false,
    running: status?.running ?? false,
    refresh,
    applyStatus: setStatus,
  };
}
