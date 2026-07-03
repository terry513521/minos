import { useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { AutoModePanel } from "../components/AutoModePanel";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";

export function ConsolePage() {
  const [candidateContext, setCandidateContext] = useState<FindCandidatesResponse | null>(null);

  return (
    <div className="console-page">
      <div className="bento-grid">
        <section id="candidates" className="panel">
          <SectionHeader
            step={1}
            title="Find base candidates"
            lead="Same tool → similar coordinates → best score from history."
          />
          <CandidateFinderPanel onResultChange={setCandidateContext} embedded />
          <AutoModePanel />
          <WorkersPanel candidateContext={candidateContext} />
        </section>
      </div>
    </div>
  );
}
