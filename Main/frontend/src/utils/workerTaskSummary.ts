import type { WorkerAssignment } from "../types/workerAssignment";
import type { WorkerBestScoreResult } from "../api/client";

export function formatWorkerTaskSummary(
  best: WorkerBestScoreResult | null | undefined,
  assignment: WorkerAssignment | null | undefined,
): string | null {
  const tool = best?.tool ?? assignment?.tool ?? null;
  const window = best?.window ?? assignment?.window ?? null;
  const algorithm = best?.algorithm ?? assignment?.algorithm ?? null;
  if (!tool && !window && !algorithm) return null;

  const parts: string[] = [];
  if (tool) parts.push(tool);
  if (algorithm) parts.push(algorithm);
  if (window) parts.push(window);

  const total =
    best?.search_space_size && best.search_space_size > 0
      ? best.search_space_size
      : assignment?.trialCount && assignment.trialCount > 0
        ? assignment.trialCount
        : null;
  const evaluated = best?.trials_evaluated ?? 0;
  if (total) {
    parts.push(`trials ${evaluated}/${total}`);
  } else if (evaluated > 0) {
    parts.push(`trials ${evaluated}`);
  }

  const concurrency = best?.concurrency ?? assignment?.concurrency ?? null;
  if (concurrency && concurrency > 1) {
    parts.push(`×${concurrency}`);
  }

  const threads = best?.trial_threads ?? assignment?.trialThreads ?? null;
  const memoryGb = best?.trial_memory_gb ?? assignment?.trialMemoryGb ?? null;
  if (threads != null && memoryGb != null) {
    parts.push(`${threads} CPU / ${memoryGb} GB`);
  }

  const slice = best?.benchmark_window;
  if (slice && slice !== window) {
    parts.push(`slice ${slice}`);
  }

  return parts.join(" · ");
}

export function formatWorkerTaskParams(
  best: WorkerBestScoreResult | null | undefined,
  assignment: WorkerAssignment | null | undefined,
): string | null {
  const params =
    best?.params && best.params.length > 0
      ? best.params
      : assignment?.selectedParams && assignment.selectedParams.length > 0
        ? assignment.selectedParams
        : null;
  if (!params?.length) return null;
  const preview = params.slice(0, 4).join(", ");
  const suffix = params.length > 4 ? ` +${params.length - 4}` : "";
  return `${params.length} params: ${preview}${suffix}`;
}
