import { AutoSelectedCandidate } from "../api/client";

export const AUTO_SCORE_WEIGHT = 0.4;
export const AUTO_SIMILARITY_WEIGHT = 0.6;

export type SelectionReason = "top_score" | "most_similar" | "best_composite";

export function candidateHistoryScore(candidate: {
  history_score?: number | null;
  rank_score?: number;
}): number {
  if (candidate.history_score != null) return candidate.history_score;
  return candidate.rank_score ?? 0;
}

export function compositeCandidateScore(candidate: {
  history_score?: number | null;
  rank_score?: number;
  similarity?: number | null;
}): number {
  const score = candidateHistoryScore(candidate);
  const similarity = candidate.similarity ?? 0;
  return AUTO_SCORE_WEIGHT * score + AUTO_SIMILARITY_WEIGHT * similarity;
}

const SELECTION_LABELS: Record<SelectionReason, string> = {
  top_score: "Top score",
  most_similar: "Most similar",
  best_composite: "Best composite",
};

export function selectionReasonLabel(reason: SelectionReason | string | null | undefined): string {
  if (!reason) return "Selected";
  if (reason in SELECTION_LABELS) return SELECTION_LABELS[reason as SelectionReason];
  return String(reason);
}

export type CandidateMetricFields = {
  history_score?: number | null;
  rank_score?: number;
  similarity?: number | null;
  algorithm?: string | null;
  composite_score?: number;
};

export type CandidateRegionFields = {
  source_window?: string | null;
  window?: string | null;
};

export function formatSelectionMetric(
  reason: SelectionReason | string | null | undefined,
  item: CandidateMetricFields,
): string {
  if (reason && reason in SELECTION_LABELS) {
    return SELECTION_LABELS[reason as SelectionReason];
  }
  if (item.algorithm) {
    return item.algorithm;
  }
  const score = candidateHistoryScore(item);
  return `score ${(score * 100).toFixed(1)}%`;
}

export function candidateRegion(item: CandidateRegionFields): string | null {
  return item.source_window?.trim() || item.window?.trim() || null;
}

export function selectionSlotsByIndex(
  selected: AutoSelectedCandidate[],
): Map<number, AutoSelectedCandidate[]> {
  const map = new Map<number, AutoSelectedCandidate[]>();
  for (const slot of selected) {
    const existing = map.get(slot.index) ?? [];
    existing.push(slot);
    map.set(slot.index, existing);
  }
  return map;
}

export function isSelectedCandidateIndex(
  index: number,
  selected: AutoSelectedCandidate[],
): boolean {
  return selected.some((slot) => slot.index === index);
}
