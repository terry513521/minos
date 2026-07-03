import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { AUTO_MODE_CHANGED_EVENT } from "../components/AutoModePanel";
import { loadAutoModeState, saveAutoModeState } from "../utils/autoModeStorage";

export function useAutoModeEnabled(): boolean {
  const [enabled, setEnabled] = useState(
    () => loadAutoModeState()?.status?.enabled ?? false,
  );

  const refresh = useCallback(() => {
    const cached = loadAutoModeState()?.status;
    if (cached) {
      setEnabled(cached.enabled);
    }
    api
      .getAutoMode()
      .then((status) => {
        saveAutoModeState(status);
        setEnabled(status.enabled);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, refresh);
    const intervalId = window.setInterval(refresh, 5000);
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, refresh);
      window.clearInterval(intervalId);
    };
  }, [refresh]);

  return enabled;
}
