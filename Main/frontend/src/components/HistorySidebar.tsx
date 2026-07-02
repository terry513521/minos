import { useEffect, useMemo, useState } from "react";
import { api, HistoryRecord } from "../api/client";
import {
  HistorySortKey,
  smartSearchHistory,
  sortHistory,
  sortLabel,
  toggleScoreSort,
} from "../utils/historyView";
import { ConfDetails } from "./ConfDetails";

const DEFAULT_VISIBLE = 5;
const DEFAULT_CHROMOSOMES = 5;

interface HistorySidebarProps {
  chromosomeFilter?: string | null;
  embedded?: boolean;
}

export function HistorySidebar({ chromosomeFilter, embedded = false }: HistorySidebarProps) {
  const [rows, setRows] = useState<HistoryRecord[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [chromosomes, setChromosomes] = useState<Array<{ chromosome: string; count: number }>>([]);
  const [filter, setFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<HistorySortKey>("score-desc");
  const [showAllRecords, setShowAllRecords] = useState(false);
  const [showAllChromosomes, setShowAllChromosomes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    if (chromosomeFilter) {
      setFilter(chromosomeFilter);
    }
  }, [chromosomeFilter]);

  useEffect(() => {
    api.historyChromosomes().then(setChromosomes).catch(() => {});
  }, []);

  function refresh() {
    setLoading(true);
    setError(null);
    const activeFilter = filter || undefined;
    Promise.all([
      api.listHistory(activeFilter),
      api.historyCount(activeFilter),
    ])
      .then(([list, countRes]) => {
        setRows(list);
        setTotal(countRes.count);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    setShowAllRecords(false);
  }, [filter]);

  useEffect(() => {
    setShowAllRecords(false);
  }, [search, sortKey]);

  async function handleImport() {
    setImporting(true);
    setError(null);
    try {
      await api.importHistory(false);
      const chroms = await api.historyChromosomes();
      setChromosomes(chroms);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  const visibleChromosomes = showAllChromosomes
    ? chromosomes
    : chromosomes.slice(0, DEFAULT_CHROMOSOMES);
  const hiddenChromosomeCount = Math.max(0, chromosomes.length - DEFAULT_CHROMOSOMES);

  const displayedRows = useMemo(() => {
    const searched = smartSearchHistory(rows, search);
    return sortHistory(searched, sortKey);
  }, [rows, search, sortKey]);

  const visibleRows = showAllRecords
    ? displayedRows
    : displayedRows.slice(0, DEFAULT_VISIBLE);
  const hiddenRecordCount = Math.max(0, displayedRows.length - DEFAULT_VISIBLE);

  const body = (
    <>
      <label className="history-search">
        <span className="sr-only">Search history</span>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search window, chr, score…"
          aria-label="Smart search history"
        />
      </label>

      <div className="history-toolbar-line">
        <div className="history-toolbar-filters">
          <button
            type="button"
            className={`history-chrom-chip${filter === "" ? " active" : ""}`}
            onClick={() => setFilter("")}
          >
            All
          </button>
          {visibleChromosomes.map((row) => (
            <button
              key={row.chromosome}
              type="button"
              className={`history-chrom-chip${filter === row.chromosome ? " active" : ""}`}
              onClick={() => setFilter(row.chromosome)}
            >
              {row.chromosome}
              <span className="history-chrom-count">{row.count}</span>
            </button>
          ))}
          {!showAllChromosomes && hiddenChromosomeCount > 0 && (
            <button
              type="button"
              className="button ghost history-show-all-chrom"
              onClick={() => setShowAllChromosomes(true)}
            >
              +{hiddenChromosomeCount}
            </button>
          )}
          {showAllChromosomes && chromosomes.length > DEFAULT_CHROMOSOMES && (
            <button
              type="button"
              className="button ghost history-show-all-chrom"
              onClick={() => setShowAllChromosomes(false)}
            >
              Less
            </button>
          )}
        </div>
        <div className="history-toolbar-actions">
          <button
            type="button"
            className="button ghost history-sort-btn"
            onClick={() => setSortKey((k) => toggleScoreSort(k))}
            title="Toggle score sort"
          >
            {sortLabel(sortKey)}
          </button>
          <button type="button" className="button ghost" onClick={handleImport} disabled={importing}>
            {importing ? "Importing…" : "Sync JSON"}
          </button>
        </div>
      </div>

      {total != null && (
        <div className="history-meta">
          <span className="chip chip-muted">
            {displayedRows.length} match{displayedRows.length === 1 ? "" : "es"}
            {search.trim() ? ` · ${total} loaded` : ""}
          </span>
        </div>
      )}

      {error && <div className="alert error">{error}</div>}
      {loading && <p className="empty-state">Loading history…</p>}
      {!loading && displayedRows.length === 0 && (
        <p className="empty-state">
          {search.trim() ? "No records match your search." : "No records for this filter."}
        </p>
      )}
      {!loading && visibleRows.length > 0 && (
        <ul className="history-list">
          {visibleRows.map((row) => (
            <li key={row.id} className="history-item">
              <div className="history-item-top">
                <span className="history-chrom">{row.chromosome}</span>
                <span className="history-score">{(row.score * 100).toFixed(1)}%</span>
                <ConfDetails conf={row.conf} label="···" compact />
              </div>
              <code className="history-window">{row.window}</code>
            </li>
          ))}
        </ul>
      )}
      {!loading && !showAllRecords && hiddenRecordCount > 0 && (
        <button
          type="button"
          className="button ghost history-show-all-records"
          onClick={() => setShowAllRecords(true)}
        >
          Show all ({displayedRows.length})
        </button>
      )}
      {!loading && showAllRecords && hiddenRecordCount > 0 && (
        <button
          type="button"
          className="button ghost history-show-all-records"
          onClick={() => setShowAllRecords(false)}
        >
          Show {DEFAULT_VISIBLE}
        </button>
      )}
    </>
  );

  if (embedded) return <div className="history-sidebar embedded">{body}</div>;

  return <section className="panel history-sidebar">{body}</section>;
}
