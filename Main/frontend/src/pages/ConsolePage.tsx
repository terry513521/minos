import { useCallback, useEffect, useRef, useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { ConfCheckPanel } from "../components/ConfCheckPanel";
import { AutoModePanel } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkerStatusOverview } from "../components/WorkerStatusOverview";
import { WorkersPanel } from "../components/WorkersPanel";
import { useAutoModeEnabled } from "../hooks/useAutoModeEnabled";
import { WorkerAssignmentSummary } from "../types/workerAssignment";
import { WorkerLiveStatus } from "../utils/workerLiveStatus";
import { ApplyConfImportResult } from "../utils/workerConfImport";
import { loadCandidateFinderState } from "../utils/candidateFinderStorage";
import { ensureWorkerTunablesHydrated } from "../utils/workerTunableStorage";

const initialFinderState = loadCandidateFinderState();

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);
  const [finderRegion, setFinderRegion] = useState(
    () => initialFinderState?.region ?? "chr20:10000000-15000000",
  );
  const [workerAssignmentSummaries, setWorkerAssignmentSummaries] = useState<
    WorkerAssignmentSummary[]
  >([]);
  const [workerLiveStatuses, setWorkerLiveStatuses] = useState<WorkerLiveStatus[]>([]);
  const autoModeEnabled = useAutoModeEnabled();
  const assignCandidateRef = useRef<
    ((workerId: string, candidateIndex: number) => boolean) | null
  >(null);
  const applyConfImportRef = useRef<
    ((text: string, candidateIndex: number) => Promise<ApplyConfImportResult>) | null
  >(null);

  const handleWorkerAssignmentSummariesChange = useCallback(
    (summaries: WorkerAssignmentSummary[]) => {
      setWorkerAssignmentSummaries(summaries);
    },
    [],
  );

  const handleWorkerLiveStatusesChange = useCallback((statuses: WorkerLiveStatus[]) => {
    setWorkerLiveStatuses(statuses);
  }, []);

  const handleAssignHandlerReady = useCallback(
    (handler: (workerId: string, candidateIndex: number) => boolean) => {
      assignCandidateRef.current = handler;
    },
    [],
  );

  const handleApplyConfHandlerReady = useCallback(
    (handler: (text: string, candidateIndex: number) => Promise<ApplyConfImportResult>) => {
      applyConfImportRef.current = handler;
    },
    [],
  );

  const handleAssignCandidateToWorker = useCallback(
    (workerId: string, candidateIndex: number) =>
      assignCandidateRef.current?.(workerId, candidateIndex) ?? false,
    [],
  );

  const handleApplyConfToAllWorkers = useCallback(async (text: string, candidateIndex: number) => {
    return (
      (await applyConfImportRef.current?.(text, candidateIndex)) ?? {
        ok: false,
        message: "Workers panel is not ready yet.",
        applied: 0,
        skipped: 0,
      }
    );
  }, []);

  useEffect(() => {
    void ensureWorkerTunablesHydrated();
  }, []);

  useEffect(() => {
    if (!autoModeEnabled) return;
    if (window.location.hash === "#candidates" || !window.location.hash) {
      window.location.hash = "#auto";
    }
  }, [autoModeEnabled]);

  return (
    <div className="console-page">
      <WorkerStatusOverview statuses={workerLiveStatuses} />
      <div className="bento-grid">
        {autoModeEnabled ? (
          <section id="auto" className="panel">
            <SectionHeader
              step={1}
              title="Auto mode"
              lead="Overnight orchestration for registered workers. Workers run after POST /api/v1/auto/start."
            />
            <AutoModePanel embedded />
          </section>
        ) : (
          <section id="candidates" className="panel">
            <SectionHeader
              step={1}
              title="Find base candidates"
              lead="Select a candidate, then click a worker to assign its base conf and region."
            />
            <CandidateFinderPanel
              onResultChange={setCandidateContext}
              onRegionChange={setFinderRegion}
              workerAssignmentSummaries={workerAssignmentSummaries}
              onAssignCandidateToWorker={handleAssignCandidateToWorker}
              onApplyConfToAllWorkers={handleApplyConfToAllWorkers}
              embedded
            />
            <ConfCheckPanel finderRegion={finderRegion} />
          </section>
        )}

        <section id="workers" className="panel">
          <SectionHeader
            step={2}
            title="Workers"
            lead={
              autoModeEnabled
                ? "Live scores and controls for registered workers during auto runs."
                : "Assigned base conf appears here — tune params and dispatch optimization."
            }
          />
          <WorkersPanel
            candidateContext={candidateContext}
            finderRegion={finderRegion}
            onWorkerAssignmentSummariesChange={handleWorkerAssignmentSummariesChange}
            onWorkerLiveStatusesChange={handleWorkerLiveStatusesChange}
            onAssignHandlerReady={handleAssignHandlerReady}
            onApplyConfHandlerReady={handleApplyConfHandlerReady}
            sectionChild
          />
        </section>
      </div>
    </div>
  );
}
