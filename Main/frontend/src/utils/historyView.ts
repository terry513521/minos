import { HistoryRecord } from "../api/client";

export type HistorySortKey = "score-desc" | "score-asc";

export function smartSearchHistory(rows: HistoryRecord[], query: string): HistoryRecord[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return rows;

  const tokens = trimmed.split(/\s+/).filter(Boolean);
  return rows.filter((row) => {
    const haystack = [
      row.chromosome,
      row.window,
      row.tool,
      row.score.toFixed(4),
      (row.score * 100).toFixed(1),
    ]
      .join(" ")
      .toLowerCase();
    return tokens.every((token) => haystack.includes(token));
  });
}

export function sortHistory(rows: HistoryRecord[], sortKey: HistorySortKey): HistoryRecord[] {
  const sorted = [...rows];
  if (sortKey === "score-asc") {
    sorted.sort((a, b) => a.score - b.score);
  } else {
    sorted.sort((a, b) => b.score - a.score);
  }
  return sorted;
}

export function toggleScoreSort(current: HistorySortKey): HistorySortKey {
  return current === "score-desc" ? "score-asc" : "score-desc";
}

export function sortLabel(key: HistorySortKey): string {
  return key === "score-asc" ? "Score ↑" : "Score ↓";
}
