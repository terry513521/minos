import { useEffect, useMemo, useState } from "react";
import {
  api,
  HistoryChromosomeSummary,
  HistoryOrigin,
  HistoryOriginSummary,
  HistoryRecord,
  WorkerRecord,
} from "../api/client";
import {
  HISTORY_ORIGIN_FILTER_OPTIONS,
  historyOriginClass,
  historyOriginLabel,
} from "../utils/historyOrigin";
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
const SEED_BATCH_LIMIT = 50;

function workerReachable(worker: WorkerRecord): boolean {
  return Boolean((worker.dispatch_base_url || worker.base_url || worker.health_url || "").trim());
}

interface HistorySidebarProps {
  chromosomeFilter?: string | null;
  embedded?: boolean;
}

export function HistorySidebar({ chromosomeFilter, embedded = false }: HistorySidebarProps) {
  const [rows, setRows] = useState<HistoryRecord[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [chromosomes, setChromosomes] = useState<HistoryChromosomeSummary[]>([]);
  const [origins, setOrigins] = useState<HistoryOriginSummary[]>([]);
  const [workers, setWorkers] = useState<WorkerRecord[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [originFilter, setOriginFilter] = useState<"" | HistoryOrigin>("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<HistorySortKey>("score-desc");
  const [showAllRecords, setShowAllRecords] = useState(false);
  const [showAllChromosomes, setShowAllChromosomes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [refetching, setRefetching] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [seedWorkerId, setSeedWorkerId] = useState("");

  const seedableWorkers = useMemo(
    () => workers.filter(workerReachable),
    [workers],
  );

  useEffect(() => {
    if (!seedWorkerId && seedableWorkers.length > 0) {
      setSeedWorkerId(seedableWorkers[0].id);
    }
  }, [seedWorkerId, seedableWorkers]);

  useEffect(() => {
    if (chromosomeFilter) {
      setFilter(chromosomeFilter);
    }
  }, [chromosomeFilter]);

  function loadMeta() {
    return Promise.all([api.historyChromosomes(), api.historyOrigins(), api.listWorkers()])
      .then(([chroms, originRows, workerRows]) => {
        setChromosomes(chroms);
        setOrigins(originRows);
        setWorkers(workerRows);
      })
      .catch(() => {});
  }

  useEffect(() => {
    void loadMeta();
  }, []);

  async function refresh(includeMeta = false) {
    setLoading(true);
    setError(null);
    const activeFilter = filter || undefined;
    const activeOrigin = originFilter || undefined;
    try {
      if (includeMeta) {
        await loadMeta();
      }
      const [list, countRes] = await Promise.all([
        api.listHistory(activeFilter, 500, activeOrigin),
        api.historyCount(activeFilter, activeOrigin),
      ]);
      setRows(list);
      setTotal(countRes.count);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefetch() {
    setRefetching(true);
    setError(null);
    try {
      await refresh(true);
    } finally {
      setRefetching(false);
    }
  }

  useEffect(() => {
    void refresh();
    setShowAllRecords(false);
  }, [filter, originFilter]);

  useEffect(() => {
    setShowAllRecords(false);
  }, [search, sortKey]);

  async function handleImport() {
    setImporting(true);
    setError(null);
    try {
      await api.importHistory(false);
      await loadMeta();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  async function handleSyncRounds() {
    setSyncing(true);
    setError(null);
    try {
      await api.syncHistoryRounds(false);
      await loadMeta();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function handleSeedChr22(dryRun: boolean) {
    if (!seedWorkerId) {
      setError("Select a worker before seeding chr22 history.");
      return;
    }
    const seedWorker = seedableWorkers.find((w) => w.id === seedWorkerId);
    if (!seedWorker) {
      setError("Selected worker is not reachable. Pick a worker with health_url or base_url.");
      return;
    }
    setSeeding(true);
    setError(null);
    try {
      const result = await api.seedChr22History({
        worker_id: seedWorkerId,
        limit: SEED_BATCH_LIMIT,
        dry_run: dryRun,
        source_chromosomes: ["chr20", "chr21"],
      });
      await loadMeta();
      await refresh();
      const workerName = seedWorker.name;
      const workerUrl =
        result.worker_dispatch_urls?.[seedWorkerId] ?? seedWorker.dispatch_base_url ?? "?";
      const summary = dryRun
        ? `Dry run: ${result.items.filter((i) => i.status === "dry_run").length} new benchmark(s) on ${workerName} (${result.skipped_existing} already seeded)`
        : `Seeded ${result.scored} chr22 rows on ${workerName} (${result.skipped_existing} already seeded, ${result.failed} failed)`;
      setError(null);
      window.alert(`${summary}\n\n${workerName} → ${workerUrl}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Seed failed");
    } finally {
      setSeeding(false);
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

  const originSummary = origins
    .map((row) => `${row.label} ${row.count}`)
    .join(" · ");

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

      <div className="history-toolbar-line history-origin-filters">
        {HISTORY_ORIGIN_FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.value || "all"}
            type="button"
            className={`history-origin-chip${originFilter === opt.value ? " active" : ""}`}
            onClick={() => setOriginFilter(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

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
              title={`Real ${row.portfolio} · Seeded ${row.seed}`}
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
            className="button ghost history-refetch-btn"
            onClick={() => void handleRefetch()}
            disabled={refetching || loading || syncing || importing || seeding}
            title="Reload portfolio history from the database, including chr22 seeded rows"
          >
            {refetching ? "Refetching…" : "Refetch"}
          </button>
          <button
            type="button"
            className="button ghost history-sort-btn"
            onClick={() => setSortKey((k) => toggleScoreSort(k))}
            title="Toggle score sort"
          >
            {sortLabel(sortKey)}
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={handleSyncRounds}
            disabled={syncing}
          >
            {syncing ? "Syncing…" : "Sync API"}
          </button>
          <button type="button" className="button ghost" onClick={handleImport} disabled={importing}>
            {importing ? "Importing…" : "Sync JSON"}
          </button>
        </div>
      </div>

      <div className="history-seed-actions">
        {seedableWorkers.length > 0 && (
          <label className="history-seed-worker">
            <span className="sr-only">Worker for chr22 seeding</span>
            <select
              value={seedWorkerId}
              onChange={(e) => setSeedWorkerId(e.target.value)}
              disabled={seeding}
              aria-label="Worker for chr22 seeding"
            >
              {seedableWorkers.map((worker) => (
                <option key={worker.id} value={worker.id}>
                  {worker.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="button ghost"
          disabled={seeding || !seedWorkerId}
          onClick={() => handleSeedChr22(true)}
        >
          Preview chr22 seed
        </button>
        <button
          type="button"
          className="button"
          disabled={seeding || !seedWorkerId}
          onClick={() => handleSeedChr22(false)}
        >
          {seeding ? "Seeding…" : `Seed chr22 (${SEED_BATCH_LIMIT})`}
        </button>
        {seedWorkerId && (
          <span className="chip chip-muted history-seed-hint">one worker · sequential</span>
        )}
      </div>

      {total != null && (
        <div className="history-meta">
          <span className="chip chip-muted">
            {displayedRows.length} match{displayedRows.length === 1 ? "" : "es"}
            {search.trim() ? ` · ${total} loaded` : ""}
          </span>
          {originSummary && (
            <span className="chip chip-muted history-origin-summary">{originSummary}</span>
          )}
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
                <span className={historyOriginClass(row.history_origin)}>
                  {historyOriginLabel(row.history_origin)}
                </span>
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
