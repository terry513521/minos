import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { api, CandidatePreview, FindCandidatesResponse } from "../api/client";
import { CANDIDATE_DRAG_MIME } from "../utils/candidateAssign";
import {
  loadCandidateFinderState,
  saveCandidateFinderState,
} from "../utils/candidateFinderStorage";
import { chromosomeFromWindow, normalizeRegion } from "../utils/window";
import { ConfTooltip } from "./ConfTooltip";

const K_OPTIONS = [1, 2, 3, 4, 5, 6, 8];
const DEFAULT_REGION = "chr20:10000000-15000000";

const initialFinderState = loadCandidateFinderState();

interface CandidateFinderPanelProps {
  onChromosomeChange?: (chromosome: string | null) => void;
  onResultChange?: (result: FindCandidatesResponse | null) => void;
  embedded?: boolean;
}

export function CandidateFinderPanel({
  onChromosomeChange,
  onResultChange,
  embedded = false,
}: CandidateFinderPanelProps) {
  const regionInitializedRef = useRef(false);
  const restoredResultRef = useRef(initialFinderState?.result ?? null);
  const [region, setRegion] = useState(
    () => initialFinderState?.region || DEFAULT_REGION,
  );
  const [kCandidates, setKCandidates] = useState(
    () => initialFinderState?.kCandidates ?? 2,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FindCandidatesResponse | null>(
    () => initialFinderState?.result ?? null,
  );

  const previewChrom = chromosomeFromWindow(region);

  useEffect(() => {
    saveCandidateFinderState({ region, kCandidates, result });
  }, [region, kCandidates, result]);

  useEffect(() => {
    if (!regionInitializedRef.current) {
      regionInitializedRef.current = true;
      const restored = restoredResultRef.current;
      if (restored) {
        onChromosomeChange?.(restored.chromosome);
        onResultChange?.(restored);
      } else {
        onChromosomeChange?.(previewChrom);
        onResultChange?.(null);
      }
      return;
    }

    setResult(null);
    setError(null);
    onChromosomeChange?.(previewChrom);
    onResultChange?.(null);
  }, [region, previewChrom, onChromosomeChange, onResultChange]);

  async function handleFind(e: FormEvent) {
    e.preventDefault();
    const window = normalizeRegion(region) ?? region.trim();
    if (!window) return;

    setError(null);
    setLoading(true);
    try {
      const data = await api.findCandidates({
        window,
        k_candidates: kCandidates,
      });
      setResult(data);
      onChromosomeChange?.(data.chromosome);
      onResultChange?.(data);
    } catch (err) {
      setResult(null);
      onChromosomeChange?.(null);
      onResultChange?.(null);
      setError(err instanceof Error ? err.message : "Failed to find candidates");
    } finally {
      setLoading(false);
    }
  }

  const body = (
    <>
      <form className="candidate-finder-bar" onSubmit={handleFind}>
        <label className="candidate-region-field">
          <span className="candidate-region-label">Region</span>
          <input
            className="input-mono candidate-region-input"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder={DEFAULT_REGION}
            aria-label="Genomic region"
            spellCheck={false}
          />
        </label>
        <label className="candidate-k-select">
          <span className="sr-only">Number of candidates</span>
          <select
            value={kCandidates}
            onChange={(e) => setKCandidates(Number(e.target.value))}
            aria-label="Candidates count"
          >
            {K_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="button primary candidate-find-btn"
          disabled={loading || !region.trim()}
        >
          {loading ? "Finding…" : `Find ${kCandidates} candidates`}
        </button>
      </form>

      {error && <div className="alert error">{error}</div>}

      {result && (
        <div className="candidate-results">
            <div className="candidate-results-summary">
            <span className="chip chip-accent">{result.tool}</span>
            <span className="chip">
              {result.coordinate_matched} similar on {result.chromosome}
            </span>
            {result.total_history === 0 && (
              <span className="chip chip-warn">no history in database</span>
            )}
            {result.used_default && result.total_history > 0 && (
              <span className="chip chip-warn">no similar window — default conf</span>
            )}
            {result.used_default && result.total_history === 0 && (
              <span className="chip chip-warn">default conf — import history first</span>
            )}
          </div>
          <div className="candidate-card-grid">
            {result.candidates.map((c) => (
              <CandidateCard
                key={c.index}
                candidate={c}
                fallbackChrom={result.chromosome}
                draggable
              />
            ))}
          </div>
        </div>
      )}
    </>
  );

  if (embedded) return <div className="candidate-finder embedded">{body}</div>;

  return (
    <section className="panel candidate-finder">
      <h2>Find base candidates</h2>
      {body}
    </section>
  );
}

function CandidateCard({
  candidate,
  fallbackChrom,
  draggable = false,
}: {
  candidate: CandidatePreview;
  fallbackChrom: string;
  draggable?: boolean;
}) {
  const chrom =
    chromosomeFromWindow(candidate.source_window) ?? fallbackChrom;
  const score = candidate.history_score ?? candidate.rank_score;

  function handleDragStart(e: DragEvent<HTMLElement>) {
    if (!draggable) return;
    e.dataTransfer.setData(
      CANDIDATE_DRAG_MIME,
      JSON.stringify({ index: candidate.index }),
    );
    e.dataTransfer.effectAllowed = "copy";
  }

  return (
    <article
      className={`candidate-result-card${draggable ? " candidate-draggable" : ""}`}
      draggable={draggable}
      onDragStart={handleDragStart}
    >
      <div className="candidate-result-top">
        <span className="candidate-result-chrom">{chrom}</span>
        <span className="candidate-result-score">{(score * 100).toFixed(1)}%</span>
      </div>
      {candidate.source_window && (
        <code className="candidate-result-window">{candidate.source_window}</code>
      )}
      <div className="candidate-result-foot">
        <span className="candidate-rank-badge">#{candidate.index + 1}</span>
        {candidate.similarity != null && (
          <span className="candidate-sim-tag">sim {candidate.similarity.toFixed(2)}</span>
        )}
        <ConfTooltip conf={candidate.base_conf} label="Conf" />
      </div>
    </article>
  );
}
