import { useCallback, useEffect, useState } from "react";
import { api, FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { AutoModePanel, AUTO_MODE_CHANGED_EVENT } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";
import { loadAutoModeState } from "../utils/autoModeStorage";
import { WorkerAssignmentSummary } from "../types/workerAssignment";

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);
  const [workerAssignmentSummaries, setWorkerAssignmentSummaries] = useState<
    WorkerAssignmentSummary[]
  >([]);
  const [autoModeEnabled, setAutoModeEnabled] = useState(
    () => loadAutoModeState()?.status?.enabled ?? false,
  );

  const handleWorkerAssignmentSummariesChange = useCallback(
    (summaries: WorkerAssignmentSummary[]) => {
      setWorkerAssignmentSummaries(summaries);
    },
    [],
  );

  useEffect(() => {
    function refreshAutoMode() {
      api
        .getAutoMode()
        .then((status) => setAutoModeEnabled(status.enabled))
        .catch(() => {});
    }
    refreshAutoMode();
    window.addEventListener(AUTO_MODE_CHANGED_EVENT, refreshAutoMode);
    return () => window.removeEventListener(AUTO_MODE_CHANGED_EVENT, refreshAutoMode);
  }, []);

  return (
    <div className="console-page">
      <div className="bento-grid">
        {autoModeEnabled ? (
          <section id="auto" className="panel">
            <SectionHeader
              step={1}
              title="Auto mode"
              lead="Overnight orchestration for VM, Big, and Igno. Workers run after POST /api/v1/auto/start."
            />
            <AutoModePanel embedded />
          </section>
        ) : (
          <section id="candidates" className="panel">
            <SectionHeader
              step={1}
              title="Find base candidates"
              lead="Same tool → similar coordinates → best score from history."
            />
            <CandidateFinderPanel
              onResultChange={setCandidateContext}
              workerAssignmentSummaries={workerAssignmentSummaries}
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
                ? "Live scores and controls for VM, Big, and Igno during auto runs."
                : "Drag a candidate card onto a worker to assign base conf and tune params."
            }
          />
          <WorkersPanel
            candidateContext={candidateContext}
            onWorkerAssignmentSummariesChange={handleWorkerAssignmentSummariesChange}
            sectionChild
          />
        </section>
      </div>
    </div>
  );
}
