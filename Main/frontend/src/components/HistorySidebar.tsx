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
  const [seeding, setSeeding] = useState(false);

  useEffect(() => {
    if (chromosomeFilter) {
      setFilter(chromosomeFilter);
    }
  }, [chromosomeFilter]);

  function loadMeta() {
    Promise.all([api.historyChromosomes(), api.historyOrigins(), api.listWorkers()])
      .then(([chroms, originRows, workerRows]) => {
        setChromosomes(chroms);
        setOrigins(originRows);
        setWorkers(workerRows);
      })
      .catch(() => {});
  }

  useEffect(() => {
    loadMeta();
  }, []);

  function refresh() {
    setLoading(true);
    setError(null);
    const activeFilter = filter || undefined;
    const activeOrigin = originFilter || undefined;
    Promise.all([
      api.listHistory(activeFilter, 500, activeOrigin),
      api.historyCount(activeFilter, activeOrigin),
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
  }, [filter, originFilter]);

  useEffect(() => {
    setShowAllRecords(false);
  }, [search, sortKey]);

  async function handleImport() {
    setImporting(true);
    setError(null);
    try {
      await api.importHistory(false);
      loadMeta();
      refresh();
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
      loadMeta();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function handleSeedChr22(dryRun: boolean) {
    const seedWorkers = workers.filter(workerReachable);
    if (seedWorkers.length === 0) {
      setError("Register a worker with health_url or base_url before seeding chr22 history.");
      return;
    }
    setSeeding(true);
    setError(null);
    try {
      const result = await api.seedChr22History({
        worker_ids: seedWorkers.map((w) => w.id),
        limit: SEED_BATCH_LIMIT,
        dry_run: dryRun,
        source_chromosomes: ["chr20", "chr21"],
      });
      loadMeta();
      refresh();
      const waveCount = result.waves_completed ?? 0;
      const perWave = result.workers_per_wave ?? seedWorkers.length;
      const usedCount = result.worker_ids_used?.length ?? seedWorkers.length;
      const skippedWorkers = result.workers_skipped ?? [];
      const dispatchLines = (result.worker_ids_used ?? [])
        .map((id) => {
          const name = workers.find((w) => w.id === id)?.name ?? id.slice(0, 8);
          const url = result.worker_dispatch_urls?.[id] ?? "?";
          return `${name} → ${url}`;
        })
        .join("\n");
      const skipLines = skippedWorkers
        .map((s) => `${s.worker_name ?? s.worker_id}: ${s.reason}`)
        .join("\n");
      const summary = dryRun
        ? `Dry run: ${result.items.length} task(s) in ${waveCount} wave(s) of up to ${perWave} worker(s), ${usedCount} will receive POST /benchmark (${result.skipped_existing} already seeded)`
        : `Seeded ${result.scored} chr22 rows in ${waveCount} wave(s) (${perWave} worker(s) per wave, ${usedCount} workers used, ${result.skipped_existing} skipped, ${result.failed} failed)`;
      const detail = [dispatchLines, skipLines ? `Skipped:\n${skipLines}` : ""]
        .filter(Boolean)
        .join("\n\n");
      setError(null);
      window.alert(detail ? `${summary}\n\n${detail}` : summary);
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
        <button
          type="button"
          className="button ghost"
          disabled={seeding}
          onClick={() => handleSeedChr22(true)}
        >
          Preview chr22 seed
        </button>
        <button
          type="button"
          className="button"
          disabled={seeding}
          onClick={() => handleSeedChr22(false)}
        >
            {seeding
              ? "Seeding…"
              : `Seed chr22 (${SEED_BATCH_LIMIT})`}
          </button>
          {workers.filter(workerReachable).length > 0 && (
            <span className="chip chip-muted history-seed-hint">
              {workers.filter((w) => w.dispatch_base_url).length || workers.filter(workerReachable).length}{" "}
              dispatchable · parallel wave → wait → next wave
            </span>
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
