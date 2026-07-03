import { DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  AutoModeStatus,
  FindCandidatesResponse,
  WorkerBestScoreResult,
  WorkerDispatchResult,
  WorkerHealthCheckResult,
  WorkerRecord,
} from "../api/client";
import { formatLocalDateTime, usePeriodicTick } from "../hooks/useSubmissionCountdown";
import { LimitCountdownBadge } from "./LimitCountdownBadge";
import { WorkerEndpointsEditor } from "./WorkerEndpointsEditor";
import {
  ALGORITHM_OPTIONS,
  assignmentParamsForTool,
  buildDispatchBaseConf,
  clampTrialMemoryGb,
  clampTrialThreads,
  clampTotalTrials,
  createAssignment,
  adaptiveMaxTrialsFromTotal,
  DEFAULT_ADAPTIVE_MAX_TRIALS,
  isAdaptiveAlgorithm,
  limitMinutesToSeconds,
  normalizeWorkerAssignment,
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
import { parseToolOptionValue, setToolOption } from "../utils/confEdit";
import { WORKERS_CHANGED_EVENT } from "./AddWorkerModal";
import { ConfParamPicker } from "./ConfParamPicker";
import { ConfManualEditor } from "./ConfManualEditor";
import { ConfTooltip } from "./ConfTooltip";
import {
  clearWorkerPanelEntry,
  clearDismissedWorkerAssignments,
  dismissWorkerAssignment,
  loadDismissedWorkerAssignments,
  loadWorkerPanelState,
  restoreWorkerAssignment,
  saveWorkerPanelState,
} from "../utils/workerPanelStorage";
import {
  autoAssignmentsForStatus,
  manualAssignmentsFromEndedAuto,
  previewAssignmentsFromAutoConfig,
} from "../utils/autoModeSync";
import { loadAutoModeState, saveAutoModeState } from "../utils/autoModeStorage";
import {
  isWorkerJobRunning,
  resolveWorkerJobStatus,
} from "../utils/workerJobStatus";
import {
  nextActiveWorkerOrder,
  shouldPollWorkerBest,
  sortWorkersForDisplay,
} from "../utils/workerDisplayOrder";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";

const CONCURRENCY_OPTIONS = [1, 2, 3, 4, 6, 8];
/** Background poll for worker GET /best while optimization is running. */
const BEST_POLL_INTERVAL_MS = 1000;

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

function formatTrialProgress(
  evaluated: number,
  total: number | null | undefined,
  status: string | null | undefined,
): string {
  const done = Math.max(0, evaluated);
  const planned = total && total > 0 ? total : null;
  if (planned) {
    if (status === "optimizing") return `Trial ${done} / ${planned}`;
    return `${done} / ${planned} trials`;
  }
  if (done > 0) return `${done} trial${done === 1 ? "" : "s"}`;
  return "";
}

function trialTotal(
  best: WorkerBestScoreResult | undefined,
  dispatchResult: WorkerDispatchResult | null | undefined,
): number | null {
  if (best?.search_space_size && best.search_space_size > 0) {
    return best.search_space_size;
  }
  const fromDispatch = dispatchResult?.result?.search_space_size;
  if (typeof fromDispatch === "number" && fromDispatch > 0) {
    return fromDispatch;
  }
  return null;
}

function hasConfContent(conf: Record<string, unknown>): boolean {
  return Object.keys(conf).length > 0;
}

function bestStatusClass(status: string | null | undefined): string {
  if (status === "ready") return "online";
  if (status === "time limited") return "warn";
  if (status === "optimizing" || status === "stopping") return "running";
  if (status === "error") return "failed";
  return "offline";
}

function isJobActive(
  status: string | null | undefined,
  startedAt?: string | null,
  limitSeconds?: number | null,
  nowMs = Date.now(),
): boolean {
  return isWorkerJobRunning(status, startedAt, limitSeconds, nowMs);
}

function jobStartedAt(
  assignment: WorkerAssignment | undefined,
  autoModeStatus: AutoModeStatus | null,
  autoManaged: boolean,
): string | null {
  if (assignment?.dispatchedAt) return assignment.dispatchedAt;
  if (autoManaged && autoModeStatus?.started_at) return autoModeStatus.started_at;
  return null;
}

function formatTrialScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${(score * 100).toFixed(2)}%`;
}

function withoutLoadingBest(
  bestByWorker: Record<string, WorkerBestScoreResult | "loading">,
): Record<string, WorkerBestScoreResult> {
  return Object.fromEntries(
    Object.entries(bestByWorker).filter((entry): entry is [string, WorkerBestScoreResult] => {
      return entry[1] !== "loading";
    }),
  );
}

function withoutLoadingHealth(
  healthByWorker: Record<string, WorkerHealthCheckResult | "loading">,
): Record<string, WorkerHealthCheckResult> {
  return Object.fromEntries(
    Object.entries(healthByWorker).filter((entry): entry is [string, WorkerHealthCheckResult] => {
      return entry[1] !== "loading";
    }),
  );
}

export function WorkersPanel({ candidateContext = null }: WorkersPanelProps) {
  const persistedRef = useRef(loadWorkerPanelState());
  const persisted = persistedRef.current;
  const persistedAutoRef = useRef(loadAutoModeState());
  const initialAutoStatus = persistedAutoRef.current?.status ?? null;
  const initialDismissed = loadDismissedWorkerAssignments();

  const [workers, setWorkers] = useState<WorkerRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, WorkerAssignment>>(() => {
    const base = Object.fromEntries(
      Object.entries(persisted?.assignments ?? {}).map(([workerId, assignment]) => [
        workerId,
        normalizeWorkerAssignment(assignment),
      ]),
    );
    if (!initialAutoStatus) {
      return Object.fromEntries(
        Object.entries(base).filter(([workerId]) => !initialDismissed.has(workerId)),
      );
    }
    const manualFromAuto = manualAssignmentsFromEndedAuto(initialAutoStatus);
    const merged = { ...base, ...manualFromAuto };
    return Object.fromEntries(
      Object.entries(merged).filter(([workerId]) => !initialDismissed.has(workerId)),
    );
  });
  const [dismissedWorkers, setDismissedWorkers] = useState<Set<string>>(
    () => new Set(initialDismissed),
  );
  const dismissedWorkersRef = useRef(dismissedWorkers);
  dismissedWorkersRef.current = dismissedWorkers;
  const [dragOverWorkerId, setDragOverWorkerId] = useState<string | null>(null);
  const [healthByWorker, setHealthByWorker] = useState<
    Record<string, WorkerHealthCheckResult | "loading">
  >(() => persisted?.healthByWorker ?? {});
  const [bestByWorker, setBestByWorker] = useState<
    Record<string, WorkerBestScoreResult | "loading">
  >(() => persisted?.bestByWorker ?? {});
  const [dispatchByWorker, setDispatchByWorker] = useState<
    Record<string, WorkerDispatchResult | null>
  >(() => persisted?.dispatchByWorker ?? {});
  const [removingWorkerId, setRemovingWorkerId] = useState<string | null>(null);
  const [stoppingWorkerId, setStoppingWorkerId] = useState<string | null>(null);
  const [baseConfByWorker, setBaseConfByWorker] = useState<
    Record<string, Record<string, unknown>>
  >(() => persisted?.baseConfByWorker ?? {});
  const [activeWorkerOrder, setActiveWorkerOrder] = useState<Record<string, number>>({});
  const [refreshingBestByWorker, setRefreshingBestByWorker] = useState<
    Record<string, boolean>
  >({});
  const [autoModeEnabled, setAutoModeEnabled] = useState(
    () => initialAutoStatus?.enabled ?? false,
  );
  const [autoModeStatus, setAutoModeStatus] = useState<AutoModeStatus | null>(
    () => initialAutoStatus,
  );
  const [autoAssignmentsByWorker, setAutoAssignmentsByWorker] = useState<
    Record<string, WorkerAssignment>
  >(() => (initialAutoStatus ? autoAssignmentsForStatus(initialAutoStatus) : {}));

  const autoPreviewByWorker = useMemo(
    () =>
      autoModeStatus && autoModeEnabled
        ? previewAssignmentsFromAutoConfig(autoModeStatus, workers)
        : {},
    [autoModeStatus, autoModeEnabled, workers],
  );

  const effectiveAssignmentsByWorker = useMemo(() => {
    const merged = { ...assignments };
    for (const [workerId, assignment] of Object.entries(autoAssignmentsByWorker)) {
      if (!dismissedWorkers.has(workerId)) {
        merged[workerId] = assignment;
      }
    }
    for (const [workerId, assignment] of Object.entries(autoPreviewByWorker)) {
      if (!dismissedWorkers.has(workerId) && !merged[workerId]) {
        merged[workerId] = assignment;
      }
    }
    return merged;
  }, [assignments, autoAssignmentsByWorker, autoPreviewByWorker, dismissedWorkers]);

  const bestByWorkerRef = useRef(bestByWorker);
  bestByWorkerRef.current = bestByWorker;
  const effectiveAssignmentsRef = useRef(effectiveAssignmentsByWorker);
  effectiveAssignmentsRef.current = effectiveAssignmentsByWorker;

  const anyActiveJob = useMemo(() => {
    for (const worker of workers) {
      const best = bestByWorker[worker.id];
      if (
        best &&
        best !== "loading" &&
        best.ok &&
        (best.status === "optimizing" || best.status === "stopping")
      ) {
        return true;
      }
    }
    return false;
  }, [workers, bestByWorker]);

  const nowMs = usePeriodicTick(anyActiveJob);

  const displayWorkers = useMemo(
    () =>
      sortWorkersForDisplay(
        workers,
        bestByWorker,
        healthByWorker,
        effectiveAssignmentsByWorker,
        activeWorkerOrder,
        nowMs,
      ),
    [workers, bestByWorker, healthByWorker, effectiveAssignmentsByWorker, activeWorkerOrder, nowMs],
  );

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

  const refreshAutoMode = useCallback(() => {
    api
      .getAutoMode()
      .then((status) => {
        saveAutoModeState(status);
        setAutoModeEnabled(status.enabled);
        setAutoModeStatus(status);
        setAutoAssignmentsByWorker(autoAssignmentsForStatus(status));
        const manualFromAuto = manualAssignmentsFromEndedAuto(status);
        if (Object.keys(manualFromAuto).length > 0) {
          const dismissed = dismissedWorkersRef.current;
          setAssignments((prev) => {
            const next = { ...prev };
            for (const [workerId, assignment] of Object.entries(manualFromAuto)) {
              if (!dismissed.has(workerId)) {
                next[workerId] = assignment;
              }
            }
            return next;
          });
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshAutoMode();
    function onAutoChanged() {
      refreshAutoMode();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
    const intervalId = window.setInterval(refreshAutoMode, 5000);
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
      window.clearInterval(intervalId);
    };
  }, [refreshAutoMode]);

  useEffect(() => {
    if (!autoModeStatus?.running) return;
    setDismissedWorkers(new Set());
    clearDismissedWorkerAssignments();
  }, [autoModeStatus?.running, autoModeStatus?.started_at]);

  useEffect(() => {
    saveWorkerPanelState({
      assignments,
      baseConfByWorker,
      dispatchByWorker,
      bestByWorker: withoutLoadingBest(bestByWorker),
      healthByWorker: withoutLoadingHealth(healthByWorker),
    });
  }, [assignments, baseConfByWorker, dispatchByWorker, bestByWorker, healthByWorker]);

  useEffect(() => {
    if (workers.length === 0) return;
    const activeIds = new Set(workers.map((worker) => worker.id));
    const prune = <T,>(record: Record<string, T>): Record<string, T> =>
      Object.fromEntries(Object.entries(record).filter(([id]) => activeIds.has(id)));

    setAssignments((prev) => prune(prev));
    setBaseConfByWorker((prev) => prune(prev));
    setDispatchByWorker((prev) => prune(prev));
    setBestByWorker((prev) => prune(prev));
    setHealthByWorker((prev) => prune(prev));
  }, [workers]);

  useEffect(() => {
    setActiveWorkerOrder((current) => {
      const next = nextActiveWorkerOrder(
        current,
        workers,
        bestByWorker,
        effectiveAssignmentsByWorker,
        nowMs,
      );
      return next ?? current;
    });
  }, [workers, bestByWorker, effectiveAssignmentsByWorker, nowMs]);

  function updateAssignment(workerId: string, patch: Partial<WorkerAssignment>) {
    setAssignments((prev) => {
      const current = prev[workerId];
      if (!current) return prev;
      return { ...prev, [workerId]: { ...current, ...patch } };
    });
  }

  function clearAssignment(workerId: string) {
    setDismissedWorkers((prev) => {
      const next = new Set(prev);
      next.add(workerId);
      dismissWorkerAssignment(workerId);
      return next;
    });
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
    setBaseConfByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    clearWorkerPanelEntry(workerId);
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

    restoreWorkerAssignment(workerId);
    setDismissedWorkers((prev) => {
      if (!prev.has(workerId)) return prev;
      const next = new Set(prev);
      next.delete(workerId);
      return next;
    });

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
            search_space_size: 0,
            updated_at: null,
            message: null,
            trials: [],
            error: err instanceof Error ? err.message : "Failed to fetch best score",
          },
        }));
      }
    }
  }, []);

  const handleRefreshBest = useCallback(
    async (workerId: string) => {
      setRefreshingBestByWorker((prev) => ({ ...prev, [workerId]: true }));
      try {
        await pollWorkerBest(workerId, true);
      } finally {
        setRefreshingBestByWorker((prev) => ({ ...prev, [workerId]: false }));
      }
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

      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        try {
          const best = await api.fetchWorkerBest(workerId);
          setBestByWorker((prev) => ({ ...prev, [workerId]: best }));
          if (best.ok && best.status && !isJobActive(best.status)) {
            break;
          }
        } catch {
          break;
        }
      }
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
      const best = bestByWorkerRef.current;
      const assignmentsByWorker = effectiveAssignmentsRef.current;
      const tickNow = Date.now();
      for (const worker of pollable) {
        const assignment = assignmentsByWorker[worker.id];
        if (
          !shouldPollWorkerBest(
            best[worker.id],
            assignment,
            assignment?.dispatchedAt,
            assignment?.limitSeconds,
            tickNow,
          )
        ) {
          continue;
        }
        void pollWorkerBest(worker.id, true);
      }
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
        base_conf: buildDispatchBaseConf(
          assignment.candidate.base_conf,
          assignment.trialThreads,
          assignment.trialMemoryGb,
        ),
        params: assignment.selectedParams,
        param_intervals: buildDispatchParamIntervals(
          assignment.tool,
          assignment.selectedParams,
          assignment.paramIntervals,
        ),
        concurrency: assignment.concurrency,
        algorithm: assignment.algorithm,
        limit_seconds: assignment.limitSeconds,
        adaptive_max_trials: isAdaptiveAlgorithm(assignment.algorithm)
          ? adaptiveMaxTrialsFromTotal(assignment.trialCount)
          : DEFAULT_ADAPTIVE_MAX_TRIALS,
        candidate_index: assignment.candidate.index,
      });
      setDispatchByWorker((prev) => ({ ...prev, [workerId]: result }));
      updateAssignment(workerId, {
        dispatching: false,
        dispatchError: result.ok ? null : result.error ?? "Dispatch failed",
        dispatchedAt: result.ok ? new Date().toISOString() : assignment.dispatchedAt ?? null,
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

  function updateAssignmentBaseConf(workerId: string, nextBaseConf: Record<string, unknown>) {
    const assignment = assignments[workerId];
    if (!assignment) return;

    const nextIntervals = { ...assignment.paramIntervals };
    for (const param of assignment.selectedParams) {
      const options = nextBaseConf[`${assignment.tool}_options`];
      const baseValue =
        options && typeof options === "object" && !Array.isArray(options)
          ? String((options as Record<string, unknown>)[param] ?? "")
          : "";
      nextIntervals[param] = defaultParamInterval(assignment.tool, param, baseValue);
    }

    updateAssignment(workerId, {
      candidate: {
        ...assignment.candidate,
        base_conf: nextBaseConf,
      },
      paramIntervals: nextIntervals,
    });
  }

  function updateBaseParamValue(workerId: string, param: string, raw: string) {
    const assignment = assignments[workerId];
    if (!assignment) return;
    const value = parseToolOptionValue(assignment.tool, param, raw);
    const nextBaseConf = setToolOption(
      assignment.candidate.base_conf,
      assignment.tool,
      param,
      value,
    );
    updateAssignmentBaseConf(workerId, nextBaseConf);
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

  function applyBestConfToAssignment(workerId: string) {
    const assignment = assignments[workerId];
    const best = bestByWorker[workerId];
    if (!assignment || !best || best === "loading" || !best.ok || !hasConfContent(best.best_conf)) {
      return;
    }
    updateAssignmentBaseConf(workerId, {
      ...assignment.candidate.base_conf,
      ...best.best_conf,
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
    clearWorkerPanelEntry(workerId);
  }

  function handleWorkerUpdated(updated: WorkerRecord) {
    setWorkers((prev) => prev.map((w) => (w.id === updated.id ? updated : w)));
    setHealthByWorker((prev) => {
      const next = { ...prev };
      delete next[updated.id];
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
          {displayWorkers.map((worker) => {
            const dismissed = dismissedWorkers.has(worker.id);
            const autoAssignment = dismissed
              ? undefined
              : autoAssignmentsByWorker[worker.id] ?? autoPreviewByWorker[worker.id];
            const assignment = autoAssignment ?? (dismissed ? undefined : assignments[worker.id]);
            const autoManaged = Boolean(autoAssignment?.autoManaged);
            const health = healthByWorker[worker.id];
            const best = bestByWorker[worker.id];
            const dispatchResult = dispatchByWorker[worker.id];
            const refreshingBest = Boolean(refreshingBestByWorker[worker.id]);
            const score =
              assignment?.candidate.history_score ?? assignment?.candidate.rank_score;
            const compareBaseConf =
              assignment?.candidate.base_conf ?? baseConfByWorker[worker.id] ?? null;
            const bestOk = best && best !== "loading" && best.ok ? best : null;
            const runStartedAt = jobStartedAt(assignment, autoModeStatus, autoManaged);
            const runLimitSeconds = assignment?.limitSeconds ?? autoModeStatus?.config.limit_seconds;
            const displayStatus = resolveWorkerJobStatus(
              bestOk?.status ?? null,
              runStartedAt,
              runLimitSeconds,
              nowMs,
            );
            const isOptimizing = Boolean(
              bestOk && isJobActive(bestOk.status, runStartedAt, runLimitSeconds, nowMs),
            );
            const trialTotalCount = trialTotal(bestOk ?? undefined, dispatchResult);
            const trialLabel =
              trialTotalCount || (bestOk?.trials_evaluated ?? 0) > 0
                ? formatTrialProgress(
                    bestOk?.trials_evaluated ?? 0,
                    trialTotalCount,
                    displayStatus ?? (isOptimizing ? "optimizing" : null),
                  )
                : "";

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
                    {autoManaged && <span className="chip chip-ok">Auto</span>}
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
                      {isOptimizing && (
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
                        disabled={!worker.base_url || refreshingBest}
                      >
                        {refreshingBest ? "Refreshing…" : "Refresh"}
                      </button>
                    </div>
                  </div>

                  {best && best !== "loading" && !best.ok && (
                    <div className="worker-best-empty">{best.error ?? "Could not load best score"}</div>
                  )}

                  {bestOk && (
                    <div className="worker-best-body">
                      <div className="worker-best-score-row">
                        <span className="worker-best-score">{formatBestScore(bestOk.best_score)}</span>
                        {displayStatus && (
                          <span className={`badge ${bestStatusClass(displayStatus)}`}>
                            {displayStatus}
                          </span>
                        )}
                        {trialLabel && (
                          <span className="worker-best-trials worker-best-trials--inline">
                            {trialLabel}
                          </span>
                        )}
                        {(isOptimizing || displayStatus === "time limited") && (
                          <LimitCountdownBadge
                            startedAt={runStartedAt}
                            limitSeconds={runLimitSeconds ?? null}
                            active
                            className="worker-limit-countdown"
                          />
                        )}
                      </div>

                      {(bestOk.tool || bestOk.window) && (
                        <div className="worker-best-meta">
                          {bestOk.tool && <span className="chip chip-accent">{bestOk.tool}</span>}
                          {bestOk.window && <code className="worker-best-window">{bestOk.window}</code>}
                        </div>
                      )}

                      {hasConfContent(bestOk.best_conf) && (
                        <div className="worker-best-conf">
                          <ConfTooltip
                            conf={bestOk.best_conf}
                            label="Best conf"
                            layout="panel"
                            showActions
                            baseConf={compareBaseConf}
                            downloadFileName={`${worker.name.replace(/[^\w.-]+/g, "-")}-best-conf`}
                          />
                          {assignment && (
                            <button
                              type="button"
                              className="button ghost worker-best-use-conf"
                              onClick={() => applyBestConfToAssignment(worker.id)}
                            >
                              Use best as base
                            </button>
                          )}
                        </div>
                      )}

                      {bestOk.updated_at && (
                        <span className="worker-best-updated">
                          Updated {formatLocalDateTime(bestOk.updated_at)}
                        </span>
                      )}

                      {bestOk.message && !hasConfContent(bestOk.best_conf) && bestOk.best_score == null && (
                        <span className="worker-best-message">{bestOk.message}</span>
                      )}

                      {bestOk.trials.length > 0 && (
                        <div className="worker-trial-history">
                          <div className="worker-trial-history-head">
                            <span className="worker-assignment-label">Trial scores</span>
                            <span className="worker-trial-history-count">
                              {bestOk.trials.length} recorded
                            </span>
                          </div>
                          <div className="worker-trial-history-table-wrap">
                            <table className="worker-trial-history-table">
                              <thead>
                                <tr>
                                  <th>#</th>
                                  <th>Label</th>
                                  <th>Score</th>
                                  <th>Status</th>
                                </tr>
                              </thead>
                              <tbody>
                                {[...bestOk.trials].reverse().map((trial) => (
                                  <tr
                                    key={`${trial.index}-${trial.label}-${trial.recorded_at ?? ""}`}
                                    className={trial.is_best ? "worker-trial-row-best" : undefined}
                                  >
                                    <td>{trial.index}</td>
                                    <td>{trial.label}</td>
                                    <td>{formatTrialScore(trial.score)}</td>
                                    <td>
                                      {trial.is_best && <span className="chip chip-accent">best</span>}
                                      {!trial.success && (
                                        <span className="chip chip-warn" title={trial.error ?? undefined}>
                                          failed
                                        </span>
                                      )}
                                      {trial.cached && <span className="chip chip-muted">cache</span>}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {!best && (
                    <div className="worker-best-empty">
                      Live scores update while optimization runs. Use Refresh for an immediate
                      update.
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

                <WorkerEndpointsEditor worker={worker} onUpdated={handleWorkerUpdated} />

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
                        {autoManaged ? "Auto assignment" : `Candidate #${assignment.candidate.index + 1}`}
                        {score != null && (
                          <span className="worker-assignment-score">
                            {(score * 100).toFixed(1)}%
                          </span>
                        )}
                      </span>
                      {!autoManaged && (
                        <button
                          type="button"
                          className="button ghost worker-assignment-clear"
                          onClick={(e) => {
                            e.stopPropagation();
                            clearAssignment(worker.id);
                          }}
                        >
                          Clear
                        </button>
                      )}
                    </div>

                    <ConfParamPicker
                      baseConf={assignment.candidate.base_conf}
                      tool={assignment.tool}
                      selectedParams={assignment.selectedParams}
                      paramIntervals={assignment.paramIntervals}
                      onToggle={autoManaged ? () => {} : (param) => toggleParam(worker.id, param)}
                      onIntervalChange={
                        autoManaged
                          ? () => {}
                          : (param, patch) => updateParamInterval(worker.id, param, patch)
                      }
                      onBaseValueChange={
                        autoManaged
                          ? () => {}
                          : (param, raw) => updateBaseParamValue(worker.id, param, raw)
                      }
                    />

                    <ConfManualEditor
                      baseConf={assignment.candidate.base_conf}
                      tool={assignment.tool}
                      onChange={
                        autoManaged
                          ? () => {}
                          : (nextBaseConf) => updateAssignmentBaseConf(worker.id, nextBaseConf)
                      }
                    />

                    <div className="worker-assignment-options">
                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Toolkit</span>
                        <select
                          value={assignment.tool}
                          disabled={autoManaged}
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
                          disabled={autoManaged}
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

                      {isAdaptiveAlgorithm(assignment.algorithm) && (
                        <label className="worker-assignment-field">
                          <span className="worker-assignment-label">Trials</span>
                          <div className="worker-duration-input">
                            <input
                              type="number"
                              min={2}
                              max={1001}
                              step={1}
                              disabled={autoManaged}
                              value={assignment.trialCount}
                              onChange={(e) =>
                                updateAssignment(worker.id, {
                                  trialCount: clampTotalTrials(Number(e.target.value)),
                                })
                              }
                              aria-label="Total trials including base benchmark"
                            />
                          </div>
                        </label>
                      )}

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Time limit</span>
                        <div className="worker-duration-input">
                          <input
                            type="number"
                            min={1}
                            max={1440}
                            step={1}
                            disabled={autoManaged}
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
                        <span className="worker-assignment-label">CPUs / trial</span>
                        <div className="worker-duration-input">
                          <input
                            type="number"
                            min={1}
                            max={32}
                            step={1}
                            disabled={autoManaged}
                            value={assignment.trialThreads}
                            onChange={(e) =>
                              updateAssignment(worker.id, {
                                trialThreads: clampTrialThreads(Number(e.target.value)),
                              })
                            }
                            aria-label="CPU threads per trial"
                          />
                        </div>
                      </label>

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">RAM (GB) / trial</span>
                        <div className="worker-duration-input">
                          <input
                            type="number"
                            min={4}
                            max={128}
                            step={1}
                            disabled={autoManaged}
                            value={assignment.trialMemoryGb}
                            onChange={(e) =>
                              updateAssignment(worker.id, {
                                trialMemoryGb: clampTrialMemoryGb(Number(e.target.value)),
                              })
                            }
                            aria-label="Memory in GB per trial"
                          />
                          <span className="worker-duration-unit">GB</span>
                        </div>
                      </label>

                      <label className="worker-assignment-field">
                        <span className="worker-assignment-label">Concurrency</span>
                        <select
                          value={assignment.concurrency}
                          disabled={autoManaged}
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

                    {autoManaged ? (
                      <div className="worker-dispatch-success">
                        {assignment.dispatchError
                          ? `Auto dispatch failed: ${assignment.dispatchError}`
                          : autoAssignmentsByWorker[worker.id]
                            ? "Dispatched by auto mode — live scores update above."
                            : "Waiting for auto start — config shown from auto mode policy."}
                      </div>
                    ) : (
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
                    )}

                    {!autoManaged && assignment.dispatchError && (
                      <div className="alert error worker-dispatch-alert">{assignment.dispatchError}</div>
                    )}

                    {!autoManaged && dispatchResult?.ok && (
                      <div className="worker-dispatch-success">
                        Job accepted — use Refresh above for live best score and conf.
                      </div>
                    )}
                  </div>
                )}

                {!assignment && candidateContext && !autoModeEnabled && (
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
