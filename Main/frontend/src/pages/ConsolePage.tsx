import { useCallback, useEffect, useRef, useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { AutoModePanel } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";
import { useAutoModeEnabled } from "../hooks/useAutoModeEnabled";
import { WorkerAssignmentSummary } from "../types/workerAssignment";

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);
  const [workerAssignmentSummaries, setWorkerAssignmentSummaries] = useState<
    WorkerAssignmentSummary[]
  >([]);
  const autoModeEnabled = useAutoModeEnabled();
  const assignCandidateRef = useRef<
    ((workerId: string, candidateIndex: number) => boolean) | null
  >(null);

  const handleWorkerAssignmentSummariesChange = useCallback(
    (summaries: WorkerAssignmentSummary[]) => {
      setWorkerAssignmentSummaries(summaries);
    },
    [],
  );

  const handleAssignHandlerReady = useCallback(
    (handler: (workerId: string, candidateIndex: number) => boolean) => {
      assignCandidateRef.current = handler;
    },
    [],
  );

  const handleAssignCandidateToWorker = useCallback(
    (workerId: string, candidateIndex: number) =>
      assignCandidateRef.current?.(workerId, candidateIndex) ?? false,
    [],
  );

  useEffect(() => {
    if (!autoModeEnabled) return;
    if (window.location.hash === "#candidates" || !window.location.hash) {
      window.location.hash = "#auto";
    }
  }, [autoModeEnabled]);

  return (
    <div className="console-page">
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
              lead="Select a candidate, then click a worker to assign its base conf."
            />
            <CandidateFinderPanel
              onResultChange={setCandidateContext}
              workerAssignmentSummaries={workerAssignmentSummaries}
              onAssignCandidateToWorker={handleAssignCandidateToWorker}
              embedded
            />
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
            onWorkerAssignmentSummariesChange={handleWorkerAssignmentSummariesChange}
            onAssignHandlerReady={handleAssignHandlerReady}
            sectionChild
          />
        </section>
      </div>
    </div>
  );
}
