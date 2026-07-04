import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, WorkerRecord } from "../api/client";
import { buildConfCheckDispatchPayload, parseConfCheckFile, ParsedConfCheckFile } from "../utils/confCheck";
import { loadConfCheckWorkerId, saveConfCheckWorkerId } from "../utils/confCheckStorage";
import { CONF_CHECK_TRIAL_MEMORY_GB, CONF_CHECK_TRIAL_THREADS } from "../types/workerAssignment";
import { effectiveBenchmarkWindow, formatBenchmarkWindowLabel } from "../utils/workerTaskSummary";
import { analyzeBenchmarkWindow, formatWindowSpan } from "../utils/window";
import { ConfTooltip } from "./ConfTooltip";
import { WORKERS_CHANGED_EVENT } from "./AddWorkerModal";

interface ConfCheckPanelProps {
  finderRegion: string;
}

type CheckPhase = "idle" | "dispatching" | "running" | "done" | "error";

function formatScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${(score * 100).toFixed(2)}%`;
}

export function ConfCheckPanel({ finderRegion }: ConfCheckPanelProps) {
  const importFileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);

  const [workers, setWorkers] = useState<WorkerRecord[]>([]);
  const [checkWorkerId, setCheckWorkerId] = useState<string | null>(() => loadConfCheckWorkerId());
  const [parsedConf, setParsedConf] = useState<ParsedConfCheckFile | null>(null);
  const [confFileName, setConfFileName] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [phase, setPhase] = useState<CheckPhase>("idle");
  const [score, setScore] = useState<number | null>(null);
  const [rawScore, setRawScore] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [benchmarkWindow, setBenchmarkWindow] = useState<string | null>(null);
  const [dispatchedWindow, setDispatchedWindow] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const windowAnalysis = analyzeBenchmarkWindow(finderRegion);
  const region = windowAnalysis.window ?? "";
  const regionSpan = formatWindowSpan(region);
  const checkWorker = workers.find((worker) => worker.id === checkWorkerId) ?? null;
  const benchmarkSpan = formatWindowSpan(benchmarkWindow);
  const dispatchedSpan = formatWindowSpan(dispatchedWindow);

  const refreshWorkers = useCallback(() => {
    api
      .listWorkers()
      .then(setWorkers)
      .catch(() => setWorkers([]));
  }, []);

  useEffect(() => {
    refreshWorkers();
    function onChanged() {
      refreshWorkers();
    }
    window.addEventListener(WORKERS_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKERS_CHANGED_EVENT, onChanged);
  }, [refreshWorkers]);

  useEffect(() => {
    if (!checkWorkerId && workers.length > 0) {
      const saved = loadConfCheckWorkerId();
      const match = saved ? workers.find((worker) => worker.id === saved) : null;
      const nextId = match?.id ?? workers[0]?.id ?? null;
      if (nextId) {
        setCheckWorkerId(nextId);
        saveConfCheckWorkerId(nextId);
      }
    }
  }, [workers, checkWorkerId]);

  useEffect(() => {
    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
      }
    };
  }, []);

  function stopPolling() {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function applyConfText(text: string, fileName?: string) {
    setError(null);
    setMessage(null);
    setScore(null);
    setRawScore(null);
    setBenchmarkWindow(null);
    setDispatchedWindow(null);
    setPhase("idle");

    const parsed = parseConfCheckFile(text);
    if (!parsed.ok) {
      setError(parsed.error);
      setParsedConf(null);
      setConfFileName(null);
      return;
    }

    setParsedConf(parsed.result);
    setConfFileName(fileName ?? "dropped conf");
    setMessage("Conf loaded — click Start check to benchmark on the check worker.");
  }

  async function handleConfFile(file: File | null | undefined) {
    if (!file) return;
    try {
      const text = await file.text();
      await applyConfText(text, file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read conf file");
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDropActive(false);
    const file = e.dataTransfer.files?.[0];
    void handleConfFile(file);
  }

  function handleWorkerChange(workerId: string) {
    setCheckWorkerId(workerId);
    saveConfCheckWorkerId(workerId);
  }

  async function pollUntilScore(workerId: string) {
    const best = await api.fetchWorkerBest(workerId);
    if (!best.ok) {
      setPhase("error");
      setError(best.error ?? "Could not read worker score");
      stopPolling();
      return;
    }

    setDispatchedWindow(best.window ?? null);
    setBenchmarkWindow(effectiveBenchmarkWindow(best));

    const baseTrial = best.trials.find((trial) => trial.label === "base conf" && trial.success);
    const finished =
      best.status === "ready" ||
      best.status === "completed" ||
      best.status === "time limited" ||
      (best.trials_evaluated >= 1 && baseTrial != null);

    if (finished && baseTrial?.score != null) {
      setScore(baseTrial.score);
      setRawScore(baseTrial.raw_score);
      setPhase("done");
      const scoredLabel = formatBenchmarkWindowLabel(best);
      setMessage(scoredLabel ? `Base conf score on ${scoredLabel}` : "Base conf score ready");
      stopPolling();
      return;
    }

    if (best.status === "error") {
      setPhase("error");
      setError(best.message ?? "Benchmark failed");
      stopPolling();
      return;
    }

    if (best.status === "optimizing" || best.status === "stopping") {
      setPhase("running");
      const liveLabel = formatBenchmarkWindowLabel(best);
      setMessage(
        liveLabel
          ? `Benchmarking on worker window ${liveLabel}`
          : best.message ?? "Running base conf benchmark…",
      );
    }
  }

  async function handleStartCheck() {
    setError(null);
    setMessage(null);
    setScore(null);
    setRawScore(null);
    setBenchmarkWindow(null);
    setDispatchedWindow(null);

    if (!windowAnalysis.valid) {
      setError(windowAnalysis.error ?? "Invalid region for benchmark.");
      return;
    }
    if (!region) {
      setError("Set a Region in Find candidates before running a conf check.");
      return;
    }
    if (!checkWorkerId || !checkWorker) {
      setError("Select a check worker.");
      return;
    }
    if (!parsedConf) {
      setError("Drop or choose a conf file first.");
      return;
    }
    if (!checkWorker.base_url) {
      setError("Check worker has no base URL configured.");
      return;
    }

    const built = buildConfCheckDispatchPayload(finderRegion, parsedConf);
    if (!built.ok) {
      setError(built.error);
      return;
    }

    setDispatchedWindow(built.payload.window);
    setPhase("dispatching");
    stopPolling();

    try {
      const dispatch = await api.dispatchToWorker(checkWorkerId, built.payload);
      if (!dispatch.ok) {
        setPhase("error");
        setError(dispatch.error ?? "Dispatch failed");
        return;
      }

      setPhase("running");
      setMessage("Benchmark started — waiting for base conf score…");
      await pollUntilScore(checkWorkerId);
      pollRef.current = window.setInterval(() => {
        void pollUntilScore(checkWorkerId);
      }, 1000);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to start conf check");
      stopPolling();
    }
  }

  const startDisabled =
    phase === "dispatching" ||
    phase === "running" ||
    !parsedConf ||
    !windowAnalysis.valid ||
    !checkWorkerId;

  return (
    <section className="conf-check-panel" aria-label="Conf parameter check">
      <div className="conf-check-head">
        <div>
          <h3 className="conf-check-title">Conf check</h3>
          <p className="conf-check-lead">
            Use one worker to score a dropped conf on the current Region — base benchmark only, no
            search trials. Uses {CONF_CHECK_TRIAL_THREADS} CPU / {CONF_CHECK_TRIAL_MEMORY_GB} GB per
            trial.
          </p>
        </div>
        {phase === "done" && score != null && (
          <div className="conf-check-score-badge" aria-live="polite">
            <span className="conf-check-score-label">Score</span>
            <span className="conf-check-score-value">{formatScore(score)}</span>
            {rawScore != null && (
              <span className="conf-check-score-raw">{rawScore.toFixed(2)} / 100</span>
            )}
          </div>
        )}
      </div>

      <div className="conf-check-controls">
        <label className="conf-check-field">
          <span className="conf-check-field-label">Check worker</span>
          <select
            value={checkWorkerId ?? ""}
            onChange={(e) => handleWorkerChange(e.target.value)}
            aria-label="Worker for conf check"
          >
            {workers.length === 0 ? (
              <option value="">No workers registered</option>
            ) : (
              workers.map((worker) => (
                <option key={worker.id} value={worker.id}>
                  {worker.name}
                </option>
              ))
            )}
          </select>
        </label>

        <label className="conf-check-field conf-check-field--region">
          <span className="conf-check-field-label">Assigned region</span>
          <code className="conf-check-region">{region || "—"}</code>
          {regionSpan && (
            <span className="conf-check-region-size">{regionSpan} dispatched</span>
          )}
        </label>

        {(phase === "running" || phase === "done") && benchmarkWindow && (
          <label className="conf-check-field conf-check-field--region">
            <span className="conf-check-field-label">Worker benchmark window</span>
            <code className="conf-check-region conf-check-region--live">{benchmarkWindow}</code>
            {benchmarkSpan && (
              <span className="conf-check-region-size conf-check-region-size--ok">
                {benchmarkSpan} scored
              </span>
            )}
          </label>
        )}
      </div>

      {windowAnalysis.warning && phase === "idle" && (
        <p className="conf-check-window-warning" role="status">
          {windowAnalysis.warning}
        </p>
      )}
      {windowAnalysis.error && (
        <p className="conf-check-error" role="alert">
          {windowAnalysis.error}
        </p>
      )}

      {phase === "done" && dispatchedWindow && benchmarkWindow && dispatchedWindow !== benchmarkWindow && (
        <p className="conf-check-window-note" role="status">
          Assigned <code>{dispatchedWindow}</code> ({dispatchedSpan ?? "—"}) · worker scored{" "}
          <code>{benchmarkWindow}</code> ({benchmarkSpan ?? "—"})
        </p>
      )}

      <div
        className={`conf-check-dropzone${dropActive ? " conf-check-dropzone--active" : ""}${parsedConf ? " conf-check-dropzone--loaded" : ""}`}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          setDropActive(true);
        }}
        onDragLeave={() => setDropActive(false)}
        onDrop={handleDrop}
        onClick={() => importFileRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            importFileRef.current?.click();
          }
        }}
      >
        <input
          ref={importFileRef}
          type="file"
          accept=".conf,.json,.txt,application/json,text/plain"
          className="sr-only"
          onChange={(e) => {
            void handleConfFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <span className="conf-check-dropzone-title">
          {parsedConf ? `Loaded: ${confFileName ?? "conf"}` : "Drop conf file here"}
        </span>
        <span className="conf-check-dropzone-hint">
          GATK <code>.conf</code> or JSON with <code>gatk_options</code>
        </span>
      </div>

      {parsedConf && (
        <div className="conf-check-conf-preview">
          <ConfTooltip conf={parsedConf.baseConf} label="Check conf" />
        </div>
      )}

      <div className="conf-check-actions">
        <button
          type="button"
          className="button primary"
          disabled={startDisabled}
          onClick={() => void handleStartCheck()}
        >
          {phase === "dispatching"
            ? "Starting…"
            : phase === "running"
              ? "Checking…"
              : "Start check"}
        </button>
      </div>

      {message && phase !== "error" && (
        <p className="conf-check-message" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="conf-check-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
