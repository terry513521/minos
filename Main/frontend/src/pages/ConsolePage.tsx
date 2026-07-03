import { useCallback, useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { AutoModePanel } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";
import { WorkerAssignmentSummary } from "../types/workerAssignment";

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);
  const [workerAssignmentSummaries, setWorkerAssignmentSummaries] = useState<
    WorkerAssignmentSummary[]
  >([]);

  const handleWorkerAssignmentSummariesChange = useCallback(
    (summaries: WorkerAssignmentSummary[]) => {
      setWorkerAssignmentSummaries(summaries);
    },
    [],
  );

  return (
    <div className="console-page">
      <div className="bento-grid">
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
          <AutoModePanel />
          <WorkersPanel
            candidateContext={candidateContext}
            onWorkerAssignmentSummariesChange={handleWorkerAssignmentSummariesChange}
          />
        </section>
      </div>
    </div>
  );
}
