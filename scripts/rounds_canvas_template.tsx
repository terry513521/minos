import {
  BarChart,
  Card,
  CardBody,
  CardHeader,
  Grid,
  H1,
  H2,
  H3,
  LineChart,
  PieChart,
  Row,
  Select,
  Stack,
  Stat,
  Table,
  Text,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";

type RoundRow = {
  round_id: string;
  region: string;
  chrom: string;
  start: number;
  end: number;
  leader_score: number;
  instance: string;
  label: string;
  score_100: number;
  rank: number;
  gap_to_leader: number;
  runtime_s: number;
  f1_snp: number;
  f1_indel: number;
  variant_count: number;
  core: number | null;
  completeness: number | null;
  fp: number | null;
  quality: number | null;
  heterozygosity: number | null;
  max_reads: number | null;
  confidence: number | null;
};

const ROWS: RoundRow[] = __ROWS__;

const SUMMARY = __SUMMARY__;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(5, 10);
  return `${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function avg(nums: number[]): number {
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function binGenomic(filtered: RoundRow[], chrom: string, bins = 12) {
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

export default function RoundsHistoryDashboard() {
  const theme = useHostTheme();
  const muted = { color: theme.text.muted, fontSize: 12 };
  const [chrom, setChrom] = useCanvasState<string>("chrom", "all");
  const [instance, setInstance] = useCanvasState<string>("instance", "all");

  const filtered = ROWS.filter((r) => {
    if (chrom !== "all" && r.chrom !== chrom) return false;
    if (instance !== "all" && r.instance !== instance) return false;
    return true;
  });

  const roundOrder = Array.from(new Set(filtered.map((r) => r.round_id))).sort();
  const timeLabels = roundOrder.map(fmtDate);
  const scoreByRound = roundOrder.map((id) => {
    const pts = filtered.filter((r) => r.round_id === id).map((r) => r.score_100);
    return Math.round(avg(pts) * 100) / 100;
  });
  const rankByRound = roundOrder.map((id) => {
    const pts = filtered.filter((r) => r.round_id === id).map((r) => r.rank);
    return Math.min(...pts);
  });
  const gapByRound = roundOrder.map((id) => {
    const pts = filtered.filter((r) => r.round_id === id).map((r) => r.gap_to_leader);
    return Math.round(avg(pts) * 10) / 10;
  });

  const uniqueChromRounds: Record<string, Set<string>> = {};
  for (const r of filtered) {
    (uniqueChromRounds[r.chrom] ||= new Set()).add(r.round_id);
  }
  const pieData = Object.entries(uniqueChromRounds).map(([label, set]) => ({
    label,
    value: set.size,
  }));

  const chromAvg = SUMMARY.chroms.map((c) => {
    const pts = filtered.filter((r) => r.chrom === c).map((r) => r.score_100);
    return Math.round(avg(pts) * 100) / 100;
  });

  const breakdownChrom = SUMMARY.chroms[0] || "chr21";
  const breakdownRows = filtered.filter((r) => r.chrom === (chrom === "all" ? breakdownChrom : chrom));
  const breakdownCats = ["Core F1", "Completeness", "FP rate", "Quality"];
  const breakdownSeries = [
    {
      name: "Avg contribution (pts)",
      data: [
        Math.round(avg(breakdownRows.map((r) => r.core ?? 0)) * 100) / 100,
        Math.round(avg(breakdownRows.map((r) => r.completeness ?? 0)) * 100) / 100,
        Math.round(avg(breakdownRows.map((r) => r.fp ?? 0)) * 100) / 100,
        Math.round(avg(breakdownRows.map((r) => r.quality ?? 0)) * 100) / 100,
      ],
    },
  ];

  const genomicChrom = chrom === "all" ? "chr21" : chrom;
  const genomic = binGenomic(filtered, genomicChrom);

  const instanceSeries = SUMMARY.instances
    .filter((id) => instance === "all" || id === instance)
    .map((id) => ({
      name: id,
      data: roundOrder.map((rid) => {
        const hit = filtered.find((r) => r.round_id === rid && r.instance === id);
        return hit ? hit.score_100 : 0;
      }),
    }))
    .filter((s) => s.data.some((v) => v > 0));

  const tableRows = [...filtered]
    .sort((a, b) => (a.round_id < b.round_id ? 1 : -1))
    .slice(0, 30)
    .map((r) => [
      fmtDate(r.round_id),
      r.chrom,
      r.region.split(":")[1] || r.region,
      r.instance,
      r.score_100.toFixed(2),
      String(r.rank),
      r.gap_to_leader.toFixed(1),
      r.f1_snp.toFixed(3),
      r.f1_indel.toFixed(3),
      `${r.runtime_s}s`,
    ]);

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
      <Stack gap={6}>
        <H1>Minos round history</H1>
        <Text style={{ ...muted }}>
          Source: rounds.json · {SUMMARY.date_min.slice(0, 10)} to {SUMMARY.date_max.slice(0, 10)} ·
          {SUMMARY.rounds} rounds · {SUMMARY.rows} instance scores
        </Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat label="Rounds" value={String(SUMMARY.rounds)} />
        <Stat label="Avg score (0–100)" value={String(SUMMARY.avg_score)} tone="info" />
        <Stat label="Best score" value={String(SUMMARY.best_score)} tone="success" />
        <Stat label="Filtered rows" value={String(filtered.length)} />
      </Grid>

      <Card>
        <CardHeader title="Filters" />
        <CardBody>
          <Row gap={16} wrap>
            <Select
              label="Chromosome"
              value={chrom}
              onChange={setChrom}
              options={[
                { label: "All chromosomes", value: "all" },
                ...SUMMARY.chroms.map((c) => ({ label: c, value: c })),
              ]}
            />
            <Select
              label="Instance"
              value={instance}
              onChange={setInstance}
              options={[
                { label: "All instances", value: "all" },
                ...SUMMARY.instances.map((c) => ({ label: c, value: c })),
              ]}
            />
          </Row>
        </CardBody>
      </Card>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader title="Score over time (avg per round)" />
          <CardBody>
            <Text style={{ ...muted, marginBottom: 8 }}>Y-axis: score_100 (0–100) · X-axis: round date (UTC)</Text>
            <LineChart
              categories={timeLabels}
              series={[{ name: "Avg score", data: scoreByRound, tone: "info" }]}
              height={220}
              beginAtZero={false}
              yMin={50}
              yMax={100}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Rank and gap to leader" />
          <CardBody>
            <Text style={{ ...muted, marginBottom: 8 }}>Lower rank is better · gap = points below round leader</Text>
            <LineChart
              categories={timeLabels}
              series={[
                { name: "Best rank", data: rankByRound, tone: "warning" },
                { name: "Gap to leader", data: gapByRound, tone: "danger" },
              ]}
              height={220}
              beginAtZero={false}
            />
          </CardBody>
        </Card>
      </Grid>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader title="Score by instance (per round)" />
          <CardBody>
            <Text style={{ ...muted, marginBottom: 8 }}>Y-axis: score_100 · one line per GATK hotkey</Text>
            <LineChart categories={timeLabels} series={instanceSeries} height={220} beginAtZero={false} yMin={50} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Rounds by chromosome" />
          <CardBody>
            <Row gap={24} align="center">
              <PieChart data={pieData} donut size={180} />
              <Stack gap={8}>
                <H3>Avg score by chromosome</H3>
                <BarChart
                  categories={SUMMARY.chroms}
                  series={[{ name: "Avg score_100", data: chromAvg, tone: "success" }]}
                  height={140}
                  horizontal
                  showValues
                />
              </Stack>
            </Row>
          </CardBody>
        </Card>
      </Grid>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader title={`Genomic position vs score (${genomicChrom})`} />
          <CardBody>
            <Text style={{ ...muted, marginBottom: 8 }}>
              X-axis: window start (Mb) · Y-axis: mean score_100 in bin
            </Text>
            <BarChart
              categories={genomic.categories}
              series={[{ name: "Mean score", data: genomic.scores, tone: "info" }]}
              height={200}
              showValues={genomic.categories.length <= 12}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={`Score breakdown (${chrom === "all" ? breakdownChrom : chrom} avg)`} />
          <CardBody>
            <Text style={{ ...muted, marginBottom: 8 }}>Y-axis: average contribution points from AdvancedScorer</Text>
            <BarChart categories={breakdownCats} series={breakdownSeries} height={200} showValues />
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={8}>
        <H2>Recent rounds (top 30)</H2>
        <Text style={muted}>Sorted by date descending · filtered by chromosome and instance above</Text>
        <Table
          headers={["Date", "Chr", "Window", "Instance", "Score", "Rank", "Gap", "F1 SNP", "F1 indel", "Runtime"]}
          rows={tableRows}
          striped
          stickyHeader
          columnAlign={["left", "left", "left", "left", "right", "right", "right", "right", "right", "right"]}
        />
      </Stack>
    </Stack>
  );
}
