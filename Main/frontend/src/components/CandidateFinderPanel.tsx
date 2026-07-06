import { DragEvent, FormEvent, MouseEvent, useEffect, useRef, useState } from "react";
import { api, CandidatePreview, FindCandidatesResponse } from "../api/client";
import { CANDIDATE_DRAG_MIME } from "../utils/candidateAssign";
import { compositeCandidateScore } from "../utils/candidateSelection";
import {
  clampKCandidates,
  DEFAULT_K_CANDIDATES,
  loadCandidateFinderState,
  normalizeFinderTool,
  saveCandidateFinderState,
} from "../utils/candidateFinderStorage";
import { ToolkitOption } from "../types/workerAssignment";
import { ToolBadge } from "./ToolBadge";
import { ToolSegmentPicker } from "./ToolSegmentPicker";
import { normalizeRegion, chromosomeFromWindow, analyzeBenchmarkWindow, formatWindowSpan } from "../utils/window";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";
import { loadAutoModeState } from "../utils/autoModeStorage";
import { getAutoModeSnapshot, subscribeAutoMode } from "../utils/autoModePoll";
import { ConfTooltip } from "./ConfTooltip";
import { DeferredNumberInput } from "./DeferredNumberInput";
import { WorkerAssignmentSummary } from "../types/workerAssignment";
import { ApplyConfImportResult } from "../utils/workerConfImport";
import { bestConfDownloadFileName, downloadConfFile } from "../utils/confDisplay";

const DEFAULT_REGION = "chr20:10000000-15000000";

const initialFinderState = loadCandidateFinderState();

interface CandidateFinderPanelProps {
  onResultChange?: (result: FindCandidatesResponse | null) => void;
  onRegionChange?: (region: string) => void;
  workerAssignmentSummaries?: WorkerAssignmentSummary[];
  onAssignCandidateToWorker?: (workerId: string, candidateIndex: number) => boolean;
  onApplyConfToAllWorkers?: (
    text: string,
    candidateIndex: number,
  ) => ApplyConfImportResult | Promise<ApplyConfImportResult>;
  embedded?: boolean;
}

export function CandidateFinderPanel({
  onResultChange,
  onRegionChange,
  workerAssignmentSummaries = [],
  onAssignCandidateToWorker,
  onApplyConfToAllWorkers,
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
  const [tool, setTool] = useState<ToolkitOption>(() =>
    normalizeFinderTool(initialFinderState?.tool),
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

  useEffect(() => {
    const snapshot = getAutoModeSnapshot();
    if (snapshot) {
      setAutoModeEnabled(snapshot.enabled);
    }
    function onAutoChanged() {
      const next = getAutoModeSnapshot();
      if (next) setAutoModeEnabled(next.enabled);
    }
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
    const unsubscribe = subscribeAutoMode((next) => {
      if (next) setAutoModeEnabled(next.enabled);
    });
    return () => {
      window.removeEventListener(AUTO_MODE_CHANGED_EVENT, onAutoChanged);
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    saveCandidateFinderState({ region, tool, kCandidates, result });
  }, [region, tool, kCandidates, result]);

  useEffect(() => {
    onRegionChange?.(region);
  }, [region, onRegionChange]);

  useEffect(() => {
    if (!regionInitializedRef.current) {
      regionInitializedRef.current = true;
      const restored = restoredResultRef.current;
      const normalizedRegion = normalizeRegion(region) ?? region.trim();
      if (restored) {
        const restoredWindow = normalizeRegion(restored.window) ?? restored.window?.trim();
        if (normalizedRegion && restoredWindow && normalizedRegion !== restoredWindow) {
          onResultChange?.(null);
        } else {
          onResultChange?.(restored);
        }
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
  }, [region, tool, onResultChange]);

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
        tool,
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

  const regionAnalysis = analyzeBenchmarkWindow(region);
  const regionSpanLabel = formatWindowSpan(regionAnalysis.window);

  const body = (
    <>
      <div className="candidate-finder-toolbar">
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
            {regionSpanLabel && (
              <span
                className={`candidate-region-size${regionAnalysis.isMinosRoundSize ? " candidate-region-size--ok" : " candidate-region-size--warn"}`}
              >
                {regionSpanLabel}
                {regionAnalysis.isMinosRoundSize ? " · 5 Mb round" : " · not 5 Mb"}
              </span>
            )}
          </label>
          <div className="candidate-tool-field">
            <span className="candidate-k-label">Tool</span>
            <ToolSegmentPicker
              value={tool}
              onChange={setTool}
              disabled={autoModeEnabled}
              aria-label="Variant caller for candidate search"
            />
          </div>
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
      </div>

      {error && <div className="alert error">{error}</div>}

      {result && (
        <div className="candidate-results">
          <div className="candidate-results-summary">
            <ToolBadge tool={result.tool} />
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
                tool={result.tool}
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
              onApplyConfFile={
                onApplyConfToAllWorkers
                  ? (text) => onApplyConfToAllWorkers(text, selectedCandidate.index)
                  : undefined
              }
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
  tool,
  fallbackChrom,
  selected,
  onSelect,
  draggable = false,
}: {
  candidate: CandidatePreview;
  tool: string;
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

  function handleDownloadConf(e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    const downloadName = bestConfDownloadFileName(
      region || `candidate-${candidate.index + 1}`,
      score,
    );
    downloadConfFile(candidate.base_conf, downloadName);
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
        <ToolBadge tool={tool} className="candidate-result-tool" />
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
        <button
          type="button"
          className="button ghost conf-tooltip-btn"
          onClick={handleDownloadConf}
          title="Download candidate base conf"
          aria-label={`Download candidate #${candidate.index + 1} base conf`}
        >
          Download
        </button>
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
  onApplyConfFile,
}: {
  candidate: CandidatePreview;
  workerSlots: WorkerAssignmentSummary[];
  assignMessage: string | null;
  onAssign: (workerId: string, workerName: string) => void;
  onApplyConfFile?: (text: string) => ApplyConfImportResult | Promise<ApplyConfImportResult>;
}) {
  const region = candidate.source_window?.trim();
  const importFileRef = useRef<HTMLInputElement>(null);
  const [confDropActive, setConfDropActive] = useState(false);
  const [confImportMessage, setConfImportMessage] = useState<string | null>(null);
  const [confImportError, setConfImportError] = useState<string | null>(null);

  useEffect(() => {
    if (!confImportMessage && !confImportError) return;
    const timerId = window.setTimeout(() => {
      setConfImportMessage(null);
      setConfImportError(null);
    }, 3200);
    return () => window.clearTimeout(timerId);
  }, [confImportMessage, confImportError]);

  async function applyConfText(text: string) {
    if (!onApplyConfFile) return;
    setConfImportMessage(null);
    setConfImportError(null);
    const result = await onApplyConfFile(text);
    if (result.ok) {
      setConfImportMessage(result.message);
    } else {
      setConfImportError(result.message);
    }
  }

  async function handleConfFile(file: File | null | undefined) {
    if (!file || !onApplyConfFile) return;
    try {
      const text = await file.text();
      await applyConfText(text);
    } catch (err) {
      setConfImportError(err instanceof Error ? err.message : "Failed to read conf file");
    }
  }

  function handleConfDragOver(e: DragEvent<HTMLDivElement>) {
    if (!onApplyConfFile) return;
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setConfDropActive(true);
  }

  function handleConfDragLeave() {
    setConfDropActive(false);
  }

  async function handleConfDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setConfDropActive(false);
    if (!onApplyConfFile) return;
    const file = e.dataTransfer.files?.[0];
    await handleConfFile(file);
  }

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
        <span className="candidate-worker-assign-hint">
          Click a worker to assign, or drop a conf file below to apply to all workers.
        </span>
      </div>

      {onApplyConfFile && (
        <div
          className={`candidate-worker-assign-dropzone${confDropActive ? " candidate-worker-assign-dropzone--active" : ""}`}
          onDragOver={handleConfDragOver}
          onDragLeave={handleConfDragLeave}
          onDrop={handleConfDrop}
          onClick={() => importFileRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              importFileRef.current?.click();
            }
          }}
        >
          <span className="candidate-worker-assign-dropzone-title">Drop conf file here</span>
          <span className="candidate-worker-assign-dropzone-hint">
            JSON tunable export or <code>.conf</code> — applies params, intervals, CPUs, trials, and
            time limits to every manual worker (skips auto mode).
          </span>
          <input
            ref={importFileRef}
            type="file"
            accept=".json,.conf,.txt,application/json,text/plain"
            className="sr-only"
            onChange={(e) => void handleConfFile(e.target.files?.[0])}
          />
        </div>
      )}

      {assignMessage && <div className="alert ok candidate-worker-assign-message">{assignMessage}</div>}
      {confImportMessage && (
        <div className="alert ok candidate-worker-assign-message">{confImportMessage}</div>
      )}
      {confImportError && <div className="alert error candidate-worker-assign-message">{confImportError}</div>}

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
