import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { api, AutoModeStatus } from "../api/client";
import { AddWorkerModal } from "./AddWorkerModal";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";
import { AutoModeTunableEditor } from "./AutoModeTunableEditor";
import { saveAutoModeState } from "../utils/autoModeStorage";

const sections = [
  { hash: "#candidates", label: "Candidates" },
  { hash: "#workers", label: "Workers" },
];

export function Layout() {
  const location = useLocation();
  const [health, setHealth] = useState("…");
  const [workerModalOpen, setWorkerModalOpen] = useState(false);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoModeStatus, setAutoModeStatus] = useState<AutoModeStatus | null>(null);
  const [enableConfirmOpen, setEnableConfirmOpen] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoRestarting, setAutoRestarting] = useState(false);
  const [autoMessage, setAutoMessage] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((h) => setHealth(h.status)).catch(() => {});
  }, []);

  const refreshAutoMode = useCallback(() => {
    api
      .getAutoMode()
      .then((status) => {
        saveAutoModeState(status);
        setAutoModeStatus(status);
        setAutoEnabled(status.enabled);
        setAutoRunning(status.running);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshAutoMode();
    function onChanged() {
      refreshAutoMode();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
    const intervalId = window.setInterval(refreshAutoMode, 5000);
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
      window.clearInterval(intervalId);
    };
  }, [refreshAutoMode]);

  async function handleToggleAutoMode() {
    if (autoEnabled) {
      setAutoBusy(true);
      setAutoMessage(null);
      try {
        const status = await api.setAutoMode(false);
        saveAutoModeState(status);
        setAutoModeStatus(status);
        setAutoEnabled(status.enabled);
        setAutoRunning(status.running);
        setAutoMessage(
          status.running
            ? "Auto mode disabled — worker optimizations continue"
            : "Auto mode disabled",
        );
        window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
      } catch (err) {
        setAutoMessage(err instanceof Error ? err.message : "Failed to update auto mode");
      } finally {
        setAutoBusy(false);
      }
      return;
    }

    setAutoMessage(null);
    try {
      const status = await api.getAutoMode();
      saveAutoModeState(status);
      setAutoModeStatus(status);
      setEnableConfirmOpen(true);
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to load auto mode config");
    }
  }

  async function handleConfirmEnableAutoMode() {
    setAutoBusy(true);
    setAutoMessage(null);
    try {
      const status = await api.setAutoMode(true);
      saveAutoModeState(status);
      setAutoModeStatus(status);
      setAutoEnabled(status.enabled);
      setAutoRunning(status.running);
      setAutoMessage("Auto mode enabled — call POST /api/v1/auto/start when ready.");
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to enable auto mode");
      throw err;
    } finally {
      setAutoBusy(false);
    }
  }

  async function handleRestartAutoMode() {
    if (
      !window.confirm(
        "Stop all auto workers and clear the session? POST /auto/start will work again.",
      )
    ) {
      return;
    }
    setAutoRestarting(true);
    setAutoMessage(null);
    try {
      const status = await api.restartAutoMode();
      setAutoEnabled(status.enabled);
      setAutoRunning(status.running);
      setAutoMessage("Auto session cleared — POST /api/v1/auto/start is ready.");
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to restart auto mode");
    } finally {
      setAutoRestarting(false);
    }
  }

  const activeHash = location.hash || "#candidates";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand">
            <img
              src="/effortless-avatar.png"
              alt=""
              className="brand-avatar"
              width={36}
              height={36}
            />
            <div className="brand-text">
              <span className="brand-mark">Effortless</span>
              <span className="brand-sub">Candidate Finder</span>
            </div>
          </div>
          <nav className="section-nav" aria-label="Sections">
            {sections.map((s) => (
              <a
                key={s.hash}
                href={s.hash}
                className={`section-nav-link${activeHash === s.hash ? " active" : ""}`}
              >
                {s.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className={`button ghost topbar-auto-mode${autoEnabled ? " is-on" : ""}`}
            onClick={handleToggleAutoMode}
            disabled={autoBusy || autoRestarting}
            aria-pressed={autoEnabled}
            title={
              autoEnabled
                ? "Auto mode armed — call POST /api/v1/auto/start to begin; GET /api/v1/auto/best to stop"
                : "Enable auto mode for unattended overnight runs"
            }
          >
            {autoBusy ? "Auto…" : autoEnabled ? "Auto mode on" : "Auto mode off"}
            {autoRunning ? " · running" : ""}
          </button>
          {(autoRunning || autoEnabled) && (
            <button
              type="button"
              className="button ghost topbar-auto-restart"
              onClick={() => void handleRestartAutoMode()}
              disabled={autoRestarting || autoBusy}
              title="Stop workers and clear session so POST /api/v1/auto/start works again"
            >
              {autoRestarting ? "Restarting…" : "Restart session"}
            </button>
          )}
          <button
            type="button"
            className="button primary topbar-add-worker"
            onClick={() => setWorkerModalOpen(true)}
          >
            Add worker
          </button>
          <span className={`status-pill ${health === "ok" ? "ok" : "bad"}`}>
            <span className="status-dot" />
            API {health}
          </span>
        </div>
      </header>
      {autoMessage && <div className="auto-mode-banner">{autoMessage}</div>}
      <AddWorkerModal open={workerModalOpen} onClose={() => setWorkerModalOpen(false)} />
      {autoModeStatus && (
        <AutoModeTunableEditor
          open={enableConfirmOpen}
          config={autoModeStatus.config}
          tool={autoModeStatus.config.tool}
          running={autoModeStatus.running}
          variant="enable"
          onClose={() => setEnableConfirmOpen(false)}
          onEnable={handleConfirmEnableAutoMode}
        />
      )}
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
