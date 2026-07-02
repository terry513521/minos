import {
  formatCountdown,
  formatCountdownVerbose,
  limitCountdownUrgency,
  useLimitCountdown,
} from "../hooks/useSubmissionCountdown";

interface LimitCountdownBadgeProps {
  startedAt: string | null | undefined;
  limitSeconds: number | null | undefined;
  active: boolean;
  className?: string;
}

export function LimitCountdownBadge({
  startedAt,
  limitSeconds,
  active,
  className = "",
}: LimitCountdownBadgeProps) {
  const remaining = useLimitCountdown(startedAt, limitSeconds, active);
  if (!active || remaining == null || !limitSeconds) return null;

  const urgency = limitCountdownUrgency(remaining, limitSeconds);
  const label = remaining <= 0 ? "Time limit reached" : `${formatCountdown(remaining)} left`;

  return (
    <span
      className={`limit-countdown-badge urgency-${urgency}${className ? ` ${className}` : ""}`}
      title={formatCountdownVerbose(remaining)}
    >
      {label}
    </span>
  );
}
