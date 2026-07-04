import { LimitCountdownBadge } from "./LimitCountdownBadge";
import { bestConfDownloadFileName, downloadConfFile } from "../utils/confDisplay";
import {
  formatWorkerBestScore,
  sortWorkerLiveStatusesByScore,
  WorkerLiveStatus,
  workerBestStatusClass,
} from "../utils/workerLiveStatus";

interface WorkerStatusOverviewProps {
  statuses: WorkerLiveStatus[];
}

export function WorkerStatusOverview({ statuses }: WorkerStatusOverviewProps) {
  if (statuses.length === 0) return null;

  const rows = sortWorkerLiveStatusesByScore(statuses);

  return (
    <section className="worker-status-overview panel" aria-label="Worker optimization status">
      <div className="worker-status-overview-head">
        <h3 className="worker-status-overview-title">Workers</h3>
        <p className="worker-status-overview-lead">Live best score and trial progress, highest score first.</p>
      </div>
      <ul className="worker-status-overview-list">
        {rows.map((row) => (
          <li key={row.workerId} className="worker-status-overview-card">
            <div className="worker-status-overview-card-top">
              <span className="worker-status-overview-name">{row.workerName}</span>
              <span
                className={`badge ${row.connected ? "online" : "offline"}`}
                title={row.connected ? "Connected" : "Not connected"}
              >
                {row.connected ? "Connected" : "Offline"}
              </span>
            </div>

            <div className="worker-status-overview-metrics">
              <div className="worker-status-overview-score-block">
                <span className="worker-status-overview-label">Best</span>
                <span className="worker-status-overview-score">
                  {formatWorkerBestScore(row.bestScore)}
                </span>
              </div>

              <div className="worker-status-overview-trials-block">
                <span className="worker-status-overview-label">Trials</span>
                <span className="worker-status-overview-trials">{row.trialLabel}</span>
              </div>

              <div className="worker-status-overview-state-block">
                <span className="worker-status-overview-label">State</span>
                {row.displayStatus ? (
                  <span className={`badge ${workerBestStatusClass(row.displayStatus)}`}>
                    {row.displayStatus}
                  </span>
                ) : row.loadError ? (
                  <span className="worker-status-overview-error" title={row.loadError}>
                    unavailable
                  </span>
                ) : (
                  <span className="worker-status-overview-muted">—</span>
                )}
              </div>
            </div>

            <div className="worker-status-overview-actions">
              {row.isOptimizing || row.displayStatus === "time limited" ? (
                <LimitCountdownBadge
                  startedAt={row.runStartedAt}
                  limitSeconds={row.runLimitSeconds}
                  active
                  className="worker-status-overview-countdown"
                />
              ) : null}
              {row.hasConf ? (
                <button
                  type="button"
                  className="button ghost worker-status-overview-download"
                  onClick={() =>
                    downloadConfFile(
                      row.bestConf,
                      bestConfDownloadFileName(row.baseConfRegion, row.bestScore),
                    )
                  }
                >
                  Download conf
                </button>
              ) : (
                <span className="worker-status-overview-muted worker-status-overview-no-conf">
                  No conf yet
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
