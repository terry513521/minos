import { useCallback, useEffect, useState } from "react";
import { api, PlatformRound } from "../api/client";

const WS_URL =
  (location.protocol === "https:" ? "wss://" : "ws://") +
  location.host +
  "/api/v1/ws";

export function usePlatformRound(pollSeconds = 5) {
  const [round, setRound] = useState<PlatformRound | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const applyRound = useCallback((data: PlatformRound) => {
    setRound(data);
    setError(data.error);
  }, []);

  const loadCached = useCallback(async () => {
    const data = await api.getPlatformRound();
    applyRound(data);
    return data;
  }, [applyRound]);

  const refresh = useCallback(async () => {
    try {
      const data = await api.refreshPlatformRound();
      applyRound(data);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to refresh round");
      throw e;
    } finally {
      setLoading(false);
    }
  }, [applyRound]);

  useEffect(() => {
    let alive = true;

    refresh().catch(() => {
      if (!alive) return;
      loadCached()
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          if (alive) setLoading(false);
        });
    });

    const id = window.setInterval(() => {
      loadCached().catch(() => {});
    }, pollSeconds * 1000);

    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [refresh, loadCached, pollSeconds]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let alive = true;

    try {
      ws = new WebSocket(WS_URL);
      ws.onmessage = (ev) => {
        if (!alive) return;
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "platform_round" && msg.data) {
            applyRound(msg.data as PlatformRound);
            setLoading(false);
          }
        } catch {
          /* ignore */
        }
      };
    } catch {
      /* WS optional */
    }

    return () => {
      alive = false;
      ws?.close();
    };
  }, [applyRound]);

  return { round, loading, error, refresh };
}
