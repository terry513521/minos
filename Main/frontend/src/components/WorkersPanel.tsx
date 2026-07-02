import { DragEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  FindCandidatesResponse,
  WorkerBestScoreResult,
  WorkerDispatchResult,
  WorkerHealthCheckResult,
  WorkerRecord,
} from "../api/client";
import { formatLocalDateTime } from "../hooks/useSubmissionCountdown";
import {
  ALGORITHM_OPTIONS,
  assignmentParamsForTool,
  createAssignment,
  limitMinutesToSeconds,
  secondsToLimitMinutes,
  TOOLKIT_OPTIONS,
  ToolkitOption,
  WorkerAssignment,
} from "../types/workerAssignment";
import {
  CANDIDATE_DRAG_MIME,
  CandidateDragPayload,
} from "../utils/candidateAssign";
import {
  buildDispatchParamIntervals,
  defaultParamInterval,
  ParamInterval,
} from "../utils/paramBounds";
import { WORKERS_CHANGED_EVENT } from "./AddWorkerModal";
import { ConfParamPicker } from "./ConfParamPicker";
import { ConfTooltip } from "./ConfTooltip";

const CONCURRENCY_OPTIONS = [1, 2, 3, 4, 6, 8];
/** Background poll for worker GET /best — manual Refresh fetches immediately. */
const BEST_POLL_INTERVAL_MS = 5 * 60 * 1000;

interface WorkersPanelProps {
  candidateContext?: FindCandidatesResponse | null;
}

function isWorkerConnected(
  status: WorkerRecord["status"],
  health: WorkerHealthCheckResult | "loading" | undefined,
): boolean {
  if (health && health !== "loading") {
    return health.ok;
  }
  return status === "online" || status === "draining";
}

function connectionLabel(
  status: WorkerRecord["status"],
  health: WorkerHealthCheckResult | "loading" | undefined,
): string {
  return isWorkerConnected(status, health) ? "Connected" : "Not connected";
}

function connectionClass(
  status: WorkerRecord["status"],
  health: WorkerHealthCheckResult | "loading" | undefined,
): string {
  return isWorkerConnected(status, health) ? "online" : "offline";
}

function formatBestScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${(score * 100).toFixed(2)}%`;
}

function hasConfContent(conf: Record<string, unknown>): boolean {
  return Object.keys(conf).length > 0;
}

function bestStatusClass(status: string | null | undefined): string {
  if (status === "ready") return "online";
  if (status === "optimizing") return "running";
  if (status === "error") return "failed";
  return "offline";
}

export function WorkersPanel({ candidateContext = null }: WorkersPanelProps) {
  const [workers, setWorkers] = useState<WorkerRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, WorkerAssignment>>({});
  const [dragOverWorkerId, setDragOverWorkerId] = useState<string | null>(null);
  const [healthByWorker, setHealthByWorker] = useState<
    Record<string, WorkerHealthCheckResult | "loading">
  >({});
  const [bestByWorker, setBestByWorker] = useState<
    Record<string, WorkerBestScoreResult | "loading">
  >({});
  const [dispatchByWorker, setDispatchByWorker] = useState<
    Record<string, WorkerDispatchResult | null>
  >({});
  const [removingWorkerId, setRemovingWorkerId] = useState<string | null>(null);
  const [stoppingWorkerId, setStoppingWorkerId] = useState<string | null>(null);
  const [baseConfByWorker, setBaseConfByWorker] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .listWorkers()
      .then(setWorkers)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    function onChanged() {
      refresh();
    }
    window.addEventListener(WORKERS_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKERS_CHANGED_EVENT, onChanged);
  }, [refresh]);

  useEffect(() => {
    if (!candidateContext) {
      setAssignments({});
    }
  }, [candidateContext]);

  function updateAssignment(workerId: string, patch: Partial<WorkerAssignment>) {
    setAssignments((prev) => {
      const current = prev[workerId];
      if (!current) return prev;
      return { ...prev, [workerId]: { ...current, ...patch } };
    });
  }

  function clearAssignment(workerId: string) {
    setAssignments((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setDispatchByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
  }

  function handleDragOver(e: DragEvent, workerId: string) {
    if (!candidateContext) return;
    if (!e.dataTransfer.types.includes(CANDIDATE_DRAG_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDragOverWorkerId(workerId);
  }

  function handleDragLeave(workerId: string) {
    setDragOverWorkerId((current) => (current === workerId ? null : current));
  }

  function handleDrop(e: DragEvent, workerId: string) {
    e.preventDefault();
    setDragOverWorkerId(null);
    if (!candidateContext) return;

    const raw = e.dataTransfer.getData(CANDIDATE_DRAG_MIME);
    if (!raw) return;

    let payload: CandidateDragPayload;
    try {
      payload = JSON.parse(raw) as CandidateDragPayload;
    } catch {
      return;
    }

    const candidate = candidateContext.candidates.find((c) => c.index === payload.index);
    if (!candidate) return;

    setAssignments((prev) => ({
      ...prev,
      [workerId]: createAssignment(candidate, candidateContext),
    }));
    setDispatchByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
  }

  async function handleHealthCheck(workerId: string) {
    setHealthByWorker((prev) => ({ ...prev, [workerId]: "loading" }));
    try {
      const result = await api.checkWorkerHealth(workerId);
      setHealthByWorker((prev) => ({ ...prev, [workerId]: result }));
    } catch (err) {
      setHealthByWorker((prev) => ({
        ...prev,
        [workerId]: {
          worker_id: workerId,
          ok: false,
          status_code: null,
          health: null,
          error: err instanceof Error ? err.message : "Health check failed",
        },
      }));
    }
  }

  const pollWorkerBest = useCallback(async (workerId: string, silent = false) => {
    if (!silent) {
      setBestByWorker((prev) => ({ ...prev, [workerId]: "loading" }));
    }
    try {
      const result = await api.fetchWorkerBest(workerId);
      setBestByWorker((prev) => ({ ...prev, [workerId]: result }));
    } catch (err) {
      if (!silent) {
        setBestByWorker((prev) => ({
          ...prev,
          [workerId]: {
            worker_id: workerId,
            ok: false,
            status_code: null,
            status: null,
            job_id: null,
            window: null,
            tool: null,
            best_score: null,
            best_conf: {},
            trials_evaluated: 0,
            updated_at: null,
            message: null,
            error: err instanceof Error ? err.message : "Failed to fetch best score",
          },
        }));
      }
    }
  }, []);

  const handleRefreshBest = useCallback(
    (workerId: string) => {
      void pollWorkerBest(workerId, false);
    },
    [pollWorkerBest],
  );

  async function handleStopOptimization(workerId: string) {
    setStoppingWorkerId(workerId);
    try {
      const result = await api.stopWorkerOptimization(workerId);
      if (!result.ok) {
        setBestByWorker((prev) => {
          const current = prev[workerId];
          if (!current || current === "loading") return prev;
          return {
            ...prev,
            [workerId]: {
              ...current,
              message: result.error ?? "Stop request failed",
            },
          };
        });
        return;
      }
      void pollWorkerBest(workerId, true);
    } catch (err) {
      setBestByWorker((prev) => {
        const current = prev[workerId];
        if (!current || current === "loading") return prev;
        return {
          ...prev,
          [workerId]: {
            ...current,
            message: err instanceof Error ? err.message : "Stop request failed",
          },
        };
      });
    } finally {
      setStoppingWorkerId(null);
    }
  }

  useEffect(() => {
    if (workers.length === 0) return;

    const pollable = workers.filter((worker) => worker.base_url);
    if (pollable.length === 0) return;

    const tick = () => {
      pollable.forEach((worker) => {
        void pollWorkerBest(worker.id, true);
      });
    };

    tick();
    const intervalId = window.setInterval(tick, BEST_POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [workers, pollWorkerBest]);

  async function handleDispatch(workerId: string) {
    const assignment = assignments[workerId];
    if (!assignment || assignment.selectedParams.length === 0) return;

    updateAssignment(workerId, { dispatching: true, dispatchError: null });
    try {
      const result = await api.dispatchToWorker(workerId, {
        window: assignment.window,
        tool: assignment.tool,
        base_conf: assignment.candidate.base_conf,
        params: assignment.selectedParams,
        param_intervals: buildDispatchParamIntervals(
          assignment.tool,
          assignment.selectedParams,
          assignment.paramIntervals,
        ),
        concurrency: assignment.concurrency,
        algorithm: assignment.algorithm,
        limit_seconds: assignment.limitSeconds,
        candidate_index: assignment.candidate.index,
      });
      setDispatchByWorker((prev) => ({ ...prev, [workerId]: result }));
      updateAssignment(workerId, {
        dispatching: false,
        dispatchError: result.ok ? null : result.error ?? "Dispatch failed",
      });
      if (result.ok) {
        setBaseConfByWorker((prev) => ({
          ...prev,
          [workerId]: assignment.candidate.base_conf,
        }));
        void pollWorkerBest(workerId, true);
      }
    } catch (err) {
      updateAssignment(workerId, {
        dispatching: false,
        dispatchError: err instanceof Error ? err.message : "Dispatch failed",
      });
    }
  }

  function toggleParam(workerId: string, param: string) {
    const assignment = assignments[workerId];
    if (!assignment) return;

    const options = assignment.candidate.base_conf[`${assignment.tool}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";

    if (assignment.selectedParams.includes(param)) {
      const selected = assignment.selectedParams.filter((p) => p !== param);
      const { [param]: _removed, ...restIntervals } = assignment.paramIntervals;
      updateAssignment(workerId, { selectedParams: selected, paramIntervals: restIntervals });
      return;
    }

    updateAssignment(workerId, {
      selectedParams: [...assignment.selectedParams, param],
      paramIntervals: {
        ...assignment.paramIntervals,
        [param]: defaultParamInterval(assignment.tool, param, baseValue),
      },
    });
  }

  function updateParamInterval(
    workerId: string,
    param: string,
    patch: Partial<ParamInterval>,
  ) {
    const assignment = assignments[workerId];
    if (!assignment) return;
    const current = assignment.paramIntervals[param] ?? {};
    updateAssignment(workerId, {
      paramIntervals: {
        ...assignment.paramIntervals,
        [param]: { ...current, ...patch },
      },
    });
  }

  function clearWorkerState(workerId: string) {
    setAssignments((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setHealthByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setBestByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setDispatchByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setBaseConfByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
  }

  async function handleRemoveWorker(workerId: string, workerName: string) {
    if (!window.confirm(`Remove worker "${workerName}" from the control plane?`)) {
      return;
    }

    setRemovingWorkerId(workerId);
    setError(null);
    try {
      await api.deleteWorker(workerId);
      clearWorkerState(workerId);
      refresh();
      window.dispatchEvent(new Event(WORKERS_CHANGED_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove worker");
    } finally {
      setRemovingWorkerId(null);
    }
  }

  return (
    <div className="workers-panel">
      <div className="workers-panel-head">
        <h3 className="workers-panel-title">Workers</h3>
        <button type="button" className="button ghost workers-refresh" onClick={refresh} disabled={loading}>
          Refresh
        </button>
      </div>

      {candidateContext && (
        <p className="workers-drop-hint">
          Drag a candidate card onto a worker to assign base conf and tune params.
        </p>
      )}

      {error && <div className="alert error">{error}</div>}
      {loading && workers.length === 0 ? (
        <p className="empty-state">Loading workers…</p>
      ) : workers.length === 0 ? (
        <p className="empty-state">No workers registered yet.</p>
      ) : (
        <div className="worker-card-grid">
          {workers.map((worker) => {
            const assignment = assignments[worker.id];
            const health = healthByWorker[worker.id];
            const best = bestByWorker[worker.id];
            const dispatchResult = dispatchByWorker[worker.id];
            const score =
              assignment?.candidate.history_score ?? assignment?.candidate.rank_score;
            const isOptimizing = Boolean(
              best && best !== "loading" && best.ok && best.status === "optimizing",
            );
            const compareBaseConf =
              assignment?.candidate.base_conf ?? baseConfByWorker[worker.id] ?? null;

            return (
              <article
                key={worker.id}
                className={`worker-card${dragOverWorkerId === worker.id ? " worker-card-drop-target" : ""}${assignment ? " worker-card-assigned worker-card-has-assignment" : ""}`}
                onDragOver={(e) => handleDragOver(e, worker.id)}
                onDragLeave={() => handleDragLeave(worker.id)}
                onDrop={(e) => handleDrop(e, worker.id)}
              >
                <div className="worker-card-main">
                <div className="worker-card-top">
                  <span className="worker-card-name">{worker.name}</span>
                  <div className="worker-card-top-meta">
                    <span className={`badge ${connectionClass(worker.status, health)}`}>
                      {connectionLabel(worker.status, health)}
                    </span>
                    <button
                      type="button"
                      className="button ghost worker-remove-btn"
                      onClick={() => handleRemoveWorker(worker.id, worker.name)}
                      disabled={removingWorkerId === worker.id}
                    >
                      {removingWorkerId === worker.id ? "Removing…" : "Remove"}
                    </button>
                  </div>
                </div>

                <div className="worker-card-actions">
                  <button
                    type="button"
                    className="button ghost worker-health-btn"
                    onClick={() => handleHealthCheck(worker.id)}
                    disabled={!worker.health_url || health === "loading"}
                  >
                    {health === "loading" ? "Checking…" : "Check health"}
                  </button>
                </div>

                <div className="worker-best-block">
                  <div className="worker-best-head">
                    <span className="worker-assignment-label">Current best</span>
                    <div className="worker-best-actions">
                      {best && best !== "loading" && best.ok && best.status === "optimizing" && (
                        <button
                          type="button"
                          className="button ghost worker-best-stop"
                          onClick={() => handleStopOptimization(worker.id)}
                          disabled={!worker.base_url || stoppingWorkerId === worker.id}
                        >
                          {stoppingWorkerId === worker.id ? "Stopping…" : "Stop"}
                        </button>
                      )}
                      <button
                        type="button"
                        className="button ghost worker-best-refresh"
                        onClick={() => handleRefreshBest(worker.id)}
                        disabled={!worker.base_url || best === "loading"}
                      >
                        {best === "loading" ? "Refreshing…" : "Refresh"}
                      </button>
                    </div>
                  </div>

                  {best && best !== "loading" && !best.ok && (
                    <div className="worker-best-empty">{best.error ?? "Could not load best score"}</div>
                  )}

                  {best && best !== "loading" && best.ok && (
                    <div className="worker-best-body">
                      <div className="worker-best-score-row">
                        <span className="worker-best-score">{formatBestScore(best.best_score)}</span>
                        {best.status && (
                          <span className={`badge ${bestStatusClass(best.status)}`}>{best.status}</span>
                        )}
                      </div>

                      {(best.tool || best.window) && (
                        <div className="worker-best-meta">
                          {best.tool && <span className="chip chip-accent">{best.tool}</span>}
                          {best.window && <code className="worker-best-window">{best.window}</code>}
                        </div>
                      )}

                      {best.trials_evaluated > 0 && (
                        <span className="worker-best-trials">{best.trials_evaluated} trials</span>
                      )}

                      {hasConfContent(best.best_conf) && (
                        <div className="worker-best-conf">
                          <ConfTooltip
                            conf={best.best_conf}
                            label="Best conf"
                            layout="panel"
                            showActions
                            baseConf={compareBaseConf}
                            downloadFileName={`${worker.name.replace(/[^\w.-]+/g, "-")}-best-conf`}
                          />
                        </div>
                      )}

                      {best.updated_at && (
                        <span className="worker-best-updated">
                          Updated {formatLocalDateTime(best.updated_at)}
                        </span>
                      )}

                      {best.message && !hasConfContent(best.best_conf) && best.best_score == null && (
                        <span className="worker-best-message">{best.message}</span>
                      )}
                    </div>
                  )}

                  {!best && (
                    <div className="worker-best-empty">
                      Use Refresh to load best score and conf (auto-refresh every 5 min).
                    </div>
                  )}
                </div>

                {health && health !== "loading" && (
                  <div className={`worker-health-result${health.ok ? " ok" : " error"}`}>
                    {health.ok && health.health ? (
                      <>
                        <span>CPU {String(health.health.cpu_count ?? "—")}</span>
                        <span>RAM {String(health.health.ram_available ?? "—")} free</span>
                      </>
                    ) : (
                      <span>{health.error ?? "Health check failed"}</span>
                    )}
                  </div>
                )}

                <dl className="worker-endpoints">
                  <div>
                    <dt>Health</dt>
                    <dd><code>{worker.health_url ?? "—"}</code></dd>
                  </div>
                  <div>
                    <dt>Main API</dt>
                    <dd><code>{worker.base_url ?? "—"}</code></dd>
                  </div>
                </dl>

                <div className="worker-card-meta">
                  {worker.version && <span className="chip chip-muted">v{worker.version}</span>}
                  <span className="worker-heartbeat">
                    {worker.last_heartbeat
                      ? `Heartbeat ${formatLocalDateTime(worker.last_heartbeat)}`
                      : "No heartbeat"}
                  </span>
                </div>
                </div>

                {assignment && (
                  <div className="worker-assignment">
                    <div className="worker-assignment-head">
                      <span className="worker-assignment-title">
                        Candidate #{assignment.candidate.index + 1}
                        {score != null && (
                          <span className="worker-assignment-score">
                            {(score * 100).toFixed(1)}%
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        className="button ghost worker-assignment-clear"
                        onClick={() => clearAssignment(worker.id)}
                      >
                        Clear
                      </button>
                    </div>

                    <ConfParamPicker
                      baseConf={assignment.candidate.base_conf}
                      tool={assignment.tool}
                      selectedParams={assignment.selectedParams}
                      paramIntervals={assignment.paramIntervals}
                      onToggle={(param) => toggleParam(worker.id, param)}
                      onIntervalChange={(param, patch) =>
                        updateParamInterval(worker.id, param, patch)
                      }
                    />

                    <div className="worker-assignment-options">
                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Toolkit</span>
                        <select
                          value={assignment.tool}
                          onChange={(e) =>
                            updateAssignment(worker.id, {
                              ...assignmentParamsForTool(
                                assignment,
                                e.target.value as ToolkitOption,
                              ),
                            })
                          }
                        >
                          {TOOLKIT_OPTIONS.map((tool) => (
                            <option key={tool} value={tool}>
                              {tool}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Algorithm</span>
                        <select
                          value={assignment.algorithm}
                          onChange={(e) =>
                            updateAssignment(worker.id, {
                              algorithm: e.target.value as WorkerAssignment["algorithm"],
                            })
                          }
                        >
                          {ALGORITHM_OPTIONS.map((algorithm) => (
                            <option key={algorithm} value={algorithm}>
                              {algorithm}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Time limit</span>
                        <div className="worker-duration-input">
                          <input
                            type="number"
                            min={1}
                            max={1440}
                            step={1}
                            value={secondsToLimitMinutes(assignment.limitSeconds)}
                            onChange={(e) =>
                              updateAssignment(worker.id, {
                                limitSeconds: limitMinutesToSeconds(Number(e.target.value)),
                              })
                            }
                            aria-label="Time limit in minutes"
                          />
                          <span className="worker-duration-unit">min</span>
                        </div>
                      </label>

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Concurrency</span>
                        <select
                          value={assignment.concurrency}
                          onChange={(e) =>
                            updateAssignment(worker.id, { concurrency: Number(e.target.value) })
                          }
                        >
                          {CONCURRENCY_OPTIONS.map((n) => (
                            <option key={n} value={n}>
                              {n}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <button
                      type="button"
                      className="button primary worker-dispatch-btn"
                      disabled={
                        assignment.dispatching ||
                        isOptimizing ||
                        !worker.base_url ||
                        assignment.selectedParams.length === 0
                      }
                      onClick={() => handleDispatch(worker.id)}
                    >
                      {assignment.dispatching
                        ? "Starting…"
                        : isOptimizing
                          ? "Optimizing…"
                          : "Run optimization"}
                    </button>

                    {assignment.dispatchError && (
                      <div className="alert error worker-dispatch-alert">{assignment.dispatchError}</div>
                    )}

                    {dispatchResult?.ok && (
                      <div className="worker-dispatch-success">
                        Job accepted — use Refresh above for live best score and conf.
                      </div>
                    )}
                  </div>
                )}

                {!assignment && candidateContext && (
                  <p className="worker-drop-placeholder">Drop candidate here</p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
