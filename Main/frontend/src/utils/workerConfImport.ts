import { CandidatePreview } from "../api/client";
import {
  AlgorithmOption,
  ALGORITHM_OPTIONS,
  clampConcurrency,
  clampTotalTrials,
  clampTrialMemoryGb,
  clampTrialThreads,
  DEFAULT_ALGORITHM,
  DEFAULT_LIMIT_SECONDS,
  DEFAULT_TOTAL_TRIALS,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
  ToolkitOption,
  WorkerAssignment,
} from "../types/workerAssignment";
import { AutoModeTunableImportData } from "./autoModeTunableFile";
import { workerSettingForName } from "./autoModeSync";

function importedValueForWorker<T>(
  map: Record<string, T> | undefined,
  workerName: string,
  fallback: T,
): T {
  if (!map || Object.keys(map).length === 0) return fallback;
  const named = workerSettingForName(map, workerName);
  if (named !== undefined) return named;
  const values = Object.values(map);
  if (values.length === 1) return values[0];
  return fallback;
}

function normalizeAlgorithm(raw: string | undefined, fallback: AlgorithmOption): AlgorithmOption {
  if (raw && ALGORITHM_OPTIONS.includes(raw as AlgorithmOption)) {
    return raw as AlgorithmOption;
  }
  return fallback;
}

export interface ApplyConfImportResult {
  ok: boolean;
  message: string;
  applied: number;
  skipped: number;
}

export function assignmentPatchFromImportedTunable(
  workerName: string,
  tool: ToolkitOption,
  data: AutoModeTunableImportData,
  assignment: WorkerAssignment,
): Partial<WorkerAssignment> {
  const baseConf = data.baseConf
    ? structuredClone(data.baseConf)
    : assignment.candidate.base_conf;

  const patch: Partial<WorkerAssignment> = {
    tool,
    selectedParams: [...data.params],
    paramIntervals: { ...data.paramIntervals },
    candidate: {
      ...assignment.candidate,
      base_conf: baseConf,
    },
    algorithm: normalizeAlgorithm(
      importedValueForWorker(data.workerAlgorithms, workerName, undefined),
      assignment.algorithm ?? DEFAULT_ALGORITHM,
    ),
    trialThreads: clampTrialThreads(
      importedValueForWorker(
        data.workerTrialThreads,
        workerName,
        assignment.trialThreads ?? DEFAULT_TRIAL_THREADS,
      ),
    ),
    trialMemoryGb: clampTrialMemoryGb(
      importedValueForWorker(
        data.workerTrialMemoryGb,
        workerName,
        assignment.trialMemoryGb ?? DEFAULT_TRIAL_MEMORY_GB,
      ),
    ),
    concurrency: clampConcurrency(
      importedValueForWorker(
        data.workerConcurrency,
        workerName,
        assignment.concurrency ?? 1,
      ),
    ),
    limitSeconds: Math.max(
      60,
      Math.round(
        importedValueForWorker(
          data.workerLimitSeconds,
          workerName,
          assignment.limitSeconds ?? DEFAULT_LIMIT_SECONDS,
        ),
      ),
    ),
    trialCount: clampTotalTrials(
      importedValueForWorker(
        data.workerTrialCounts,
        workerName,
        assignment.trialCount ?? DEFAULT_TOTAL_TRIALS,
      ),
    ),
  };

  return patch;
}

export function mergeImportedConfIntoCandidate(
  candidate: CandidatePreview,
  baseConf: Record<string, unknown>,
): CandidatePreview {
  return {
    ...candidate,
    base_conf: structuredClone(baseConf),
  };
}
