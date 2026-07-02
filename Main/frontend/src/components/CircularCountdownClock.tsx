import {
  CountdownUrgency,
  formatCountdown,
  formatCountdownVerbose,
  splitCountdown,
} from "../hooks/useSubmissionCountdown";

/** Minos platform round length (submission + scoring). */
export const ROUND_TOTAL_SECONDS = 72 * 60;

type ClockSize = "default" | "compact";

const GEOMETRY: Record<
  ClockSize,
  {
    size: number;
    ringR: number;
    tickOuter: number;
    tickInner: number;
    handR: number;
    hubR: number;
    tipR: number;
    strokeTrack: number;
    strokeRing: number;
    strokeTick: number;
    strokeHand: number;
  }
> = {
  default: {
    size: 220,
    ringR: 92,
    tickOuter: 98,
    tickInner: 88,
    handR: 78,
    hubR: 5,
    tipR: 4,
    strokeTrack: 10,
    strokeRing: 10,
    strokeTick: 2,
    strokeHand: 3,
  },
  compact: {
    size: 88,
    ringR: 36,
    tickOuter: 39,
    tickInner: 34,
    handR: 30,
    hubR: 2.5,
    tipR: 2,
    strokeTrack: 4,
    strokeRing: 4,
    strokeTick: 1.2,
    strokeHand: 1.8,
  },
};

function ringColor(urgency: CountdownUrgency): string {
  if (urgency === "warn") return "var(--warn)";
  if (urgency === "critical" || urgency === "ended") return "var(--danger)";
  return "var(--accent)";
}

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

export interface CircularCountdownClockProps {
  remainingSeconds: number | null;
  totalSeconds: number | null;
  urgency: CountdownUrgency;
  /** Shown under the digital time inside the dial */
  sublabel?: string;
  size?: ClockSize;
}

export function CircularCountdownClock({
  remainingSeconds,
  totalSeconds,
  urgency,
  sublabel,
  size = "default",
}: CircularCountdownClockProps) {
  const g = GEOMETRY[size];
  const { size: SIZE, ringR: RING_R, tickOuter: TICK_OUTER, tickInner: TICK_INNER, handR: HAND_R } = g;
  const CX = SIZE / 2;
  const CY = SIZE / 2;

  const parts = splitCountdown(remainingSeconds);
  const remaining = parts?.totalSeconds ?? 0;
  const total = totalSeconds != null && totalSeconds > 0 ? totalSeconds : null;

  const fraction =
    total != null ? Math.min(1, Math.max(0, remaining / total)) : remaining > 0 ? 1 : 0;

  const circumference = 2 * Math.PI * RING_R;
  const dashOffset = circumference * (1 - fraction);
  const handAngle = fraction * 360;
  const handEnd = polar(CX, CY, HAND_R, handAngle);

  const ticks = Array.from({ length: 12 }, (_, i) => {
    const deg = i * 30;
    const outer = polar(CX, CY, TICK_OUTER, deg);
    const inner = polar(CX, CY, TICK_INNER, deg);
    return { key: i, x1: inner.x, y1: inner.y, x2: outer.x, y2: outer.y };
  });

  const showSublabel = Boolean(sublabel);

  return (
    <div
      className={`circular-countdown urgency-${urgency}${size === "compact" ? " compact" : ""}`}
      style={{ width: SIZE, height: SIZE }}
      aria-live="polite"
    >
      <svg
        className="circular-countdown-svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        width={SIZE}
        height={SIZE}
        role="img"
        aria-label={
          remainingSeconds != null
            ? `${formatCountdownVerbose(remainingSeconds)} remaining`
            : "Time remaining unknown"
        }
      >
        <circle
          className="circular-countdown-track"
          cx={CX}
          cy={CY}
          r={RING_R}
          fill="none"
          style={{ strokeWidth: g.strokeTrack }}
        />
        <circle
          className="circular-countdown-ring"
          cx={CX}
          cy={CY}
          r={RING_R}
          fill="none"
          stroke={ringColor(urgency)}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${CX} ${CY})`}
          style={{ strokeWidth: g.strokeRing }}
        />
        {ticks.map((t) => (
          <line
            key={t.key}
            className="circular-countdown-tick"
            x1={t.x1}
            y1={t.y1}
            x2={t.x2}
            y2={t.y2}
            style={{ strokeWidth: g.strokeTick }}
          />
        ))}
        <line
          className="circular-countdown-hand"
          x1={CX}
          y1={CY}
          x2={handEnd.x}
          y2={handEnd.y}
          stroke={ringColor(urgency)}
          style={{ strokeWidth: g.strokeHand }}
        />
        <circle className="circular-countdown-hub" cx={CX} cy={CY} r={g.hubR} />
        <circle
          className="circular-countdown-tip"
          cx={handEnd.x}
          cy={handEnd.y}
          r={g.tipR}
          fill={ringColor(urgency)}
        />
      </svg>
      <div className="circular-countdown-face">
        <div className="circular-countdown-digital">{formatCountdown(remainingSeconds)}</div>
        {showSublabel && <div className="circular-countdown-sublabel">{sublabel}</div>}
      </div>
    </div>
  );
}
