import { DragEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, CandidatePreview, FindCandidatesResponse } from "../api/client";
import { CANDIDATE_DRAG_MIME } from "../utils/candidateAssign";
import { compositeCandidateScore } from "../utils/candidateSelection";
import {
  clampKCandidates,
  DEFAULT_K_CANDIDATES,
  loadCandidateFinderState,
  saveCandidateFinderState,
} from "../utils/candidateFinderStorage";
import { normalizeRegion, chromosomeFromWindow } from "../utils/window";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";
import { ConfTooltip } from "./ConfTooltip";
import { DeferredNumberInput } from "./DeferredNumberInput";

const DEFAULT_REGION = "chr20:10000000-15000000";

const initialFinderState = loadCandidateFinderState();

interface CandidateFinderPanelProps {
  onResultChange?: (result: FindCandidatesResponse | null) => void;
  embedded?: boolean;
}

export function CandidateFinderPanel({
  onResultChange,
  embedded = false,
}: CandidateFinderPanelProps) {
  const regionInitializedRef = useRef(false);
  const restoredResultRef = useRef(initialFinderState?.result ?? null);
  const [region, setRegion] = useState(
    () => initialFinderState?.region || DEFAULT_REGION,
  );
  const [kCandidates, setKCandidates] = useState(() =>
    clampKCandidates(initialFinderState?.kCandidates ?? DEFAULT_K_CANDIDATES),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FindCandidatesResponse | null>(
    () => initialFinderState?.result ?? null,
  );
  const [autoModeEnabled, setAutoModeEnabled] = useState(false);

  const refreshAutoMode = useCallback(() => {
    api
      .getAutoMode()
      .then((status) => setAutoModeEnabled(status.enabled))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshAutoMode();
    function onAutoChanged() {
      refreshAutoMode();
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
    return () => window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
  }, [refreshAutoMode]);

  useEffect(() => {
    saveCandidateFinderState({ region, kCandidates, result });
  }, [region, kCandidates, result]);

  useEffect(() => {
    if (!regionInitializedRef.current) {
      regionInitializedRef.current = true;
      const restored = restoredResultRef.current;
      if (restored) {
        onResultChange?.(restored);
      } else {
        onResultChange?.(null);
      }
      return;
    }

    setResult(null);
    setError(null);
    onResultChange?.(null);
  }, [region, onResultChange]);

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
      onResultChange?.(data);
    } catch (err) {
      setResult(null);
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
            disabled={autoModeEnabled}
          />
        </label>
        <label className="candidate-k-field">
          <span className="candidate-k-label">Candidates</span>
          <DeferredNumberInput
            className="candidate-k-input"
            value={kCandidates}
            min={1}
            max={16}
            step={1}
            onCommit={(value) => setKCandidates(clampKCandidates(value))}
            aria-label="Number of candidates"
            disabled={autoModeEnabled}
          />
        </label>
        <button
          type="submit"
          className="button primary candidate-find-btn"
          disabled={loading || !region.trim() || autoModeEnabled}
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
            {result.used_default && (
              <span className="chip chip-warn">no similar window — default conf</span>
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
  const chrom = chromosomeFromWindow(candidate.source_window) ?? fallbackChrom;
  const score = candidate.history_score ?? candidate.rank_score;
  const composite = compositeCandidateScore(candidate);
  const region = candidate.source_window?.trim();

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
      {region ? (
        <code className="candidate-result-window">{region}</code>
      ) : (
        <span className="candidate-result-window-missing">No history region</span>
      )}
      <div className="candidate-result-foot">
        <span className="candidate-rank-badge">#{candidate.index + 1}</span>
        {candidate.similarity != null && (
          <span className="candidate-sim-tag">sim {candidate.similarity.toFixed(2)}</span>
        )}
        <span className="candidate-composite-tag">
          composite {(composite * 100).toFixed(1)}%
        </span>
        <ConfTooltip conf={candidate.base_conf} label="Conf" />
      </div>
    </article>
  );
}
