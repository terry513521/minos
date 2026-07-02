import { useEffect, useState } from "react";

export function computeDeadlineMs(
  timeRemainingSeconds: number | null | undefined,
  polledAt: string | null | undefined,
): number | null {
  if (timeRemainingSeconds == null || !polledAt) return null;
  return new Date(polledAt).getTime() + timeRemainingSeconds * 1000;
}

/**
 * Client-side countdown synced from platform time_remaining_seconds + polled_at.
 */
export function useSubmissionCountdown(
  timeRemainingSeconds: number | null | undefined,
  polledAt: string | null | undefined,
  active: boolean,
): number | null {
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    const deadline = computeDeadlineMs(timeRemainingSeconds, polledAt);
    if (!active || deadline == null) {
      setRemaining(null);
      return;
    }

    const tick = () => {
      setRemaining(Math.max(0, Math.floor((deadline - Date.now()) / 1000)));
    };

    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [timeRemainingSeconds, polledAt, active]);

  return remaining;
}

export interface CountdownParts {
  totalSeconds: number;
  hours: number;
  minutes: number;
  seconds: number;
}

export function splitCountdown(seconds: number | null | undefined): CountdownParts | null {
  if (seconds == null) return null;
  const total = Math.max(0, seconds);
  return {
    totalSeconds: total,
    hours: Math.floor(total / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60,
  };
}

/** Compact clock: 2:14:32 or 14:32 */
export function formatCountdown(seconds: number | null | undefined): string {
  const p = splitCountdown(seconds);
  if (!p) return "—";
  if (p.hours > 0) {
    return `${p.hours}:${String(p.minutes).padStart(2, "0")}:${String(p.seconds).padStart(2, "0")}`;
  }
  return `${p.minutes}:${String(p.seconds).padStart(2, "0")}`;
}

/** Verbose: 2 hr 14 min 32 sec */
export function formatCountdownVerbose(seconds: number | null | undefined): string {
  const p = splitCountdown(seconds);
  if (!p) return "—";
  const chunks: string[] = [];
  if (p.hours > 0) chunks.push(`${p.hours} hr`);
  if (p.minutes > 0 || p.hours > 0) chunks.push(`${p.minutes} min`);
  chunks.push(`${p.seconds} sec`);
  return chunks.join(" ");
}

/** Total human: 2 hours 14 minutes (no seconds) */
export function formatDurationHuman(seconds: number | null | undefined): string {
  const p = splitCountdown(seconds);
  if (!p) return "—";
  const parts: string[] = [];
  if (p.hours > 0) parts.push(`${p.hours} hour${p.hours === 1 ? "" : "s"}`);
  if (p.minutes > 0) parts.push(`${p.minutes} minute${p.minutes === 1 ? "" : "s"}`);
  if (parts.length === 0) parts.push(`${p.seconds} second${p.seconds === 1 ? "" : "s"}`);
  return parts.join(" ");
}

export function formatLocalDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatLocalTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function secondsUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  try {
    return Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000));
  } catch {
    return null;
  }
}

export type CountdownUrgency = "ok" | "warn" | "critical" | "ended";

export function countdownUrgency(
  seconds: number | null,
  minSubmitSeconds = 600,
): CountdownUrgency {
  if (seconds == null) return "ok";
  if (seconds <= 0) return "ended";
  if (seconds < minSubmitSeconds) return "critical";
  if (seconds < minSubmitSeconds + 300) return "warn";
  return "ok";
}

/** Progress 0–100 through an interval [startIso, endIso] at now. */
export function phaseProgress(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
  nowMs = Date.now(),
): number | null {
  if (!startIso || !endIso) return null;
  try {
    const start = new Date(startIso).getTime();
    const end = new Date(endIso).getTime();
    if (end <= start) return null;
    const pct = ((nowMs - start) / (end - start)) * 100;
    return Math.min(100, Math.max(0, pct));
  } catch {
    return null;
  }
}
