const API_BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export interface HistoryRecord {
  id: string;
  window: string;
  chromosome: string;
  start: number;
  end: number;
  tool: string;
  conf: Record<string, unknown>;
  score: number;
  run_id?: string | null;
  created_at: string;
}

export interface HistoryImportResult {
  files: number;
  parsed: number;
  imported: number;
  skipped_unscored: number;
  skipped_invalid: number;
  skipped_duplicate: number;
}

export interface CandidatePreview {
  index: number;
  base_conf: Record<string, unknown>;
  rank_score: number;
  history_id: string | null;
  source_window: string | null;
  history_score: number | null;
  similarity: number | null;
}

export interface FindCandidatesResponse {
  window: string;
  chromosome: string;
  tool: string;
  k_candidates: number;
  candidates: CandidatePreview[];
  used_default: boolean;
  history_matched: number;
  coordinate_matched: number;
  total_history: number;
  ranked_pool_size: number;
  min_similarity: number;
}

export interface FindCandidatesPayload {
  window: string;
  tool?: string;
  k_candidates?: number;
  min_similarity?: number;
}

export type WorkerStatus = "online" | "offline" | "draining" | "disabled";

export interface WorkerRecord {
  id: string;
  name: string;
  health_url: string | null;
  base_url: string | null;
  status: WorkerStatus;
  capabilities: Record<string, unknown>;
  tags: string[];
  version: string | null;
  last_heartbeat: string | null;
  created_at: string;
}

export interface WorkerRegisterPayload {
  name: string;
  health_url: string;
  base_url: string;
}

export interface WorkerRegisterResult {
  worker: WorkerRecord;
  registration_token: string;
}

export interface WorkerHealthCheckResult {
  worker_id: string;
  ok: boolean;
  status_code: number | null;
  health: Record<string, unknown> | null;
  error: string | null;
}

export interface WorkerTrialScore {
  index: number;
  label: string;
  success: boolean;
  score: number | null;
  raw_score: number | null;
  cached: boolean;
  error: string | null;
  is_best: boolean;
  recorded_at: string | null;
}

export interface WorkerBestScoreResult {
  worker_id: string;
  ok: boolean;
  status_code: number | null;
  status: string | null;
  job_id: string | null;
  window: string | null;
  tool: string | null;
  best_score: number | null;
  best_conf: Record<string, unknown>;
  trials_evaluated: number;
  search_space_size: number;
  updated_at: string | null;
  message: string | null;
  trials: WorkerTrialScore[];
  error: string | null;
}

export interface ParamIntervalPayload {
  min?: number;
  max?: number;
  step?: number;
  values?: string[];
}

export interface WorkerDispatchPayload {
  window: string;
  tool: string;
  base_conf: Record<string, unknown>;
  params: string[];
  param_intervals?: Record<string, ParamIntervalPayload>;
  concurrency: number;
  algorithm?: string;
  limit_seconds?: number;
  adaptive_max_trials?: number;
  candidate_index?: number;
}

export interface WorkerDispatchResult {
  worker_id: string;
  ok: boolean;
  status_code: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface WorkerStopResult {
  worker_id: string;
  ok: boolean;
  status_code: number | null;
  status: string | null;
  message: string | null;
  error: string | null;
}

export interface WorkersStopAllResult {
  workers: number;
  stopped_ok: number;
  results: Array<{
    worker_id: string;
    worker_name: string;
    ok: boolean;
    message: string | null;
    error: string | null;
  }>;
}

export interface PlatformRound {
  enabled: boolean;
  polled_at: string | null;
  error: string | null;
  has_active_round: boolean;
  round_id: string | null;
  status: string | null;
  region: string | null;
  chromosome: string | null;
  time_remaining_seconds: number | null;
  start_time: string | null;
  submission_end_time: string | null;
  scoring_end_time: string | null;
  phase_deadline_at: string | null;
  optimize_deadline_at: string | null;
  num_mutations: number | null;
  downsampled_coverage: number | null;
  has_submitted: boolean;
  demo_mode: boolean;
  hotkey_ss58: string | null;
}

export interface AutoModeTunableConfigUpdate {
  params: string[];
  param_intervals: Record<string, ParamIntervalPayload>;
  worker_algorithms?: Record<string, string>;
  worker_trial_threads?: Record<string, number>;
  worker_trial_memory_gb?: Record<string, number>;
  worker_concurrency?: Record<string, number>;
}

export interface AutoModeConfig {
  tool: string;
  params: string[];
  param_intervals: Record<string, ParamIntervalPayload>;
  worker_names: string[];
  worker_algorithms: Record<string, string>;
  worker_trial_threads: Record<string, number>;
  worker_trial_memory_gb: Record<string, number>;
  worker_concurrency: Record<string, number>;
  assignment_strategy: string;
  limit_seconds: number;
  adaptive_max_trials: number;
  concurrency: number;
  find_k: number;
  select_k: number;
  score_weight: number;
  similarity_weight: number;
}

export interface AutoDispatchAssignment {
  worker_id: string;
  worker_name: string;
  algorithm: string;
  candidate_index: number;
  selection_reason: "random" | string | null;
  composite_score: number;
  history_score: number | null;
  similarity: number | null;
  base_conf: Record<string, unknown>;
  window: string | null;
  params: string[];
  param_intervals: Record<string, ParamIntervalPayload>;
  concurrency: number;
  limit_seconds: number;
  dispatch_ok: boolean;
  dispatch_error: string | null;
  job_id: string | null;
}

export interface AutoSelectedCandidate {
  index: number;
  worker_name: string | null;
  algorithm: string | null;
  selection_reason: "random" | string | null;
  composite_score: number;
  history_score: number | null;
  similarity: number | null;
  source_window: string | null;
  base_conf: Record<string, unknown>;
}

export interface AutoModeStatus {
  enabled: boolean;
  running: boolean;
  region: string | null;
  last_started_region: string | null;
  started_at: string | null;
  config: AutoModeConfig;
  candidates_found: number;
  found_candidates: CandidatePreview[];
  time_remaining_seconds: number | null;
  limit_seconds: number | null;
  selected_candidates: AutoSelectedCandidate[];
  assignments: AutoDispatchAssignment[];
}

export interface AutoStartResult {
  ok: boolean;
  skipped?: boolean;
  region: string;
  tool: string;
  candidates_found: number;
  candidates_selected: number;
  workers_dispatched: number;
  found_candidates: CandidatePreview[];
  selected_candidates: AutoSelectedCandidate[];
  assignments: AutoModeStatus["assignments"];
  message: string;
}

export interface AutoBestResult {
  ok: boolean;
  best_score: number | null;
  best_conf: Record<string, unknown>;
  worker_id: string | null;
  worker_name: string | null;
  stopped_workers: Array<Record<string, unknown>>;
  message: string;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  getPlatformRound: () => request<PlatformRound>("/platform/round"),
  refreshPlatformRound: () =>
    request<PlatformRound>("/platform/round/refresh", { method: "POST" }),
  listHistory: (chromosome?: string, limit = 500) =>
    request<HistoryRecord[]>(
      `/history?limit=${limit}${chromosome ? `&chromosome=${encodeURIComponent(chromosome)}` : ""}`,
    ),
  historyCount: (chromosome?: string) =>
    request<{ count: number }>(
      `/history/count${chromosome ? `?chromosome=${encodeURIComponent(chromosome)}` : ""}`,
    ),
  historyChromosomes: () =>
    request<Array<{ chromosome: string; count: number }>>("/history/chromosomes"),
  findCandidates: (body: FindCandidatesPayload) =>
    request<FindCandidatesResponse>("/candidates/find", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  importHistory: (replace = false) =>
    request<HistoryImportResult>(
      `/history/import${replace ? "?replace=true" : ""}`,
      { method: "POST" },
    ),
  listWorkers: () => request<WorkerRecord[]>("/workers"),
  registerWorker: (body: WorkerRegisterPayload) =>
    request<WorkerRegisterResult>("/workers/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  checkWorkerHealth: (workerId: string) =>
    request<WorkerHealthCheckResult>(`/workers/${workerId}/health-check`),
  fetchWorkerBest: (workerId: string) =>
    request<WorkerBestScoreResult>(`/workers/${workerId}/best`),
  dispatchToWorker: (workerId: string, body: WorkerDispatchPayload) =>
    request<WorkerDispatchResult>(`/workers/${workerId}/dispatch`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  stopWorkerOptimization: (workerId: string) =>
    request<WorkerStopResult>(`/workers/${workerId}/stop`, { method: "POST" }),
  stopAllWorkersOptimization: () =>
    request<WorkersStopAllResult>("/workers/stop-all", { method: "POST" }),
  deleteWorker: (workerId: string) =>
    request<{ ok: string; worker_id: string }>(`/workers/${workerId}`, {
      method: "DELETE",
    }),
  updateWorker: (
    workerId: string,
    body: { health_url?: string; base_url?: string; status?: WorkerRecord["status"] },
  ) =>
    request<WorkerRecord>(`/workers/${workerId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  getAutoMode: () => request<AutoModeStatus>("/auto/mode"),
  setAutoMode: (enabled: boolean) =>
    request<AutoModeStatus>("/auto/mode", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  startAutoMode: (region: string, tool = "gatk") =>
    request<AutoStartResult>("/auto/start", {
      method: "POST",
      body: JSON.stringify({ region, tool }),
    }),
  fetchAutoBest: () => request<AutoBestResult>("/auto/best"),
  restartAutoMode: () =>
    request<AutoModeStatus>("/auto/restart", {
      method: "POST",
    }),
  updateAutoModeConfig: (body: AutoModeTunableConfigUpdate) =>
    request<AutoModeStatus>("/auto/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
