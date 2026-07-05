import { HistoryOrigin } from "../api/client";

export const HISTORY_ORIGIN_LABELS: Record<HistoryOrigin, string> = {
  portfolio: "Real",
  seed: "Seeded",
  worker: "Worker",
  import: "Import",
};

export const HISTORY_ORIGIN_FILTER_OPTIONS: Array<{
  value: "" | HistoryOrigin;
  label: string;
}> = [
  { value: "", label: "All origins" },
  { value: "portfolio", label: "Real" },
  { value: "seed", label: "Seeded" },
  { value: "worker", label: "Worker" },
  { value: "import", label: "Import" },
];

export function historyOriginLabel(origin: HistoryOrigin | string | undefined): string {
  if (!origin) return HISTORY_ORIGIN_LABELS.portfolio;
  if (origin in HISTORY_ORIGIN_LABELS) {
    return HISTORY_ORIGIN_LABELS[origin as HistoryOrigin];
  }
  return String(origin);
}

export function historyOriginClass(origin: HistoryOrigin | string | undefined): string {
  const key = origin && origin in HISTORY_ORIGIN_LABELS ? origin : "portfolio";
  return `history-origin-tag history-origin-tag--${key}`;
}
