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
import { loadAutoModeState } from "../utils/autoModeStorage";
import { ConfTooltip } from "./ConfTooltip";
import { DeferredNumberInput } from "./DeferredNumberInput";
import { WorkerAssignmentSummary } from "../types/workerAssignment";

const DEFAULT_REGION = "chr20:10000000-15000000";

const initialFinderState = loadCandidateFinderState();

interface CandidateFinderPanelProps {
  onResultChange?: (result: FindCandidatesResponse | null) => void;
  workerAssignmentSummaries?: WorkerAssignmentSummary[];
  onAssignCandidateToWorker?: (workerId: string, candidateIndex: number) => boolean;
  embedded?: boolean;
}

export function CandidateFinderPanel({
  onResultChange,
  workerAssignmentSummaries = [],
  onAssignCandidateToWorker,
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
  const [autoModeEnabled, setAutoModeEnabled] = useState(
    () => loadAutoModeState()?.status?.enabled ?? false,
  );
  const [selectedCandidateIndex, setSelectedCandidateIndex] = useState<number | null>(null);
  const [assignMessage, setAssignMessage] = useState<string | null>(null);

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
    setSelectedCandidateIndex(null);
    setAssignMessage(null);
    onResultChange?.(null);
  }, [region, onResultChange]);

  useEffect(() => {
    if (!result) {
      setSelectedCandidateIndex(null);
      return;
    }
    if (
      selectedCandidateIndex != null &&
      !result.candidates.some((candidate) => candidate.index === selectedCandidateIndex)
    ) {
      setSelectedCandidateIndex(null);
    }
  }, [result, selectedCandidateIndex]);

  useEffect(() => {
    if (!assignMessage) return;
    const timerId = window.setTimeout(() => setAssignMessage(null), 2400);
    return () => window.clearTimeout(timerId);
  }, [assignMessage]);

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
      setSelectedCandidateIndex(null);
      setAssignMessage(null);
      onResultChange?.(data);
    } catch (err) {
      setResult(null);
      onResultChange?.(null);
      setError(err instanceof Error ? err.message : "Failed to find candidates");
    } finally {
      setLoading(false);
    }
  }

  function handleSelectCandidate(index: number) {
    setAssignMessage(null);
    setSelectedCandidateIndex((current) => (current === index ? null : index));
  }

  function handleAssignWorker(workerId: string, workerName: string) {
    if (selectedCandidateIndex == null || !onAssignCandidateToWorker) return;
    const slot = workerAssignmentSummaries.find((item) => item.workerId === workerId);
    if (slot?.reassignmentLocked) {
      setAssignMessage(`Cannot assign to ${workerName} — optimization is running.`);
      return;
    }
    const ok = onAssignCandidateToWorker(workerId, selectedCandidateIndex);
    if (ok) {
      setAssignMessage(`Assigned candidate #${selectedCandidateIndex + 1} to ${workerName}.`);
    }
  }

  const selectedCandidate =
    selectedCandidateIndex != null
      ? result?.candidates.find((candidate) => candidate.index === selectedCandidateIndex) ?? null
      : null;

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
                selected={selectedCandidateIndex === c.index}
                onSelect={() => handleSelectCandidate(c.index)}
                draggable
              />
            ))}
          </div>

          {selectedCandidate && (
            <CandidateWorkerAssignPanel
              candidate={selectedCandidate}
              workerSlots={workerAssignmentSummaries}
              assignMessage={assignMessage}
              onAssign={handleAssignWorker}
            />
          )}
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
  selected,
  onSelect,
  draggable = false,
}: {
  candidate: CandidatePreview;
  fallbackChrom: string;
  selected: boolean;
  onSelect: () => void;
  draggable?: boolean;
}) {
  const draggedRef = useRef(false);
  const chrom = chromosomeFromWindow(candidate.source_window) ?? fallbackChrom;
  const score = candidate.history_score ?? candidate.rank_score;
  const composite = compositeCandidateScore(candidate);
  const region = candidate.source_window?.trim();

  function handleDragStart(e: DragEvent<HTMLElement>) {
    if (!draggable) return;
    draggedRef.current = true;
    e.dataTransfer.setData(
      CANDIDATE_DRAG_MIME,
      JSON.stringify({ index: candidate.index }),
    );
    e.dataTransfer.effectAllowed = "copy";
  }

  function handleCardClick() {
    if (draggedRef.current) {
      draggedRef.current = false;
      return;
    }
    onSelect();
  }

  return (
    <article
      className={`candidate-result-card${draggable ? " candidate-draggable" : ""}${selected ? " candidate-result-card--selected" : ""}`}
      draggable={draggable}
      onDragStart={handleDragStart}
      onClick={handleCardClick}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`Candidate #${candidate.index + 1}${region ? `, ${region}` : ""}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
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
      <div className="candidate-result-foot" onClick={(e) => e.stopPropagation()}>
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

function CandidateWorkerAssignPanel({
  candidate,
  workerSlots,
  assignMessage,
  onAssign,
}: {
  candidate: CandidatePreview;
  workerSlots: WorkerAssignmentSummary[];
  assignMessage: string | null;
  onAssign: (workerId: string, workerName: string) => void;
}) {
  const region = candidate.source_window?.trim();

  return (
    <section className="candidate-worker-assign-panel" aria-label="Assign candidate to worker">
      <div className="candidate-worker-assign-head">
        <div>
          <span className="candidate-worker-assign-title">
            Assign candidate #{candidate.index + 1}
          </span>
          {region ? (
            <code className="candidate-worker-assign-region">{region}</code>
          ) : (
            <span className="candidate-worker-assign-region-missing">No history region</span>
          )}
        </div>
        <span className="candidate-worker-assign-hint">Click a worker to assign this base conf.</span>
      </div>

      {assignMessage && <div className="alert ok candidate-worker-assign-message">{assignMessage}</div>}

      {workerSlots.length > 0 ? (
        <ul className="candidate-worker-assign-list">
          {workerSlots.map((slot) => {
            const assignedHere = slot.candidateIndex === candidate.index;
            const assignedElsewhere =
              slot.candidateIndex != null && slot.candidateIndex !== candidate.index;
            const locked = slot.reassignmentLocked;
            return (
              <li key={slot.workerId}>
                <button
                  type="button"
                  disabled={locked}
                  className={`candidate-worker-assign-btn${assignedHere ? " candidate-worker-assign-btn--here" : ""}${locked ? " candidate-worker-assign-btn--locked" : ""}`}
                  onClick={() => onAssign(slot.workerId, slot.workerName)}
                  title={
                    locked ? "Optimization running — cannot assign candidates" : undefined
                  }
                >
                  <span className="candidate-worker-assign-btn-name">{slot.workerName}</span>
                  <span className="candidate-worker-assign-btn-status">
                    {assignedHere && <span className="chip chip-ok">this candidate</span>}
                    {assignedElsewhere && (
                      <span className="chip chip-muted">#{slot.candidateIndex! + 1}</span>
                    )}
                    {!assignedHere && !assignedElsewhere && !locked && (
                      <span className="candidate-assignment-slot-empty">unassigned</span>
                    )}
                    {locked && <span className="chip chip-muted">locked</span>}
                    {slot.autoManaged && assignedHere && (
                      <span className="chip chip-muted">auto</span>
                    )}
                  </span>
                  {!locked && (
                    <span className="candidate-worker-assign-btn-action">Assign</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="candidate-assignment-popover-empty">No workers registered.</p>
      )}
    </section>
  );
}
