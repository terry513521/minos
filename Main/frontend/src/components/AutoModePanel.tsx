import { useCallback, useEffect, useRef, useState } from "react";
import { api, AutoModeStatus, AutoSelectedCandidate, CandidatePreview } from "../api/client";
import { formatLocalDateTime } from "../hooks/useSubmissionCountdown";
import {
  candidateHistoryScore,
  compositeCandidateScore,
  selectionSlotsByIndex,
} from "../utils/candidateSelection";
import { loadAutoModeState, saveAutoModeState } from "../utils/autoModeStorage";
import { syncManualParamDefaultsFromAutoConfig } from "../utils/manualParamDefaults";
import {
  formatParamInterval,
  paramIntervalsFromAutoConfig,
  workerAlgorithmsFromAutoConfig,
} from "../utils/autoModeSync";
import { ConfTooltip } from "./ConfTooltip";
import { LimitCountdownBadge } from "./LimitCountdownBadge";
import { AutoModeTunableEditor } from "./AutoModeTunableEditor";

export const AUTO_MODE_CHANGED_EVENT = "effortless:auto-mode-changed";

interface AutoModePanelProps {
  /** Render inside dashboard section panel (no nested chrome). */
  embedded?: boolean;
}

export function AutoModePanel({ embedded = false }: AutoModePanelProps) {
  const persistedAutoRef = useRef(loadAutoModeState());
  const [status, setStatus] = useState<AutoModeStatus | null>(
    () => persistedAutoRef.current?.status ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [restartMessage, setRestartMessage] = useState<string | null>(null);
  const [editingParams, setEditingParams] = useState(false);

  const refresh = useCallback(() => {
    api
      .getAutoMode()
      .then((next) => {
        saveAutoModeState(next);
        syncManualParamDefaultsFromAutoConfig(next.config);
        setStatus(next);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    refresh();
    function onChanged() {
      refresh();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
    const intervalId = window.setInterval(refresh, 5000);
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
      window.clearInterval(intervalId);
    };
  }, [refresh]);

  if (!status) {
    return error ? (
      <div className="alert error auto-mode-panel">{error}</div>
    ) : embedded ? (
      <p className="empty-state">Loading auto mode…</p>
    ) : null;
  }

  const config = status.config;
  const paramIntervals = paramIntervalsFromAutoConfig(config);
  const workerAlgorithms = workerAlgorithmsFromAutoConfig(config);
  const selectionByIndex = selectionSlotsByIndex(status.selected_candidates);
  const foundCount = status.found_candidates.length || status.candidates_found;
  const canRestartSession =
    status.enabled ||
    status.running ||
    status.assignments.length > 0 ||
    Boolean(status.last_started_region);

  if (!status.enabled && !embedded) {
    return null;
  }

  async function handleRestartSession() {
    if (
      !window.confirm(
        "Stop all auto workers and clear the session? POST /auto/start will work again.",
      )
    ) {
      return;
    }
    setRestarting(true);
    setRestartMessage(null);
    setError(null);
    try {
      const next = await api.restartAutoMode();
      saveAutoModeState(next);
      setStatus(next);
      setRestartMessage("Session cleared — you can call POST /api/v1/auto/start again.");
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restart auto mode");
    } finally {
      setRestarting(false);
    }
  }

  return (
    <div
      className={`auto-mode-panel${status.enabled ? " auto-mode-panel--on" : ""}${embedded ? " auto-mode-panel--embedded" : ""}`}
    >
      <div className="auto-mode-panel-head">
        {!embedded && <h4 className="auto-mode-panel-title">Auto mode</h4>}
        <div className="auto-mode-panel-badges">
          <span className={`badge ${status.enabled ? "online" : "offline"}`}>
            {status.enabled ? "Enabled" : "Disabled"}
          </span>
          {status.running && <span className="badge running">Running</span>}
        </div>
        {canRestartSession && (
          <button
            type="button"
            className="button ghost auto-mode-restart-btn"
            onClick={() => void handleRestartSession()}
            disabled={restarting}
          >
            {restarting ? "Restarting…" : "Restart session"}
          </button>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {restartMessage && <div className="alert ok">{restartMessage}</div>}

      {!embedded && status.enabled ? (
        <p className="auto-mode-panel-lead">
          Overnight orchestration for <strong>VM</strong>, <strong>Big</strong>, and{" "}
          <strong>Igno</strong>. Workers run only after{" "}
          <code>POST /api/v1/auto/start</code> with the round region. Stop and export via{" "}
          <code>GET /api/v1/auto/best</code>. If start returns &quot;session already running&quot;, use{" "}
          <strong>Restart session</strong>.
        </p>
      ) : !embedded && status.running ? (
        <p className="auto-mode-panel-lead">
          Auto mode is <strong>off</strong>. Worker optimizations from the last auto start{" "}
          <strong>continue</strong> — use the worker cards below for live scores.
        </p>
      ) : embedded ? (
        <p className="auto-mode-panel-lead">
          Stop and export via <code>GET /api/v1/auto/best</code>. If start returns &quot;session
          already running&quot;, use <strong>Restart session</strong>.
        </p>
      ) : null}

      <div className="auto-mode-section">
        <div className="auto-mode-section-head">
          <span className="auto-mode-section-title">Tunable parameters</span>
          <button
            type="button"
            className="button ghost auto-mode-edit-params-btn"
            onClick={() => setEditingParams(true)}
            disabled={status.running}
            title={
              status.running
                ? "Stop or restart the session before editing parameters"
                : "Edit parameters for the next auto start"
            }
          >
            Edit parameters
          </button>
        </div>
        <div className="auto-mode-param-table-wrap">
          <table className="auto-mode-param-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Search interval</th>
              </tr>
            </thead>
            <tbody>
              {config.params.map((param) => (
                <tr key={param}>
                  <td><code>{param}</code></td>
                  <td>{formatParamInterval(paramIntervals[param] ?? {})}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="auto-mode-section">
        <span className="auto-mode-section-title">Worker algorithms</span>
        <div className="auto-mode-worker-algorithm-summary">
          {config.worker_names.map((workerName) => (
            <span key={workerName} className="chip chip-muted">
              {workerName}: {workerAlgorithms[workerName]}
            </span>
          ))}
        </div>
      </div>

      {(status.enabled || status.assignments.length > 0 || status.found_candidates.length > 0) && (
        <>
          <div className="auto-mode-grid">
            <div className="auto-mode-card">
              <span className="auto-mode-card-label">Selection</span>
              <p>
                Find {config.find_k} candidates → VM top score, Big most similar, Igno best composite.
              </p>
              {status.region && (
                <p>
                  Region: <code>{status.region}</code>
                </p>
              )}
              {status.started_at && (
                <p className="auto-mode-muted">
                  Started {formatLocalDateTime(status.started_at)}
                </p>
              )}
            </div>

            <div className="auto-mode-card">
              <span className="auto-mode-card-label">Run settings</span>
              <p>Tool: {config.tool}</p>
              <p>Time limit: {Math.round(config.limit_seconds / 60)} min</p>
              <p>Trials: {config.adaptive_max_trials + 1} (1 base + {config.adaptive_max_trials} search)</p>
              {status.running && status.started_at && (
                <p className="auto-mode-limit-row">
                  <LimitCountdownBadge
                    startedAt={status.started_at}
                    limitSeconds={config.limit_seconds}
                    active={status.running}
                    className="auto-mode-limit-countdown"
                  />
                </p>
              )}
              <p>Concurrency: {config.concurrency}</p>
            </div>
          </div>

          {status.found_candidates.length > 0 && (
            <div className="auto-mode-section">
              <span className="auto-mode-section-title">
                Found candidates ({foundCount})
              </span>
              <p className="auto-mode-section-lead">
                {status.selected_candidates.length > 0
                  ? `${status.selected_candidates.length} highlighted — score / similarity / composite picks per worker.`
                  : "Pool from history search before worker selection."}
              </p>
              <div className="auto-mode-found-list">
                {status.found_candidates.map((candidate) => (
                  <AutoModeFoundCandidateCard
                    key={candidate.index}
                    candidate={candidate}
                    selectionSlots={selectionByIndex.get(candidate.index) ?? []}
                  />
                ))}
              </div>
            </div>
          )}

          {status.assignments.length > 0 && (
            <div className="auto-mode-section">
              <span className="auto-mode-section-title">Worker assignments</span>
              <div className="auto-mode-assignment-table-wrap">
                <table className="auto-mode-param-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Algorithm</th>
                      <th>Candidate</th>
                      <th>Region</th>
                      <th>Dispatch</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.assignments.map((item) => (
                      <tr key={item.worker_id}>
                        <td>{item.worker_name}</td>
                        <td><code>{item.algorithm}</code></td>
                        <td>#{item.candidate_index + 1}</td>
                        <td>
                          {item.window ? <code>{item.window}</code> : "—"}
                        </td>
                        <td>
                          {item.dispatch_ok ? (
                            <span className="chip chip-ok">accepted</span>
                          ) : (
                            <span className="chip chip-warn" title={item.dispatch_error ?? undefined}>
                              failed
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      <AutoModeTunableEditor
        open={editingParams}
        config={config}
        tool={config.tool}
        running={status.running}
        variant="edit"
        onClose={() => setEditingParams(false)}
        onSaved={refresh}
      />
    </div>
  );
}

function AutoModeFoundCandidateCard({
  candidate,
  selectionSlots,
}: {
  candidate: CandidatePreview;
  selectionSlots: AutoSelectedCandidate[];
}) {
  const selected = selectionSlots.length > 0;
  const region = candidate.source_window?.trim();
  const score = candidateHistoryScore(candidate);
  const composite = compositeCandidateScore(candidate);

  return (
    <article
      className={`auto-mode-found-item${selected ? " auto-mode-found-item--selected" : ""}`}
    >
      <div className="auto-mode-found-item-head">
        <span className="candidate-rank-badge">#{candidate.index + 1}</span>
        {selected ? (
          <span className="chip chip-accent">Selected</span>
        ) : (
          <span className="chip chip-muted">Pool</span>
        )}
      </div>

      {region ? (
        <code className="auto-mode-found-region">{region}</code>
      ) : (
        <span className="auto-mode-found-region-missing">No history region</span>
      )}

      <div className="auto-mode-found-metrics">
        <span>score {(score * 100).toFixed(1)}%</span>
        {candidate.similarity != null && (
          <span>sim {(candidate.similarity * 100).toFixed(0)}%</span>
        )}
        <span>composite {(composite * 100).toFixed(1)}%</span>
      </div>

      {selected && (
        <div className="auto-mode-found-selections">
          {selectionSlots.map((slot) => (
            <div
              key={`${slot.worker_name ?? "worker"}-${slot.selection_reason ?? "pick"}`}
              className="auto-mode-found-selection-row"
            >
              {slot.worker_name && (
                <span className="chip chip-accent">{slot.worker_name}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="auto-mode-found-conf">
        <ConfTooltip conf={candidate.base_conf} label="Conf" />
      </div>
    </article>
  );
}
