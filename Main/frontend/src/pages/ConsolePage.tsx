import { useCallback, useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { AutoModePanel } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";
import { CandidateWorkerAssignment } from "../types/workerAssignment";

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);
  const [assignmentsByCandidate, setAssignmentsByCandidate] = useState<
    Record<number, CandidateWorkerAssignment[]>
  >({});

  const handleAssignmentsByCandidateChange = useCallback(
    (index: Record<number, CandidateWorkerAssignment[]>) => {
      setAssignmentsByCandidate(index);
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
            assignmentsByCandidate={assignmentsByCandidate}
            embedded
          />
          <AutoModePanel />
          <WorkersPanel
            candidateContext={candidateContext}
            onAssignmentsByCandidateChange={handleAssignmentsByCandidateChange}
          />
        </section>
      </div>
    </div>
  );
}
