import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AddWorkerModal } from "./AddWorkerModal";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";

const sections = [
  { hash: "#candidates", label: "Candidates" },
  { hash: "#history", label: "History" },
];

export function Layout() {
  const location = useLocation();
  const [health, setHealth] = useState("…");
  const [workerModalOpen, setWorkerModalOpen] = useState(false);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoMessage, setAutoMessage] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((h) => setHealth(h.status)).catch(() => {});
  }, []);

  const refreshAutoMode = useCallback(() => {
    api
      .getAutoMode()
      .then((status) => {
        setAutoEnabled(status.enabled);
        setAutoRunning(status.running);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshAutoMode();
    const intervalId = window.setInterval(refreshAutoMode, 5000);
    return () => window.clearInterval(intervalId);
  }, [refreshAutoMode]);

  async function handleToggleAutoMode() {
    setAutoBusy(true);
    setAutoMessage(null);
    try {
      const status = await api.setAutoMode(!autoEnabled);
      setAutoEnabled(status.enabled);
      setAutoRunning(status.running);
      setAutoMessage(
        status.enabled
          ? "Auto mode enabled"
          : status.running
            ? "Auto mode disabled — worker optimizations continue"
            : "Auto mode disabled",
      );
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to update auto mode");
    } finally {
      setAutoBusy(false);
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
            disabled={autoBusy}
            aria-pressed={autoEnabled}
            title={
              autoEnabled
                ? "Auto mode armed — call POST /api/v1/auto/start to begin; POST /api/v1/auto/best to stop"
                : "Enable auto mode for unattended overnight runs"
            }
          >
            {autoBusy ? "Auto…" : autoEnabled ? "Auto mode on" : "Auto mode off"}
            {autoRunning ? " · running" : ""}
          </button>
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
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
