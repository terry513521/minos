import { useCallback, useEffect, useState } from "react";
import { api, AutoModeStatus } from "../api/client";
import { formatLocalDateTime } from "../hooks/useSubmissionCountdown";
import { formatParamInterval, paramIntervalsFromAutoConfig } from "../utils/autoModeSync";

export const AUTO_MODE_CHANGED_EVENT = "effortless:auto-mode-changed";

export function AutoModePanel() {
  const [status, setStatus] = useState<AutoModeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .getAutoMode()
      .then((next) => {
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
    return error ? <div className="alert error auto-mode-panel">{error}</div> : null;
  }

  const config = status.config;
  const paramIntervals = paramIntervalsFromAutoConfig(config);

  return (
    <div className={`auto-mode-panel${status.enabled ? " auto-mode-panel--on" : ""}`}>
      <div className="auto-mode-panel-head">
        <h4 className="auto-mode-panel-title">Auto mode</h4>
        <div className="auto-mode-panel-badges">
          <span className={`badge ${status.enabled ? "online" : "offline"}`}>
            {status.enabled ? "Enabled" : "Disabled"}
          </span>
          {status.running && <span className="badge running">Running</span>}
        </div>
      </div>

      {status.enabled && (
        <>
          <p className="auto-mode-panel-lead">
            Overnight orchestration for <strong>VM</strong>, <strong>Big</strong>, and{" "}
            <strong>Igno</strong>. Start via{" "}
            <code>POST /api/v1/auto/start</code> with the round region. Export via{" "}
            <code>POST /api/v1/auto/best</code>.
          </p>

          <div className="auto-mode-grid">
            <div className="auto-mode-card">
              <span className="auto-mode-card-label">Selection</span>
              <p>
                Find {config.find_k} candidates → top {config.select_k} by{" "}
                {config.score_weight}×score + {config.similarity_weight}×similarity
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
              <p>Concurrency: {config.concurrency}</p>
            </div>
          </div>

          <div className="auto-mode-section">
            <span className="auto-mode-section-title">Tunable parameters</span>
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
            <div className="auto-mode-worker-table-wrap">
              <table className="auto-mode-param-table">
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Algorithm</th>
                  </tr>
                </thead>
                <tbody>
                  {config.worker_names.map((name) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td><code>{config.worker_algorithms[name] ?? "—"}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {status.selected_candidates.length > 0 && (
            <div className="auto-mode-section">
              <span className="auto-mode-section-title">
                Selected base confs ({status.selected_candidates.length})
              </span>
              <div className="auto-mode-candidate-list">
                {status.selected_candidates.map((candidate) => (
                  <div key={candidate.index} className="auto-mode-candidate-item">
                    <span className="chip chip-muted">#{candidate.index + 1}</span>
                    <span>
                      composite {(candidate.composite_score * 100).toFixed(1)}%
                    </span>
                    {candidate.history_score != null && (
                      <span>score {(candidate.history_score * 100).toFixed(1)}%</span>
                    )}
                    {candidate.similarity != null && (
                      <span>sim {(candidate.similarity * 100).toFixed(0)}%</span>
                    )}
                  </div>
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
                      <th>Composite</th>
                      <th>Dispatch</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.assignments.map((item) => (
                      <tr key={item.worker_id}>
                        <td>{item.worker_name}</td>
                        <td><code>{item.algorithm}</code></td>
                        <td>#{item.candidate_index + 1}</td>
                        <td>{(item.composite_score * 100).toFixed(1)}%</td>
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
    </div>
  );
}
