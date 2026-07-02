import { useState } from "react";
import { FindCandidatesResponse } from "../api/client";
import { CandidateFinderPanel } from "../components/CandidateFinderPanel";
import { HistorySidebar } from "../components/HistorySidebar";
import { SectionHeader } from "../components/SectionHeader";
import { WorkersPanel } from "../components/WorkersPanel";

export function ConsolePage() {
  const [historyChrom, setHistoryChrom] = useState<string | null>(null);
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
          <CandidateFinderPanel
            onChromosomeChange={setHistoryChrom}
            onResultChange={setCandidateContext}
            embedded
          />
          <WorkersPanel candidateContext={candidateContext} />
        </section>

        <section id="history" className="panel">
          <SectionHeader
            step={2}
            title="History"
            lead={historyChrom ? `Filtered to ${historyChrom}` : "Past window · conf · score records"}
          />
          <HistorySidebar chromosomeFilter={historyChrom} embedded />
        </section>
      </div>
    </div>
  );
}
