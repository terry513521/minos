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
  buildWorkerAssignmentSummaries,
  buildDispatchBaseConf,
  isWorkerCandidateAssignmentLocked,
  WorkerAssignmentSummary,
  clampTrialMemoryGb,
  clampTrialThreads,
  CONCURRENCY_OPTIONS,
  MAX_TRIAL_THREADS,
  clampTotalTrials,
  clampDeltaRounds,
  createAssignment,
  defaultTrialMemoryGbForTool,
  assignmentWindowFromRegion,
  mergeAssignmentWithWorkerTunables,
  adaptiveMaxTrialsForDispatch,
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
  clampParamInterval,
  defaultParamDelta,
  defaultParamInterval,
  ParamInterval,
} from "../utils/paramBounds";
import { parseToolOptionValue, setToolOption } from "../utils/confEdit";
import { bestConfDownloadFileName } from "../utils/confDisplay";
import { WORKERS_CHANGED_EVENT, WORKERS_CHECK_ALL_HEALTH_EVENT, WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, WORKERS_CLEAR_ALL_EVENT, WORKERS_STOP_ALL_EVENT, WORKERS_START_ALL_EVENT, WORKERS_START_ALL_RESULT_EVENT } from "./AddWorkerModal";
import { ConfParamPicker } from "./ConfParamPicker";
import { ConfManualEditor } from "./ConfManualEditor";
import { ConfTooltip } from "./ConfTooltip";
import {
  clearWorkerPanelEntry,
  clearAllWorkerPanelData,
  clearDismissedWorkerAssignments,
  dismissAllWorkerAssignments,
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
import { syncManualParamDefaultsFromAutoConfig, ensureManualDefaultsHydrated } from "../utils/manualParamDefaults";
import { getWorkerTunableDefaults, saveWorkerTunableDefaults, ensureWorkerTunablesHydrated } from "../utils/workerTunableStorage";
import {
  assignmentPatchFromImportedTunable,
  ApplyConfImportResult,
  mergeImportedConfIntoCandidate,
} from "../utils/workerConfImport";
import { parseAutoModeTunableImport } from "../utils/autoModeTunableFile";
import { loadAutoModeState, saveAutoModeState } from "../utils/autoModeStorage";
import {
  isWorkerJobActiveStatus,
  isWorkerJobRunning,
  resolveWorkerJobLimitSeconds,
  resolveWorkerJobStartedAt,
  resolveWorkerJobStatus,
} from "../utils/workerJobStatus";
import {
  nextActiveWorkerOrder,
  shouldPollWorkerBest,
  sortWorkersForDisplay,
} from "../utils/workerDisplayOrder";
import { buildWorkerLiveStatuses, WorkerLiveStatus } from "../utils/workerLiveStatus";
import {
  formatBenchmarkWindowLabel,
  formatWorkerTaskParams,
  formatWorkerTaskSummary,
} from "../utils/workerTaskSummary";
import { formatWindowSpan } from "../utils/window";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";

/** Background poll for worker GET /best while optimization is running. */
const BEST_POLL_INTERVAL_MS = 1000;

interface WorkersPanelProps {
  candidateContext?: FindCandidatesResponse | null;
  /** Live Region input from the candidate finder panel. */
  finderRegion?: string;
  onWorkerAssignmentSummariesChange?: (summaries: WorkerAssignmentSummary[]) => void;
  onWorkerLiveStatusesChange?: (statuses: WorkerLiveStatus[]) => void;
  /** Parent section provides header and panel chrome. */
  sectionChild?: boolean;
  onAssignHandlerReady?: (
    handler: (workerId: string, candidateIndex: number) => boolean,
  ) => void;
  onApplyConfHandlerReady?: (
    handler: (text: string, candidateIndex: number) => Promise<ApplyConfImportResult>,
  ) => void;
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
    return `${done} / ${planned}`;
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
  assignment: WorkerAssignment | undefined,
  best: WorkerBestScoreResult | null | undefined,
  autoModeStatus: AutoModeStatus | null,
  autoManaged: boolean,
  nowMs = Date.now(),
): boolean {
  return isWorkerJobRunning(
    status,
    resolveWorkerJobStartedAt(assignment, autoManaged ? autoModeStatus : null, best ?? undefined),
    resolveWorkerJobLimitSeconds(assignment, autoManaged ? autoModeStatus : null, best ?? undefined),
    nowMs,
  );
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

export function WorkersPanel({
  candidateContext = null,
  finderRegion = "",
  onWorkerAssignmentSummariesChange,
  onWorkerLiveStatusesChange,
  sectionChild = false,
  onAssignHandlerReady,
  onApplyConfHandlerReady,
}: WorkersPanelProps) {
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
  >(() => {
    const stored = persisted?.bestByWorker ?? {};
    if (initialDismissed.size === 0) return stored;
    return Object.fromEntries(
      Object.entries(stored).filter(([workerId]) => !initialDismissed.has(workerId)),
    );
  });
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
    const merged: Record<string, WorkerAssignment> = {};

    for (const [workerId, assignment] of Object.entries(autoPreviewByWorker)) {
      if (!dismissedWorkers.has(workerId)) {
        merged[workerId] = assignment;
      }
    }
    if (autoModeStatus?.running) {
      for (const [workerId, assignment] of Object.entries(autoAssignmentsByWorker)) {
        if (!dismissedWorkers.has(workerId)) {
          merged[workerId] = assignment;
        }
      }
    }
    for (const [workerId, assignment] of Object.entries(assignments)) {
      if (!dismissedWorkers.has(workerId)) {
        merged[workerId] = assignment;
      }
    }
    return merged;
  }, [assignments, autoAssignmentsByWorker, autoPreviewByWorker, autoModeStatus?.running, dismissedWorkers]);

  const bestByWorkerRef = useRef(bestByWorker);
  bestByWorkerRef.current = bestByWorker;
  const assignmentsRef = useRef(assignments);
  assignmentsRef.current = assignments;
  const effectiveAssignmentsRef = useRef(effectiveAssignmentsByWorker);
  effectiveAssignmentsRef.current = effectiveAssignmentsByWorker;

  const anyActiveJob = useMemo(() => {
    for (const worker of workers) {
      const best = bestByWorker[worker.id];
      if (
        best &&
        best !== "loading" &&
        best.ok &&
        isWorkerJobActiveStatus(best.status)
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

  useEffect(() => {
    void ensureWorkerTunablesHydrated();
  }, []);

  useEffect(() => {
    if (workers.length === 0) return;
    let cancelled = false;
    void ensureWorkerTunablesHydrated().then(() => {
      if (cancelled) return;
      setAssignments((prev) => {
        let changed = false;
        const next: Record<string, WorkerAssignment> = { ...prev };
        for (const worker of workers) {
          const assignment = prev[worker.id];
          if (!assignment || assignment.autoManaged) continue;
          if (!getWorkerTunableDefaults(worker, assignment.tool)) continue;
          const merged = mergeAssignmentWithWorkerTunables(worker, assignment);
          next[worker.id] = merged;
          changed = true;
        }
        return changed ? next : prev;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [workers]);

  useEffect(() => {
    const targetWindow = assignmentWindowFromRegion(finderRegion, candidateContext?.window);
    if (!targetWindow || !candidateContext) return;

    setAssignments((prev) => {
      let changed = false;
      const next: Record<string, WorkerAssignment> = { ...prev };
      for (const [workerId, assignment] of Object.entries(prev)) {
        if (assignment.autoManaged) continue;
        const inPool = candidateContext.candidates.some(
          (candidate) => candidate.index === assignment.candidate.index,
        );
        if (inPool && assignment.window !== targetWindow) {
          next[workerId] = { ...assignment, window: targetWindow };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [candidateContext, finderRegion]);

  useEffect(() => {
    if (initialAutoStatus?.config?.params?.length) {
      syncManualParamDefaultsFromAutoConfig(initialAutoStatus.config);
    } else {
      ensureManualDefaultsHydrated();
    }
  }, []);

  const refreshAutoMode = useCallback(() => {
    ensureManualDefaultsHydrated();
    api
      .getAutoMode()
      .then((status) => {
        saveAutoModeState(status);
        syncManualParamDefaultsFromAutoConfig(status.config, {
          syncPerWorkerTunables: status.enabled,
        });
        setAutoModeEnabled(status.enabled);
        setAutoModeStatus(status);
        setAutoAssignmentsByWorker(autoAssignmentsForStatus(status));
        const manualFromAuto = manualAssignmentsFromEndedAuto(status);
        if (Object.keys(manualFromAuto).length > 0) {
          const dismissed = dismissedWorkersRef.current;
          setAssignments((prev) => {
            const next = { ...prev };
            let changed = false;
            for (const [workerId, assignment] of Object.entries(manualFromAuto)) {
              if (!dismissed.has(workerId) && !prev[workerId]) {
                next[workerId] = assignment;
                changed = true;
              }
            }
            return changed ? next : prev;
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

  const autoSessionStartedAtRef = useRef<string | null>(null);

  useEffect(() => {
    if (!autoModeStatus?.running) {
      autoSessionStartedAtRef.current = null;
      return;
    }
    const startedAt = autoModeStatus.started_at ?? null;
    if (!startedAt || autoSessionStartedAtRef.current === startedAt) {
      return;
    }
    autoSessionStartedAtRef.current = startedAt;
    setDismissedWorkers(new Set());
    clearDismissedWorkerAssignments();
  }, [autoModeStatus?.running, autoModeStatus?.started_at]);

  useEffect(() => {
    const dismissed = dismissedWorkersRef.current;
    saveWorkerPanelState({
      assignments: Object.fromEntries(
        Object.entries(assignments).filter(([workerId]) => !dismissed.has(workerId)),
      ),
      baseConfByWorker: Object.fromEntries(
        Object.entries(baseConfByWorker).filter(([workerId]) => !dismissed.has(workerId)),
      ),
      dispatchByWorker: Object.fromEntries(
        Object.entries(dispatchByWorker).filter(([workerId]) => !dismissed.has(workerId)),
      ),
      bestByWorker: Object.fromEntries(
        Object.entries(withoutLoadingBest(bestByWorker)).filter(
          ([workerId]) => !dismissed.has(workerId),
        ),
      ),
      healthByWorker: withoutLoadingHealth(healthByWorker),
    });
  }, [assignments, baseConfByWorker, dispatchByWorker, bestByWorker, healthByWorker, dismissedWorkers]);

  const workerOptimizationSnapshot = useCallback(
    (workerId: string) => {
      const best = bestByWorker[workerId];
      return best && best !== "loading" ? best : null;
    },
    [bestByWorker],
  );

  const isWorkerAssignmentLocked = useCallback(
    (workerId: string) =>
      isWorkerCandidateAssignmentLocked(
        effectiveAssignmentsByWorker[workerId],
        workerOptimizationSnapshot(workerId),
        autoModeStatus,
        nowMs,
      ),
    [effectiveAssignmentsByWorker, workerOptimizationSnapshot, autoModeStatus, nowMs],
  );

  useEffect(() => {
    if (!onWorkerAssignmentSummariesChange) return;
    onWorkerAssignmentSummariesChange(
      buildWorkerAssignmentSummaries(
        workers,
        effectiveAssignmentsByWorker,
        bestByWorker,
        autoModeStatus,
        nowMs,
      ),
    );
  }, [
    workers,
    effectiveAssignmentsByWorker,
    bestByWorker,
    autoModeStatus,
    nowMs,
    onWorkerAssignmentSummariesChange,
  ]);

  useEffect(() => {
    if (!onWorkerLiveStatusesChange) return;
    onWorkerLiveStatusesChange(
      buildWorkerLiveStatuses(
        workers,
        bestByWorker,
        healthByWorker,
        effectiveAssignmentsByWorker,
        dispatchByWorker,
        autoModeStatus,
        nowMs,
      ),
    );
  }, [
    workers,
    bestByWorker,
    healthByWorker,
    effectiveAssignmentsByWorker,
    dispatchByWorker,
    autoModeStatus,
    nowMs,
    onWorkerLiveStatusesChange,
  ]);

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
      const next = { ...current, ...patch };
      const worker = workers.find((item) => item.id === workerId);
      if (worker && !next.autoManaged && next.selectedParams.length > 0) {
        saveWorkerTunableDefaults(worker, next);
      }
      return { ...prev, [workerId]: next };
    });
  }

  async function clearAssignment(workerId: string) {
    const best = bestByWorkerRef.current[workerId];
    const jobActive =
      best &&
      best !== "loading" &&
      best.ok &&
      isWorkerJobActiveStatus(best.status);
    if (jobActive) {
      try {
        await api.stopWorkerOptimization(workerId);
      } catch {
        // Still clear dashboard state even if stop fails.
      }
    }

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
    setBestByWorker((prev) => {
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    setRefreshingBestByWorker((prev) => {
      if (!prev[workerId]) return prev;
      const next = { ...prev };
      delete next[workerId];
      return next;
    });
    clearWorkerPanelEntry(workerId);
  }

  function clearAllWorkerData() {
    const workerIds = workers.map((worker) => worker.id);
    if (workerIds.length > 0) {
      dismissAllWorkerAssignments(workerIds);
    }
    setDismissedWorkers(new Set(workerIds));
    setAssignments({});
    setDispatchByWorker({});
    setBaseConfByWorker({});
    setAutoAssignmentsByWorker({});
    setBestByWorker({});
    setHealthByWorker({});
    clearAllWorkerPanelData();
  }

  const clearAllWorkerDataRef = useRef(clearAllWorkerData);
  clearAllWorkerDataRef.current = clearAllWorkerData;

  const assignCandidateToWorker = useCallback(
    (workerId: string, candidateIndex: number): boolean => {
      if (!candidateContext) return false;
      if (isWorkerAssignmentLocked(workerId)) return false;

      const candidate = candidateContext.candidates.find((c) => c.index === candidateIndex);
      if (!candidate) return false;

      const worker = workers.find((item) => item.id === workerId);

      void ensureWorkerTunablesHydrated().then(() => {
        restoreWorkerAssignment(workerId);
        setDismissedWorkers((prev) => {
          if (!prev.has(workerId)) return prev;
          const next = new Set(prev);
          next.delete(workerId);
          return next;
        });

        const assignment = createAssignment(candidate, candidateContext, worker, finderRegion);
        setAssignments((prev) => ({
          ...prev,
          [workerId]: assignment,
        }));
        if (worker) {
          saveWorkerTunableDefaults(worker, assignment);
        }
        setDispatchByWorker((prev) => {
          const next = { ...prev };
          delete next[workerId];
          return next;
        });
      });

      return true;
    },
    [candidateContext, finderRegion, workers, isWorkerAssignmentLocked],
  );

  const applyConfImportToAllWorkers = useCallback(
    async (text: string, candidateIndex: number): Promise<ApplyConfImportResult> => {
      await ensureWorkerTunablesHydrated();
      if (!candidateContext) {
        return { ok: false, message: "Find candidates before importing a conf file.", applied: 0, skipped: 0 };
      }
      if (autoModeEnabled) {
        return { ok: false, message: "Conf import is not available during auto mode.", applied: 0, skipped: 0 };
      }

      const candidate = candidateContext.candidates.find((item) => item.index === candidateIndex);
      if (!candidate) {
        return { ok: false, message: "Selected candidate not found.", applied: 0, skipped: 0 };
      }

      const toolRaw = (candidateContext.tool?.toLowerCase() ?? "gatk") as ToolkitOption;
      const tool: ToolkitOption = TOOLKIT_OPTIONS.includes(toolRaw) ? toolRaw : "gatk";
      const parsed = parseAutoModeTunableImport(text, tool, candidate.base_conf);
      if (!parsed.ok) {
        return { ok: false, message: parsed.error, applied: 0, skipped: 0 };
      }

      const nextAssignments: Record<string, WorkerAssignment> = {};
      const restoredDismissed: string[] = [];
      const clearedDispatch: string[] = [];
      let applied = 0;
      let skipped = 0;

      for (const worker of workers) {
        const effective = effectiveAssignmentsRef.current[worker.id];
        if (effective?.autoManaged) {
          skipped += 1;
          continue;
        }
        if (isWorkerAssignmentLocked(worker.id)) {
          skipped += 1;
          continue;
        }

        restoreWorkerAssignment(worker.id);
        restoredDismissed.push(worker.id);

        let assignment = createAssignment(candidate, candidateContext, worker, finderRegion);
        if (parsed.result.kind === "tunable") {
          assignment = {
            ...assignment,
            ...assignmentPatchFromImportedTunable(
              worker.name,
              tool,
              parsed.result.data,
              assignment,
            ),
          };
        } else {
          assignment = {
            ...assignment,
            candidate: mergeImportedConfIntoCandidate(
              assignment.candidate,
              parsed.result.baseConf,
            ),
          };
        }

        nextAssignments[worker.id] = assignment;
        saveWorkerTunableDefaults(worker, assignment);
        clearedDispatch.push(worker.id);
        applied += 1;
      }

      if (applied === 0) {
        return {
          ok: false,
          message:
            skipped > 0
              ? "No workers updated — all are locked or managed by auto mode."
              : "No workers registered.",
          applied: 0,
          skipped,
        };
      }

      if (restoredDismissed.length > 0) {
        setDismissedWorkers((prev) => {
          const next = new Set(prev);
          for (const workerId of restoredDismissed) {
            next.delete(workerId);
          }
          return next;
        });
      }

      setAssignments((prev) => ({ ...prev, ...nextAssignments }));
      setDispatchByWorker((prev) => {
        const next = { ...prev };
        for (const workerId of clearedDispatch) {
          delete next[workerId];
        }
        return next;
      });

      const skippedNote = skipped > 0 ? ` (${skipped} skipped: auto or running)` : "";
      return {
        ok: true,
        message: `Applied conf to ${applied} worker${applied === 1 ? "" : "s"}${skippedNote}.`,
        applied,
        skipped,
      };
    },
    [candidateContext, finderRegion, autoModeEnabled, workers, isWorkerAssignmentLocked],
  );

  useEffect(() => {
    if (!onAssignHandlerReady) return;
    onAssignHandlerReady(assignCandidateToWorker);
  }, [assignCandidateToWorker, onAssignHandlerReady]);

  useEffect(() => {
    if (!onApplyConfHandlerReady) return;
    onApplyConfHandlerReady(applyConfImportToAllWorkers);
  }, [applyConfImportToAllWorkers, onApplyConfHandlerReady]);

  function handleDragOver(e: DragEvent, workerId: string) {
    if (!candidateContext) return;
    if (isWorkerAssignmentLocked(workerId)) return;
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
    if (isWorkerAssignmentLocked(workerId)) return;

    const raw = e.dataTransfer.getData(CANDIDATE_DRAG_MIME);
    if (!raw) return;

    let payload: CandidateDragPayload;
    try {
      payload = JSON.parse(raw) as CandidateDragPayload;
    } catch {
      return;
    }

    assignCandidateToWorker(workerId, payload.index);
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
      const dismissed = dismissedWorkersRef.current;
      const hasAssignment = Boolean(effectiveAssignmentsRef.current[workerId]);
      if (dismissed.has(workerId) && !hasAssignment) {
        setBestByWorker((prev) => {
          const next = { ...prev };
          delete next[workerId];
          return next;
        });
        return;
      }
      setBestByWorker((prev) => ({ ...prev, [workerId]: result }));
      if (
        result.ok &&
        result.status &&
        !isWorkerJobRunning(result.status)
      ) {
        setAssignments((prev) => {
          const current = prev[workerId];
          if (!current || current.dispatching) return prev;
          if (!current.dispatchedAt && !current.dispatchError) return prev;
          return {
            ...prev,
            [workerId]: {
              ...current,
              dispatchedAt: null,
              dispatchError: null,
            },
          };
        });
      }
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
            algorithm: null,
            concurrency: null,
            limit_seconds: null,
            adaptive_max_trials: null,
            params: [],
            trial_threads: null,
            trial_memory_gb: null,
            benchmark_window: null,
            best_score: null,
            best_conf: {},
            trials_evaluated: 0,
            search_space_size: 0,
            started_at: null,
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
          if (best.ok && best.status && !isWorkerJobActiveStatus(best.status)) {
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
    const dismissed = dismissedWorkersRef.current;
    for (const worker of workers) {
      if (!worker.base_url || dismissed.has(worker.id)) continue;
      void pollWorkerBest(worker.id, true);
    }
  }, [workers, pollWorkerBest]);

  useEffect(() => {
    if (workers.length === 0) return;

    const pollable = workers.filter((worker) => worker.base_url);
    if (pollable.length === 0) return;

    const tick = () => {
      const best = bestByWorkerRef.current;
      const assignmentsByWorker = effectiveAssignmentsRef.current;
      const dismissed = dismissedWorkersRef.current;
      const tickNow = Date.now();
      for (const worker of pollable) {
        if (dismissed.has(worker.id)) {
          continue;
        }
        const assignment = assignmentsByWorker[worker.id];
        if (
          !shouldPollWorkerBest(
            best[worker.id],
            assignment,
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

  useEffect(() => {
    function refreshAllBest() {
      const dismissed = dismissedWorkersRef.current;
      for (const worker of workers) {
        if (!worker.base_url || dismissed.has(worker.id)) continue;
        void pollWorkerBest(worker.id, true);
      }
    }
    window.addEventListener(WORKERS_CHANGED_EVENT, refreshAllBest);
    return () => window.removeEventListener(WORKERS_CHANGED_EVENT, refreshAllBest);
  }, [workers, pollWorkerBest]);

  useEffect(() => {
    async function waitForAllWorkersIdle() {
      const pollable = workers.filter((worker) => worker.base_url);
      if (pollable.length === 0) return;

      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        let anyActive = false;
        await Promise.all(
          pollable.map(async (worker) => {
            try {
              const best = await api.fetchWorkerBest(worker.id);
              setBestByWorker((prev) => ({ ...prev, [worker.id]: best }));
              if (best.ok && best.status && isWorkerJobActiveStatus(best.status)) {
                anyActive = true;
              }
            } catch {
              // Keep polling until timeout.
            }
          }),
        );
        if (!anyActive) break;
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
    }

    function onStopAll() {
      void (async () => {
        await waitForAllWorkersIdle();
        clearAllWorkerDataRef.current();
      })();
    }
    window.addEventListener(WORKERS_STOP_ALL_EVENT, onStopAll);

    function onClearAll() {
      clearAllWorkerDataRef.current();
    }
    window.addEventListener(WORKERS_CLEAR_ALL_EVENT, onClearAll);

    async function onStartAll() {
      const results = { started: 0, failed: 0, skipped: 0 };
      for (const worker of workers) {
        const assignment = assignmentsRef.current[worker.id];
        if (!assignment || assignment.autoManaged) {
          results.skipped += 1;
          continue;
        }
        if (!worker.base_url || assignment.selectedParams.length === 0) {
          results.skipped += 1;
          continue;
        }
        if (assignment.dispatching) {
          results.skipped += 1;
          continue;
        }
        const best = bestByWorkerRef.current[worker.id];
        if (
          best &&
          best !== "loading" &&
          best.ok &&
          best.status &&
          isWorkerJobActiveStatus(best.status)
        ) {
          results.skipped += 1;
          continue;
        }
        const ok = await handleDispatchRef.current(worker.id);
        if (ok) results.started += 1;
        else results.failed += 1;
      }
      window.dispatchEvent(
        new CustomEvent(WORKERS_START_ALL_RESULT_EVENT, { detail: results }),
      );
    }

    function onStartAllEvent() {
      void onStartAll();
    }
    window.addEventListener(WORKERS_START_ALL_EVENT, onStartAllEvent);

    async function onCheckAllHealth() {
      const workerList = workers;
      if (workerList.length === 0) {
        window.dispatchEvent(
          new CustomEvent(WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, {
            detail: { total: 0, ok: 0, failed: 0 },
          }),
        );
        return;
      }

      setHealthByWorker((prev) => ({
        ...prev,
        ...Object.fromEntries(workerList.map((worker) => [worker.id, "loading" as const])),
      }));

      let ok = 0;
      let failed = 0;
      await Promise.all(
        workerList.map(async (worker) => {
          try {
            const result = await api.checkWorkerHealth(worker.id);
            setHealthByWorker((prev) => ({ ...prev, [worker.id]: result }));
            if (result.ok) ok += 1;
            else failed += 1;
          } catch (err) {
            failed += 1;
            setHealthByWorker((prev) => ({
              ...prev,
              [worker.id]: {
                worker_id: worker.id,
                ok: false,
                status_code: null,
                health: null,
                error: err instanceof Error ? err.message : "Health check failed",
              },
            }));
          }
        }),
      );

      window.dispatchEvent(
        new CustomEvent(WORKERS_CHECK_ALL_HEALTH_RESULT_EVENT, {
          detail: { total: workerList.length, ok, failed },
        }),
      );
    }

    function onCheckAllHealthEvent() {
      void onCheckAllHealth();
    }
    window.addEventListener(WORKERS_CHECK_ALL_HEALTH_EVENT, onCheckAllHealthEvent);

    return () => {
      window.removeEventListener(WORKERS_STOP_ALL_EVENT, onStopAll);
      window.removeEventListener(WORKERS_CLEAR_ALL_EVENT, onClearAll);
      window.removeEventListener(WORKERS_START_ALL_EVENT, onStartAllEvent);
      window.removeEventListener(WORKERS_CHECK_ALL_HEALTH_EVENT, onCheckAllHealthEvent);
    };
  }, [workers]);

  async function handleDispatch(workerId: string): Promise<boolean> {
    const assignment = assignments[workerId];
    if (!assignment || assignment.selectedParams.length === 0) return false;

    updateAssignment(workerId, { dispatching: true, dispatchError: null });
    try {
      const result = await api.dispatchToWorker(workerId, {
        window: assignment.window,
        tool: assignment.tool,
        base_conf: buildDispatchBaseConf(
          assignment.candidate.base_conf,
          assignment.trialThreads,
          assignment.trialMemoryGb,
          assignment.tool,
        ),
        params: assignment.selectedParams,
        param_intervals: buildDispatchParamIntervals(
          assignment.tool,
          assignment.selectedParams,
          assignment.paramIntervals,
          assignment.algorithm,
        ),
        concurrency: assignment.concurrency,
        algorithm: assignment.algorithm,
        limit_seconds: assignment.limitSeconds,
        adaptive_max_trials: adaptiveMaxTrialsForDispatch(
          assignment.trialCount,
          assignment.includeBaseBenchmark,
          assignment.algorithm,
        ),
        include_base_benchmark: assignment.includeBaseBenchmark,
        ...(assignment.algorithm === "delta"
          ? { delta_rounds: assignment.deltaRounds }
          : {}),
        candidate_index: assignment.candidate.index,
      });
      setDispatchByWorker((prev) => ({ ...prev, [workerId]: result }));
      updateAssignment(workerId, {
        dispatching: false,
        dispatchError: result.ok ? null : result.error ?? "Dispatch failed",
        dispatchedAt: result.ok ? new Date().toISOString() : assignment.dispatchedAt ?? null,
      });
      if (result.ok) {
        const worker = workers.find((item) => item.id === workerId);
        if (worker) {
          saveWorkerTunableDefaults(worker, assignment);
        }
        setBaseConfByWorker((prev) => ({
          ...prev,
          [workerId]: assignment.candidate.base_conf,
        }));
        setBestByWorker((prev) => {
          const current = prev[workerId];
          if (!current || current === "loading") return prev;
          return {
            ...prev,
            [workerId]: { ...current, ok: true, status: "optimizing" },
          };
        });
        void pollWorkerBest(workerId, true);
      }
      return result.ok;
    } catch (err) {
      updateAssignment(workerId, {
        dispatching: false,
        dispatchError: err instanceof Error ? err.message : "Dispatch failed",
      });
      return false;
    }
  }

  const handleDispatchRef = useRef(handleDispatch);
  handleDispatchRef.current = handleDispatch;

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

    const worker = workers.find((item) => item.id === workerId);
    const saved = worker
      ? getWorkerTunableDefaults(worker, assignment.tool)?.paramIntervals[param]
      : undefined;
    const useDelta = assignment.algorithm === "delta";
    const interval = saved
      ? clampParamInterval(assignment.tool, param, saved)
      : useDelta
        ? {
            ...defaultParamInterval(assignment.tool, param, baseValue),
            delta: defaultParamDelta(assignment.tool, param, baseValue),
          }
        : defaultParamInterval(assignment.tool, param, baseValue);

    updateAssignment(workerId, {
      selectedParams: [...assignment.selectedParams, param],
      paramIntervals: {
        ...assignment.paramIntervals,
        [param]: interval,
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
    <div className={`workers-panel${sectionChild ? " workers-panel--section-child" : ""}`}>
      <div className={`workers-panel-head${sectionChild ? " workers-panel-head--toolbar" : ""}`}>
        {!sectionChild && <h3 className="workers-panel-title">Workers</h3>}
        <button type="button" className="button ghost workers-refresh" onClick={refresh} disabled={loading}>
          Refresh
        </button>
      </div>

      {!sectionChild && candidateContext && (
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
            const runStartedAt = resolveWorkerJobStartedAt(
              assignment,
              autoManaged ? autoModeStatus : null,
              bestOk ?? undefined,
            );
            const runLimitSeconds = resolveWorkerJobLimitSeconds(
              assignment,
              autoManaged ? autoModeStatus : null,
              bestOk ?? undefined,
            );
            const displayStatus = resolveWorkerJobStatus(
              bestOk?.status ?? null,
              runStartedAt,
              runLimitSeconds,
              nowMs,
            );
            const isOptimizing = Boolean(
              bestOk &&
                isJobActive(
                  bestOk.status,
                  assignment,
                  bestOk,
                  autoModeStatus,
                  autoManaged,
                  nowMs,
                ),
            );
            const reassignmentLocked = isWorkerAssignmentLocked(worker.id);
            const trialTotalCount = trialTotal(bestOk ?? undefined, dispatchResult);
            const trialLabel =
              trialTotalCount || (bestOk?.trials_evaluated ?? 0) > 0
                ? formatTrialProgress(
                    bestOk?.trials_evaluated ?? 0,
                    trialTotalCount,
                    displayStatus ?? (isOptimizing ? "optimizing" : null),
                  )
                : "";
            const taskSummary = formatWorkerTaskSummary(bestOk ?? undefined, assignment ?? null);
            const taskParams = formatWorkerTaskParams(bestOk ?? undefined, assignment ?? null);
            const workerBenchmarkLabel = formatBenchmarkWindowLabel(
              bestOk ?? undefined,
              assignment?.window ?? null,
            );
            const assignedWindowSpan = formatWindowSpan(assignment?.window);
            const showWorkerBest = Boolean(assignment);

            return (
              <article
                key={worker.id}
                className={`worker-card${dragOverWorkerId === worker.id ? " worker-card-drop-target" : ""}${assignment ? " worker-card-assigned worker-card-has-assignment" : ""}${reassignmentLocked ? " worker-card-reassignment-locked" : ""}`}
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

                {assignment && (
                  <div className="worker-base-region-row">
                    <span className="worker-assignment-label">Base conf region</span>
                    <code className="worker-base-region">{assignment.window}</code>
                    {assignedWindowSpan && (
                      <span className="worker-base-region-span">{assignedWindowSpan}</span>
                    )}
                  </div>
                )}

                {assignment && !bestOk && (() => {
                  const pendingTask = formatWorkerTaskSummary(undefined, assignment);
                  const pendingParams = formatWorkerTaskParams(undefined, assignment);
                  if (!pendingTask && !pendingParams) return null;
                  return (
                    <div className="worker-task-block">
                      {pendingTask && <code className="worker-task-summary">{pendingTask}</code>}
                      {pendingParams && <div className="worker-task-params">{pendingParams}</div>}
                    </div>
                  );
                })()}

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
                  {showWorkerBest ? (
                  <>
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

                      {(bestOk.tool || bestOk.window || taskSummary) && (
                        <div className="worker-best-meta">
                          {taskSummary ? (
                            <code className="worker-task-summary">{taskSummary}</code>
                          ) : (
                            <>
                              {bestOk.tool && <span className="chip chip-accent">{bestOk.tool}</span>}
                              {bestOk.window && <code className="worker-best-window">{bestOk.window}</code>}
                            </>
                          )}
                        </div>
                      )}

                      {taskParams && (
                        <div className="worker-task-params">{taskParams}</div>
                      )}

                      {hasConfContent(bestOk.best_conf) && (
                        <div className="worker-best-conf">
                          <ConfTooltip
                            conf={bestOk.best_conf}
                            label="Best conf"
                            layout="panel"
                            showActions
                            viewOnly
                            baseConf={compareBaseConf}
                            downloadFileName={bestConfDownloadFileName(
                              assignment?.window ?? bestOk.window,
                              bestOk.best_score,
                            )}
                          />
                        </div>
                      )}

                      {bestOk.started_at && (
                        <span className="worker-best-updated">
                          Started {formatLocalDateTime(bestOk.started_at)}
                        </span>
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
                  </>
                  ) : null}
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
                      <div className="worker-assignment-head-main">
                        <span className="worker-assignment-title">
                          {autoManaged ? "Auto assignment" : `Candidate #${assignment.candidate.index + 1}`}
                          {score != null && (
                            <span className="worker-assignment-score">
                              {(score * 100).toFixed(1)}%
                            </span>
                          )}
                        </span>
                        {(isOptimizing || bestOk?.benchmark_window) && workerBenchmarkLabel && (
                          <code className="worker-assignment-window worker-assignment-window--benchmark">
                            benchmark: {workerBenchmarkLabel}
                          </code>
                        )}
                      </div>
                      <button
                          type="button"
                          className="button ghost worker-assignment-clear"
                          onClick={(e) => {
                            e.stopPropagation();
                            void clearAssignment(worker.id);
                          }}
                        >
                          Clear
                        </button>
                    </div>

                    <ConfParamPicker
                      baseConf={assignment.candidate.base_conf}
                      tool={assignment.tool}
                      algorithm={assignment.algorithm}
                      selectedParams={assignment.selectedParams}
                      paramIntervals={assignment.paramIntervals}
                      readOnly={reassignmentLocked || autoManaged}
                      onToggle={
                        autoManaged || reassignmentLocked
                          ? () => {}
                          : (param) => toggleParam(worker.id, param)
                      }
                      onIntervalChange={
                        autoManaged || reassignmentLocked
                          ? () => {}
                          : (param, patch) => updateParamInterval(worker.id, param, patch)
                      }
                      onBaseValueChange={
                        autoManaged || reassignmentLocked
                          ? undefined
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
                          onChange={(e) => {
                            const tool = e.target.value as ToolkitOption;
                            updateAssignment(
                              worker.id,
                              mergeAssignmentWithWorkerTunables(worker, {
                                ...assignment,
                                ...assignmentParamsForTool(assignment, tool, worker),
                                tool,
                                trialMemoryGb: defaultTrialMemoryGbForTool(tool),
                              }),
                            );
                          }}
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
                          <span className="worker-assignment-label">
                            {assignment.includeBaseBenchmark ? "Trials (1 base + search)" : "Search trials"}
                          </span>
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
                              aria-label={
                                assignment.includeBaseBenchmark
                                  ? "Total trials including base benchmark"
                                  : "Search trials without base benchmark"
                              }
                            />
                          </div>
                        </label>
                      )}

                      {assignment.algorithm === "delta" && (
                        <label className="worker-assignment-field">
                          <span className="worker-assignment-label">Delta rounds (n)</span>
                          <div className="worker-duration-input">
                            <input
                              type="number"
                              min={1}
                              max={1000}
                              step={1}
                              disabled={autoManaged}
                              value={assignment.deltaRounds}
                              onChange={(e) =>
                                updateAssignment(worker.id, {
                                  deltaRounds: clampDeltaRounds(Number(e.target.value)),
                                })
                              }
                              aria-label="Delta refinement rounds around current best"
                            />
                          </div>
                        </label>
                      )}

                      {!autoManaged && (
                        <label className="worker-assignment-field worker-assignment-field--checkbox">
                          <input
                            type="checkbox"
                            checked={assignment.includeBaseBenchmark}
                            onChange={(e) =>
                              updateAssignment(worker.id, {
                                includeBaseBenchmark: e.target.checked,
                              })
                            }
                          />
                          <span className="worker-assignment-label">Include base conf benchmark</span>
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
                            max={MAX_TRIAL_THREADS}
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
                          ? autoModeStatus?.running
                            ? `Auto dispatch pending: ${assignment.dispatchError} (retrying)`
                            : `Auto dispatch failed: ${assignment.dispatchError}`
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

                {!assignment && candidateContext && !reassignmentLocked && (
                  <p className="worker-drop-placeholder">Drop candidate here</p>
                )}
                {reassignmentLocked && (
                  <p className="worker-drop-placeholder worker-drop-placeholder--locked">
                    Optimization running — cannot assign candidates
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
