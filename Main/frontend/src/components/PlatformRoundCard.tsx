import { PlatformRound } from "../api/client";
import { CircularCountdownClock, ROUND_TOTAL_SECONDS } from "./CircularCountdownClock";
import {
  countdownUrgency,
  formatCountdownVerbose,
  formatLocalDateTime,
  useSubmissionCountdown,
} from "../hooks/useSubmissionCountdown";

const MIN_SUBMIT_SECONDS = 600;

interface PlatformRoundCardProps {
  round: PlatformRound | null;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void | Promise<void>;
}

export function PlatformRoundCard({
  round,
  loading = false,
  error = null,
  onRefresh,
}: PlatformRoundCardProps) {
  const showCountdown =
    round?.has_active_round &&
    round.time_remaining_seconds != null &&
    (round.status === "open" || round.status === "scoring" || round.status === "pending");

  const remaining = useSubmissionCountdown(
    round?.time_remaining_seconds,
    round?.polled_at,
    Boolean(showCountdown),
  );

  const urgency =
    round?.status === "open" && round.has_active_round
      ? countdownUrgency(remaining, MIN_SUBMIT_SECONDS)
      : (remaining ?? 0) === 0
        ? "ended"
        : "ok";

  return (
    <section className={`round-hero urgency-${urgency}`}>
      <div className="round-hero-glow" aria-hidden />

      <div className="round-hero-top">
        <div className="round-hero-main">
          <div className="round-hero-eyebrow">Platform round</div>
          {loading && !round ? (
            <h2 className="round-hero-window muted">Polling platform…</h2>
          ) : (
            <h2 className="round-hero-window">
              {round?.region ? <code>{round.region}</code> : "No active window"}
            </h2>
          )}
          {round && (
            <div className="chip-row">
              <span className={`badge ${round.status ?? "offline"}`}>{round.status ?? "—"}</span>
              <span className="chip">{round.demo_mode ? "demo" : "live"}</span>
              {round.chromosome && (
                <span className="chip chip-accent">{round.chromosome}</span>
              )}
              {round.num_mutations != null && (
                <span className="chip chip-muted">{round.num_mutations} mutations</span>
              )}
              {round.downsampled_coverage != null && (
                <span className="chip chip-muted">{round.downsampled_coverage}x cov</span>
              )}
            </div>
          )}
        </div>

        {showCountdown && round && (
          <div
            className={`round-hero-clock urgency-${urgency}`}
            title={formatCountdownVerbose(remaining)}
          >
            <CircularCountdownClock
              size="compact"
              remainingSeconds={remaining}
              totalSeconds={ROUND_TOTAL_SECONDS}
              urgency={urgency}
            />
          </div>
        )}
      </div>

      {error && <div className="alert warn">{error}</div>}

      <div className="round-hero-actions">
        <button type="button" className="button ghost" onClick={() => void onRefresh?.()}>
          Refresh round
        </button>
      </div>

      {round && (
        <div className="round-hero-meta-panel">
          <h3 className="round-hero-meta-title">Round metadata</h3>
          <dl className="meta-grid round-hero-meta-grid">
            <dt>Region</dt>
            <dd><code>{round.region ?? "—"}</code></dd>
            <dt>Chromosome</dt>
            <dd>{round.chromosome ?? "—"}</dd>
            <dt>Active</dt>
            <dd>{round.has_active_round ? "yes" : "no"}</dd>
            <dt>Status</dt>
            <dd>{round.status ?? "—"}</dd>
            <dt>Mode</dt>
            <dd>{round.demo_mode ? "demo" : "live"}</dd>
            <dt>Started</dt>
            <dd>{formatLocalDateTime(round.start_time)}</dd>
            <dt>Submission closes</dt>
            <dd>{formatLocalDateTime(round.submission_end_time)}</dd>
            <dt>Scoring ends</dt>
            <dd>{formatLocalDateTime(round.scoring_end_time)}</dd>
            <dt>Optimize by</dt>
            <dd>{formatLocalDateTime(round.optimize_deadline_at)}</dd>
            <dt>Last polled</dt>
            <dd>{formatLocalDateTime(round.polled_at)}</dd>
            <dt>Round ID</dt>
            <dd><code className="round-id-code">{round.round_id ?? "—"}</code></dd>
            <dt>Mutations</dt>
            <dd>{round.num_mutations ?? "—"}</dd>
            <dt>Coverage</dt>
            <dd>{round.downsampled_coverage != null ? `${round.downsampled_coverage}x` : "—"}</dd>
            <dt>Submitted</dt>
            <dd>{round.has_submitted ? "yes" : "no"}</dd>
          </dl>
        </div>
      )}
    </section>
  );
}
