import { useCallback, useEffect, useRef, useState } from "react";
import { api, AutoModeRoundRecord, AutoModeStatus, AutoSelectedCandidate, CandidatePreview } from "../api/client";
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
  workerConcurrencyFromAutoConfig,
  workerLimitSecondsFromAutoConfig,
  workerTrialCountsFromAutoConfig,
  workerTrialMemoryGbFromAutoConfig,
  workerTrialThreadsFromAutoConfig,
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
  const [roundHistory, setRoundHistory] = useState<AutoModeRoundRecord[]>([]);
  const [roundHistoryError, setRoundHistoryError] = useState<string | null>(null);
  const [expandedRoundId, setExpandedRoundId] = useState<string | null>(null);
  const editingParamsRef = useRef(false);
  editingParamsRef.current = editingParams;

  const refreshRoundHistory = useCallback(() => {
    api
      .listAutoRounds(50)
      .then((rows) => {
        setRoundHistory(rows);
        setRoundHistoryError(null);
      })
      .catch((err: Error) => setRoundHistoryError(err.message));
  }, []);

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
    refreshRoundHistory();
  }, [refreshRoundHistory]);

  useEffect(() => {
    refresh();
    function onChanged() {
      refresh();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onChanged);
    const intervalId = window.setInterval(() => {
      if (!editingParamsRef.current) refresh();
    }, 5000);
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
  const workerTrialThreads = workerTrialThreadsFromAutoConfig(config);
  const workerTrialMemoryGb = workerTrialMemoryGbFromAutoConfig(config);
  const workerTrialCounts = workerTrialCountsFromAutoConfig(config);
  const workerLimitSeconds = workerLimitSecondsFromAutoConfig(config);
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
            title="Edit parameters — changes apply on the next auto start"
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
        <span className="auto-mode-section-title">Worker settings</span>
        <div className="auto-mode-worker-algorithm-summary">
          {config.worker_names.map((workerName) => (
            <span key={workerName} className="chip chip-muted">
              {workerName}: {workerAlgorithms[workerName]} · {workerTrialCounts[workerName]} trials ·{" "}
              {Math.round((workerLimitSeconds[workerName] ?? config.limit_seconds) / 60)} min ·{" "}
              {workerTrialThreads[workerName]} CPU · {workerTrialMemoryGb[workerName]} GB
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
                Find {config.find_k} candidates → assign{" "}
                {config.worker_names.length > 0
                  ? config.worker_names
                      .map((name, index) => {
                        const reasons = ["top score", "most similar", "best composite"] as const;
                        return `${name} ${reasons[index % reasons.length]}`;
                      })
                      .join(", ")
                  : "registered workers"}
                .
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
              <p>Time limit: {Math.round((status.limit_seconds ?? config.limit_seconds) / 60)} min</p>
              <p>Trials: {config.adaptive_max_trials + 1} (1 base + {config.adaptive_max_trials} search)</p>
              {status.running && status.started_at && (
                <p className="auto-mode-limit-row">
                  <LimitCountdownBadge
                    startedAt={status.started_at}
                    limitSeconds={status.limit_seconds ?? config.limit_seconds}
                    active={status.running}
                    className="auto-mode-limit-countdown"
                  />
                </p>
              )}
              <p>
                Concurrency:{" "}
                {config.worker_names.length > 0
                  ? config.worker_names
                      .map((name) => {
                        const value =
                          workerConcurrencyFromAutoConfig(config)[name] ?? config.concurrency;
                        return `${name}: ${value}`;
                      })
                      .join(", ")
                  : config.concurrency}
              </p>
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
                          ) : status.running ? (
                            <span
                              className="chip chip-pending"
                              title={
                                item.dispatch_error
                                  ? `${item.dispatch_error} — retrying while session runs`
                                  : "Waiting for worker — retrying while session runs"
                              }
                            >
                              pending
                            </span>
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

      <div className="auto-mode-section">
        <div className="auto-mode-section-head">
          <span className="auto-mode-section-title">Round history</span>
        </div>
        {roundHistoryError && <div className="alert error">{roundHistoryError}</div>}
        {roundHistory.length === 0 ? (
          <p className="auto-mode-muted">
            Completed auto rounds appear here with each worker&apos;s best score and conf.
          </p>
        ) : (
          <div className="auto-mode-round-history">
            {roundHistory.map((round) => {
              const expanded = expandedRoundId === round.id;
              return (
                <div key={round.id} className="auto-mode-round-card">
                  <button
                    type="button"
                    className="auto-mode-round-card-head"
                    onClick={() => setExpandedRoundId(expanded ? null : round.id)}
                    aria-expanded={expanded}
                  >
                    <div className="auto-mode-round-card-summary">
                      <code className="auto-mode-round-region">{round.region}</code>
                      <span className="auto-mode-round-meta">
                        {formatLocalDateTime(round.ended_at)} · {formatRoundEndReason(round.end_reason)}
                      </span>
                    </div>
                    <div className="auto-mode-round-winner">
                      {round.winner_worker_name ? (
                        <>
                          <span className="auto-mode-round-winner-name">{round.winner_worker_name}</span>
                          <span className="metric-pill">
                            {round.winner_score != null ? round.winner_score.toFixed(4) : "—"}
                          </span>
                        </>
                      ) : (
                        <span className="auto-mode-muted">No scored workers</span>
                      )}
                    </div>
                  </button>
                  {expanded && (
                    <div className="auto-mode-round-workers">
                      <table className="auto-mode-param-table">
                        <thead>
                          <tr>
                            <th>Worker</th>
                            <th>Algorithm</th>
                            <th>Candidate</th>
                            <th>Best score</th>
                            <th>Trials</th>
                            <th>Conf</th>
                          </tr>
                        </thead>
                        <tbody>
                          {round.worker_results.map((worker) => (
                            <tr key={`${round.id}-${worker.worker_id}`}>
                              <td>{worker.worker_name}</td>
                              <td><code>{worker.algorithm ?? "—"}</code></td>
                              <td>
                                {worker.candidate_index != null
                                  ? `#${worker.candidate_index + 1}`
                                  : "—"}
                              </td>
                              <td>
                                {worker.best_score != null ? worker.best_score.toFixed(4) : "—"}
                              </td>
                              <td>{worker.trials_evaluated || "—"}</td>
                              <td>
                                {Object.keys(worker.best_conf).length > 0 ? (
                                  <ConfTooltip conf={worker.best_conf} />
                                ) : (
                                  worker.error ? (
                                    <span className="chip chip-warn" title={worker.error}>
                                      error
                                    </span>
                                  ) : (
                                    "—"
                                  )
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

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

function formatRoundEndReason(reason: string): string {
  switch (reason) {
    case "best_export":
      return "Exported best";
    case "restart":
      return "Session restart";
    case "time_limit":
      return "Time limit";
    case "stop_all":
      return "Stop all";
    default:
      return reason;
  }
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
