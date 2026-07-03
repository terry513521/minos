import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AddWorkerModal, WORKERS_CHANGED_EVENT, WORKERS_CHECK_ALL_HEALTH_EVENT, WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, WORKERS_CLEAR_ALL_EVENT, WORKERS_START_ALL_EVENT, WORKERS_START_ALL_RESULT_EVENT, WORKERS_STOP_ALL_EVENT, WorkersCheckAllHealthResultDetail, WorkersStartAllResultDetail } from "./AddWorkerModal";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";
import { AutoModeTunableEditor } from "./AutoModeTunableEditor";
import { useAutoModeStatus } from "../hooks/useAutoModeStatus";
import { saveAutoModeState } from "../utils/autoModeStorage";
import { syncManualParamDefaultsFromAutoConfig } from "../utils/manualParamDefaults";

const sectionsWhenAuto = [
  { hash: "#auto", label: "Auto mode" },
  { hash: "#workers", label: "Workers" },
];

const sectionsWhenManual = [
  { hash: "#candidates", label: "Candidates" },
  { hash: "#workers", label: "Workers" },
];

export function Layout() {
  const location = useLocation();
  const [health, setHealth] = useState("…");
  const [workerModalOpen, setWorkerModalOpen] = useState(false);
  const [configureAutoOpen, setConfigureAutoOpen] = useState(false);
  const configureAutoOpenRef = useRef(false);
  configureAutoOpenRef.current = configureAutoOpen;
  const { status: autoModeStatus, enabled: autoEnabled, running: autoRunning, refresh: refreshAutoMode, applyStatus: applyAutoModeStatus } =
    useAutoModeStatus(() => configureAutoOpenRef.current);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoRestarting, setAutoRestarting] = useState(false);
  const [stoppingAllWorkers, setStoppingAllWorkers] = useState(false);
  const [startingAllWorkers, setStartingAllWorkers] = useState(false);
  const [checkingAllWorkers, setCheckingAllWorkers] = useState(false);
  const [autoMessage, setAutoMessage] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((h) => setHealth(h.status)).catch(() => {});
  }, []);

  async function handleToggleAutoMode() {
    if (configureAutoOpen) {
      setConfigureAutoOpen(false);
    }

    setAutoBusy(true);
    setAutoMessage(null);
    try {
      const nextEnabled = !autoEnabled;
      const status = await api.setAutoMode(nextEnabled);
      saveAutoModeState(status);
      syncManualParamDefaultsFromAutoConfig(status.config);
      applyAutoModeStatus(status);
      setConfigureAutoOpen(false);
      setAutoMessage(
        nextEnabled
          ? "Auto mode enabled — call POST /api/v1/auto/start when ready."
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

  useEffect(() => {
    function onStartAllResult(event: Event) {
      const detail = (event as CustomEvent<WorkersStartAllResultDetail>).detail;
      setStartingAllWorkers(false);
      if (!detail) return;
      if (detail.started === 0 && detail.failed === 0) {
        setAutoMessage(
          detail.skipped > 0
            ? "No workers ready to start — assign candidates and ensure workers are idle."
            : "No workers registered.",
        );
      } else if (detail.failed === 0) {
        setAutoMessage(`Started optimization on ${detail.started} worker(s).`);
      } else {
        setAutoMessage(
          `Started ${detail.started} worker(s), ${detail.failed} failed${
            detail.skipped > 0 ? `, ${detail.skipped} skipped` : ""
          }.`,
        );
      }
    }
    window.addEventListener(WORKERS_START_ALL_RESULT_EVENT, onStartAllResult);
    return () => window.removeEventListener(WORKERS_START_ALL_RESULT_EVENT, onStartAllResult);
  }, []);

  useEffect(() => {
    function onCheckAllHealthResult(event: Event) {
      const detail = (event as CustomEvent<WorkersCheckAllHealthResultDetail>).detail;
      setCheckingAllWorkers(false);
      if (!detail) return;
      if (detail.total === 0) {
        setAutoMessage("No workers registered.");
      } else if (detail.failed === 0) {
        setAutoMessage(`All ${detail.ok} worker(s) passed health check.`);
      } else {
        setAutoMessage(
          `Health check: ${detail.ok}/${detail.total} passed, ${detail.failed} failed.`,
        );
      }
    }
    window.addEventListener(WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, onCheckAllHealthResult);
    return () =>
      window.removeEventListener(WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, onCheckAllHealthResult);
  }, []);

  function handleCheckAllWorkers() {
    setCheckingAllWorkers(true);
    setAutoMessage(null);
    window.dispatchEvent(new Event(WORKERS_CHECK_ALL_HEALTH_EVENT));
  }

  function handleClearAllWorkers() {
    if (
      !window.confirm(
        "Clear all worker data? This removes assignments, best scores, and trial history from the dashboard.",
      )
    ) {
      return;
    }
    setAutoMessage(null);
    window.dispatchEvent(new Event(WORKERS_CLEAR_ALL_EVENT));
    setAutoMessage("Cleared all worker dashboard data.");
  }

  function handleStartAllWorkers() {
    if (
      !window.confirm(
        "Start optimization on all workers with manual assignments?",
      )
    ) {
      return;
    }
    setStartingAllWorkers(true);
    setAutoMessage(null);
    window.dispatchEvent(new Event(WORKERS_START_ALL_EVENT));
  }

  async function handleStopAllWorkers() {
    if (
      !window.confirm(
        "Stop optimization on all workers and clear assignments, best scores, and trial history from the dashboard?",
      )
    ) {
      return;
    }
    setStoppingAllWorkers(true);
    setAutoMessage(null);
    try {
      const result = await api.stopAllWorkersOptimization();
      void refreshAutoMode();
      window.dispatchEvent(new Event(WORKERS_STOP_ALL_EVENT));
      window.dispatchEvent(new Event(WORKERS_CHANGED_EVENT));
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
      if (result.workers === 0) {
        setAutoMessage("No workers registered.");
      } else if (result.stopped_ok === result.workers) {
        setAutoMessage(`Stopped optimization on ${result.stopped_ok} worker(s).`);
      } else {
        const failed = result.results.filter((row) => !row.ok).map((row) => row.worker_name);
        setAutoMessage(
          `Stopped ${result.stopped_ok}/${result.workers} worker(s)${
            failed.length ? ` — failed: ${failed.join(", ")}` : ""
          }`,
        );
      }
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to stop workers");
    } finally {
      setStoppingAllWorkers(false);
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
      saveAutoModeState(status);
      applyAutoModeStatus(status);
      setAutoMessage("Auto session cleared — POST /api/v1/auto/start is ready.");
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
    } catch (err) {
      setAutoMessage(err instanceof Error ? err.message : "Failed to restart auto mode");
    } finally {
      setAutoRestarting(false);
    }
  }

  const sections = autoEnabled ? sectionsWhenAuto : sectionsWhenManual;
  const activeHash = location.hash || (autoEnabled ? "#auto" : "#candidates");

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
          <div className="topbar-worker-bulk">
            <button
              type="button"
              className="button ghost topbar-check-all"
              onClick={handleCheckAllWorkers}
              disabled={
                checkingAllWorkers ||
                startingAllWorkers ||
                stoppingAllWorkers ||
                autoBusy ||
                autoRestarting
              }
              title="Run health check on every registered worker"
            >
              {checkingAllWorkers ? "Checking…" : "Check all"}
            </button>
            <button
              type="button"
              className="button ghost topbar-start-all"
              onClick={() => void handleStartAllWorkers()}
              disabled={
                checkingAllWorkers ||
                startingAllWorkers ||
                stoppingAllWorkers ||
                autoBusy ||
                autoRestarting ||
                autoEnabled
              }
              title={
                autoEnabled
                  ? "Disable auto mode to start workers manually"
                  : "Start optimization on every worker with an assignment"
              }
            >
              {startingAllWorkers ? "Starting…" : "Start all"}
            </button>
            <button
              type="button"
              className="button ghost topbar-clear-all"
              onClick={handleClearAllWorkers}
              disabled={
                checkingAllWorkers ||
                startingAllWorkers ||
                stoppingAllWorkers ||
                autoBusy ||
                autoRestarting
              }
              title="Clear candidate assignments on every worker"
            >
              Clear all
            </button>
            <button
              type="button"
              className="button ghost topbar-stop-all"
              onClick={() => void handleStopAllWorkers()}
              disabled={
                checkingAllWorkers ||
                stoppingAllWorkers ||
                startingAllWorkers ||
                autoBusy ||
                autoRestarting
              }
              title="Stop optimization on every registered worker"
            >
              {stoppingAllWorkers ? "Stopping…" : "Stop all"}
            </button>
          </div>
          {!autoEnabled && (
            <button
              type="button"
              className="button ghost topbar-auto-configure"
              onClick={() => setConfigureAutoOpen(true)}
              disabled={autoBusy || autoRestarting || stoppingAllWorkers || startingAllWorkers || checkingAllWorkers}
              title="Edit auto mode parameters before enabling"
            >
              Configure
            </button>
          )}
          <button
            type="button"
            className={`button ghost topbar-auto-mode${autoEnabled ? " is-on" : ""}`}
            onClick={() => void handleToggleAutoMode()}
            disabled={autoBusy || autoRestarting || stoppingAllWorkers || startingAllWorkers || checkingAllWorkers}
            aria-pressed={autoEnabled}
            title={
              autoEnabled
                ? "Disable auto mode"
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
              disabled={autoRestarting || autoBusy || stoppingAllWorkers || startingAllWorkers || checkingAllWorkers}
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
          open={configureAutoOpen}
          config={autoModeStatus.config}
          tool={autoModeStatus.config.tool}
          running={autoModeStatus.running}
          variant="edit"
          onClose={() => setConfigureAutoOpen(false)}
          onSaved={() => {
            void refreshAutoMode();
            setAutoMessage("Auto mode parameters saved.");
          }}
        />
      )}
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
