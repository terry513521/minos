import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, PortfolioRoundRow, PortfolioRoundsResponse } from "../api/client";

const INSTANCE_COLORS = [
  "#c4b5fd",
  "#34d399",
  "#67e8f9",
  "#fbbf24",
  "#fb7185",
  "#a78bfa",
  "#6ee7b7",
];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(5, 10);
  return `${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function avg(nums: number[]): number {
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function binGenomic(filtered: PortfolioRoundRow[], chrom: string, bins = 12) {
  const subset = filtered.filter((r) => r.chrom === chrom && r.start > 0);
  if (!subset.length) return { categories: [] as string[], scores: [] as number[] };
  const minS = Math.min(...subset.map((r) => r.start));
  const maxS = Math.max(...subset.map((r) => r.start));
  const width = Math.max(1, Math.ceil((maxS - minS) / bins));
  const buckets: Record<number, number[]> = {};
  for (const r of subset) {
    const b = Math.floor((r.start - minS) / width);
    (buckets[b] ||= []).push(r.score_100);
  }
  const keys = Object.keys(buckets)
    .map(Number)
    .sort((a, b) => a - b);
  return {
    categories: keys.map((k) => `${Math.round((minS + k * width) / 1e6)}M`),
    scores: keys.map((k) => Math.round(avg(buckets[k]) * 100) / 100),
  };
}

type ChartSeries = { name: string; data: number[]; color?: string };

function SimpleLineChart({
  categories,
  series,
  height = 220,
  yMin,
  yMax,
}: {
  categories: string[];
  series: ChartSeries[];
  height?: number;
  yMin?: number;
  yMax?: number;
}) {
  const width = 640;
  const pad = { top: 12, right: 12, bottom: 28, left: 36 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const allValues = series.flatMap((s) => s.data).filter((v) => Number.isFinite(v));
  const minV = yMin ?? (allValues.length ? Math.min(...allValues) : 0);
  const maxV = yMax ?? (allValues.length ? Math.max(...allValues) : 100);
  const span = maxV - minV || 1;

  const xAt = (i: number) =>
    pad.left + (categories.length <= 1 ? innerW / 2 : (i / (categories.length - 1)) * innerW);
  const yAt = (v: number) => pad.top + innerH - ((v - minV) / span) * innerH;

  return (
    <div className="rounds-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Line chart">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = pad.top + innerH * (1 - t);
          const val = minV + span * t;
          return (
            <g key={t}>
              <line
                x1={pad.left}
                y1={y}
                x2={width - pad.right}
                y2={y}
                className="rounds-chart-grid"
              />
              <text x={4} y={y + 4} className="rounds-chart-axis">
                {val.toFixed(val >= 10 ? 0 : 1)}
              </text>
            </g>
          );
        })}
        {series.map((s, si) => {
          const color = s.color || INSTANCE_COLORS[si % INSTANCE_COLORS.length];
          const points = s.data
            .map((v, i) => `${xAt(i)},${yAt(v)}`)
            .join(" ");
          return (
            <g key={s.name}>
              <polyline
                fill="none"
                stroke={color}
                strokeWidth="2"
                strokeLinejoin="round"
                points={points}
              />
              {s.data.map((v, i) => (
                <circle key={`${s.name}-${i}`} cx={xAt(i)} cy={yAt(v)} r="3" fill={color} />
              ))}
            </g>
          );
        })}
        {categories.map((label, i) => (
          <text
            key={label + i}
            x={xAt(i)}
            y={height - 6}
            textAnchor="middle"
            className="rounds-chart-axis"
          >
            {label}
          </text>
        ))}
      </svg>
      <div className="rounds-chart-legend">
        {series.map((s, i) => (
          <span key={s.name} className="rounds-legend-item">
            <span
              className="rounds-legend-swatch"
              style={{ background: s.color || INSTANCE_COLORS[i % INSTANCE_COLORS.length] }}
            />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function SimpleBarChart({
  categories,
  series,
  height = 180,
  horizontal = false,
}: {
  categories: string[];
  series: ChartSeries[];
  height?: number;
  horizontal?: boolean;
}) {
  const width = 640;
  const pad = horizontal
    ? { top: 8, right: 16, bottom: 8, left: 88 }
    : { top: 8, right: 8, bottom: 28, left: 36 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const data = series[0]?.data ?? [];
  const maxV = Math.max(...data, 1);

  if (horizontal) {
    const barH = innerH / Math.max(categories.length, 1) - 4;
    return (
      <div className="rounds-chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Bar chart">
          {categories.map((cat, i) => {
            const v = data[i] ?? 0;
            const w = (v / maxV) * innerW;
            const y = pad.top + i * (barH + 4);
            return (
              <g key={cat}>
                <text x={pad.left - 8} y={y + barH / 2 + 4} textAnchor="end" className="rounds-chart-axis">
                  {cat}
                </text>
                <rect
                  x={pad.left}
                  y={y}
                  width={w}
                  height={barH}
                  rx="4"
                  className="rounds-chart-bar"
                />
                <text x={pad.left + w + 6} y={y + barH / 2 + 4} className="rounds-chart-axis">
                  {v.toFixed(1)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    );
  }

  const barW = innerW / Math.max(categories.length, 1) - 6;
  return (
    <div className="rounds-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Bar chart">
        {categories.map((cat, i) => {
          const v = data[i] ?? 0;
          const h = (v / maxV) * innerH;
          const x = pad.left + i * (barW + 6);
          const y = pad.top + innerH - h;
          return (
            <g key={cat}>
              <rect x={x} y={y} width={barW} height={h} rx="4" className="rounds-chart-bar" />
              <text x={x + barW / 2} y={height - 6} textAnchor="middle" className="rounds-chart-axis">
                {cat}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function SimpleDonut({
  data,
  size = 160,
}: {
  data: { label: string; value: number }[];
  size?: number;
}) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  let angle = -Math.PI / 2;

  const slices = data.map((d, i) => {
    const slice = (d.value / total) * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    angle += slice;
    const x2 = cx + r * Math.cos(angle);
    const y2 = cy + r * Math.sin(angle);
    const large = slice > Math.PI ? 1 : 0;
    const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
    return { ...d, path, color: INSTANCE_COLORS[i % INSTANCE_COLORS.length] };
  });

  return (
    <div className="rounds-donut-wrap">
      <svg width={size} height={size} role="img" aria-label="Donut chart">
        {slices.map((s) => (
          <path key={s.label} d={s.path} fill={s.color} opacity={0.9} />
        ))}
        <circle cx={cx} cy={cy} r={r * 0.55} fill="var(--bg-elevated)" />
        <text x={cx} y={cy + 4} textAnchor="middle" className="rounds-donut-center">
          {total}
        </text>
      </svg>
      <div className="rounds-donut-legend">
        {data.map((d, i) => (
          <span key={d.label} className="rounds-legend-item">
            <span
              className="rounds-legend-swatch"
              style={{ background: INSTANCE_COLORS[i % INSTANCE_COLORS.length] }}
            />
            {d.label} ({d.value})
          </span>
        ))}
      </div>
    </div>
  );
}

export function RoundsHistoryPage() {
  const [data, setData] = useState<PortfolioRoundsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chrom, setChrom] = useState("all");
  const [instance, setInstance] = useState("all");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.getPortfolioRounds();
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load rounds");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleSync() {
    setSyncing(true);
    setError(null);
    try {
      const payload = await api.syncPortfolioRounds(false);
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  const summary = data?.summary;
  const rows = data?.rows ?? [];

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (chrom !== "all" && r.chrom !== chrom) return false;
        if (instance !== "all" && r.instance !== instance) return false;
        return true;
      }),
    [rows, chrom, instance],
  );

  const roundOrder = useMemo(
    () => Array.from(new Set(filtered.map((r) => r.round_id))).sort(),
    [filtered],
  );
  const timeLabels = useMemo(() => roundOrder.map(fmtDate), [roundOrder]);

  const scoreByRound = useMemo(
    () =>
      roundOrder.map((id) => {
        const pts = filtered.filter((r) => r.round_id === id).map((r) => r.score_100);
        return Math.round(avg(pts) * 100) / 100;
      }),
    [filtered, roundOrder],
  );

  const rankByRound = useMemo(
    () =>
      roundOrder.map((id) => {
        const pts = filtered.filter((r) => r.round_id === id).map((r) => r.rank ?? 99);
        return Math.min(...pts);
      }),
    [filtered, roundOrder],
  );

  const gapByRound = useMemo(
    () =>
      roundOrder.map((id) => {
        const pts = filtered
          .filter((r) => r.round_id === id)
          .map((r) => r.gap_to_leader ?? 0);
        return Math.round(avg(pts) * 10) / 10;
      }),
    [filtered, roundOrder],
  );

  const pieData = useMemo(() => {
    const uniqueChromRounds: Record<string, Set<string>> = {};
    for (const r of filtered) {
      (uniqueChromRounds[r.chrom] ||= new Set()).add(r.round_id);
    }
    return Object.entries(uniqueChromRounds).map(([label, set]) => ({
      label,
      value: set.size,
    }));
  }, [filtered]);

  const chromAvg = useMemo(
    () =>
      (summary?.chroms ?? []).map((c) => {
        const pts = filtered.filter((r) => r.chrom === c).map((r) => r.score_100);
        return Math.round(avg(pts) * 100) / 100;
      }),
    [filtered, summary?.chroms],
  );

  const breakdownChrom = chrom === "all" ? summary?.chroms[0] || "chr21" : chrom;
  const breakdownRows = useMemo(
    () => filtered.filter((r) => r.chrom === breakdownChrom),
    [filtered, breakdownChrom],
  );

  const genomicChrom = chrom === "all" ? "chr21" : chrom;
  const genomic = useMemo(() => binGenomic(filtered, genomicChrom), [filtered, genomicChrom]);

  const instanceSeries = useMemo(() => {
    const ids = summary?.instances ?? [];
    return ids
      .filter((id) => instance === "all" || id === instance)
      .map((id, i) => ({
        name: id,
        color: INSTANCE_COLORS[i % INSTANCE_COLORS.length],
        data: roundOrder.map((rid) => {
          const hit = filtered.find((r) => r.round_id === rid && r.instance === id);
          return hit ? hit.score_100 : 0;
        }),
      }))
      .filter((s) => s.data.some((v) => v > 0));
  }, [summary?.instances, instance, roundOrder, filtered]);

  const tableRows = useMemo(
    () =>
      [...filtered]
        .sort((a, b) => (a.round_id < b.round_id ? 1 : -1))
        .slice(0, 30),
    [filtered],
  );

  const syncedLabel = data?.synced_at
    ? new Date(data.synced_at).toLocaleString()
    : "never";

  return (
    <div className="rounds-page">
      <div className="rounds-page-head">
        <div>
          <p className="rounds-kicker">
            <Link to="/">← Console</Link>
          </p>
          <h1 className="rounds-title">Portfolio round history</h1>
          <p className="rounds-lead">
            Live sync from{" "}
            <code>{data?.api_url || "portfolio API / rounds.json"}</code>
            {summary?.date_min && summary?.date_max ? (
              <>
                {" "}
                · {summary.date_min.slice(0, 10)} to {summary.date_max.slice(0, 10)}
              </>
            ) : null}
            {summary ? (
              <>
                {" "}
                · {summary.rounds} rounds · {summary.rows} instance scores
              </>
            ) : null}
          </p>
          <p className="rounds-meta">
            Source: <strong>{data?.source ?? "—"}</strong> · Last synced: {syncedLabel}
          </p>
        </div>
        <div className="rounds-actions">
          <button
            type="button"
            className="button ghost"
            onClick={() => void refresh()}
            disabled={loading || syncing}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
          <button
            type="button"
            className="button primary"
            onClick={() => void handleSync()}
            disabled={syncing || loading}
          >
            {syncing ? "Syncing…" : "Sync from API"}
          </button>
        </div>
      </div>

      {error && <div className="rounds-error">{error}</div>}

      {summary && (
        <div className="rounds-stat-grid">
          <div className="rounds-stat">
            <span className="rounds-stat-label">Rounds</span>
            <span className="rounds-stat-value">{summary.rounds}</span>
          </div>
          <div className="rounds-stat">
            <span className="rounds-stat-label">Avg score (0–100)</span>
            <span className="rounds-stat-value">{summary.avg_score}</span>
          </div>
          <div className="rounds-stat">
            <span className="rounds-stat-label">Best score</span>
            <span className="rounds-stat-value accent">{summary.best_score}</span>
          </div>
          <div className="rounds-stat">
            <span className="rounds-stat-label">Filtered rows</span>
            <span className="rounds-stat-value">{filtered.length}</span>
          </div>
        </div>
      )}

      <section className="panel rounds-filters">
        <div className="rounds-filter-row">
          <label className="rounds-filter">
            <span>Chromosome</span>
            <select value={chrom} onChange={(e) => setChrom(e.target.value)}>
              <option value="all">All chromosomes</option>
              {(summary?.chroms ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="rounds-filter">
            <span>Instance</span>
            <select value={instance} onChange={(e) => setInstance(e.target.value)}>
              <option value="all">All instances</option>
              {(summary?.instances ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {!loading && rows.length === 0 && (
        <section className="panel rounds-empty">
          <p>No portfolio rounds loaded yet.</p>
          <p className="muted">Click “Sync from API” or ensure rounds.json exists at the repo root.</p>
        </section>
      )}

      {rows.length > 0 && (
        <>
          <div className="rounds-chart-grid">
            <section className="panel">
              <h2 className="rounds-panel-title">Score over time (avg per round)</h2>
              <p className="rounds-panel-hint">Y-axis: score_100 · X-axis: round date (UTC)</p>
              <SimpleLineChart
                categories={timeLabels}
                series={[{ name: "Avg score", data: scoreByRound, color: "#67e8f9" }]}
                yMin={50}
                yMax={100}
              />
            </section>
            <section className="panel">
              <h2 className="rounds-panel-title">Rank and gap to leader</h2>
              <p className="rounds-panel-hint">Lower rank is better · gap = points below round leader</p>
              <SimpleLineChart
                categories={timeLabels}
                series={[
                  { name: "Best rank", data: rankByRound, color: "#fbbf24" },
                  { name: "Gap to leader", data: gapByRound, color: "#fb7185" },
                ]}
              />
            </section>
          </div>

          <div className="rounds-chart-grid">
            <section className="panel">
              <h2 className="rounds-panel-title">Score by instance (per round)</h2>
              <SimpleLineChart
                categories={timeLabels}
                series={instanceSeries}
                yMin={50}
                yMax={100}
              />
            </section>
            <section className="panel">
              <h2 className="rounds-panel-title">Rounds by chromosome</h2>
              <div className="rounds-chrom-row">
                <SimpleDonut data={pieData} />
                <div className="rounds-chrom-bars">
                  <h3 className="rounds-subtitle">Avg score by chromosome</h3>
                  <SimpleBarChart
                    categories={summary?.chroms ?? []}
                    series={[{ name: "Avg score_100", data: chromAvg }]}
                    horizontal
                    height={Math.max(120, (summary?.chroms.length ?? 1) * 36)}
                  />
                </div>
              </div>
            </section>
          </div>

          <div className="rounds-chart-grid">
            <section className="panel">
              <h2 className="rounds-panel-title">Genomic position vs score ({genomicChrom})</h2>
              <SimpleBarChart
                categories={genomic.categories}
                series={[{ name: "Mean score", data: genomic.scores }]}
              />
            </section>
            <section className="panel">
              <h2 className="rounds-panel-title">
                Score breakdown ({breakdownChrom} avg)
              </h2>
              <SimpleBarChart
                categories={["Core F1", "Completeness", "FP rate", "Quality"]}
                series={[
                  {
                    name: "Avg contribution (pts)",
                    data: [
                      Math.round(avg(breakdownRows.map((r) => r.core ?? 0)) * 100) / 100,
                      Math.round(avg(breakdownRows.map((r) => r.completeness ?? 0)) * 100) / 100,
                      Math.round(avg(breakdownRows.map((r) => r.fp ?? 0)) * 100) / 100,
                      Math.round(avg(breakdownRows.map((r) => r.quality ?? 0)) * 100) / 100,
                    ],
                  },
                ]}
              />
            </section>
          </div>

          <section className="panel">
            <h2 className="rounds-panel-title">Recent rounds (top 30)</h2>
            <div className="rounds-table-wrap">
              <table className="rounds-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Chr</th>
                    <th>Window</th>
                    <th>Instance</th>
                    <th>Score</th>
                    <th>Rank</th>
                    <th>Gap</th>
                    <th>F1 SNP</th>
                    <th>F1 indel</th>
                    <th>Runtime</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((r) => (
                    <tr key={`${r.round_id}-${r.instance}-${r.region}`}>
                      <td>{fmtDate(r.round_id)}</td>
                      <td>{r.chrom}</td>
                      <td className="mono">{r.region.split(":")[1] || r.region}</td>
                      <td>{r.instance}</td>
                      <td className="num">{r.score_100.toFixed(2)}</td>
                      <td className="num">{r.rank ?? "—"}</td>
                      <td className="num">
                        {r.gap_to_leader != null ? r.gap_to_leader.toFixed(1) : "—"}
                      </td>
                      <td className="num">{r.f1_snp?.toFixed(3) ?? "—"}</td>
                      <td className="num">{r.f1_indel?.toFixed(3) ?? "—"}</td>
                      <td className="num">{r.runtime_s}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
