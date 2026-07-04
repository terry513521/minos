const WINDOW_RE = /^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$/i;

export interface WindowParts {
  chrom: string;
  start: string;
  end: string;
}

/** Minos platform rounds use 5 Mb challenge windows. */
export const MINOS_ROUND_SPAN_BP = 5_000_000;

export function windowSpanBp(window: string | null | undefined): number | null {
  const parts = parseWindowParts(window ?? "");
  if (!parts) return null;
  const start = Number(parts.start);
  const end = Number(parts.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return end - start;
}

export function windowSpanMb(window: string | null | undefined): number | null {
  const spanBp = windowSpanBp(window);
  if (spanBp == null) return null;
  return spanBp / 1_000_000;
}

export function formatWindowSpan(window: string | null | undefined): string | null {
  const spanMb = windowSpanMb(window);
  if (spanMb == null) return null;
  return `${spanMb.toFixed(2)} Mb`;
}

export interface BenchmarkWindowAnalysis {
  valid: boolean;
  window: string | null;
  spanBp: number | null;
  spanMb: number | null;
  isMinosRoundSize: boolean;
  error: string | null;
  warning: string | null;
}

export function analyzeBenchmarkWindow(region: string | null | undefined): BenchmarkWindowAnalysis {
  const window = normalizeRegion(region ?? "") ?? region?.trim() ?? null;
  if (!window) {
    return {
      valid: false,
      window: null,
      spanBp: null,
      spanMb: null,
      isMinosRoundSize: false,
      error: "Region is required.",
      warning: null,
    };
  }

  const spanBp = windowSpanBp(window);
  if (spanBp == null) {
    return {
      valid: false,
      window,
      spanBp: null,
      spanMb: null,
      isMinosRoundSize: false,
      error: "Invalid region format. Use chr20:10000000-15000000.",
      warning: null,
    };
  }

  const spanMb = spanBp / 1_000_000;
  const isMinosRoundSize = spanBp === MINOS_ROUND_SPAN_BP;
  let warning: string | null = null;

  if (!isMinosRoundSize) {
    warning =
      spanBp > MINOS_ROUND_SPAN_BP
        ? `Region is ${spanMb.toFixed(2)} Mb — larger than a standard 5 Mb Minos round. The worker may benchmark only a 5 Mb slice inside it.`
        : `Region is ${spanMb.toFixed(2)} Mb — smaller than a standard 5 Mb Minos round. Scores may not match live platform rounds.`;
  }

  return {
    valid: true,
    window,
    spanBp,
    spanMb,
    isMinosRoundSize,
    error: null,
    warning,
  };
}

export function parseWindowParts(window: string): WindowParts | null {
  const m = window.trim().match(WINDOW_RE);
  if (!m) return null;
  let chrom = m[1];
  if (!chrom.toLowerCase().startsWith("chr")) {
    chrom = `chr${chrom}`;
  }
  return { chrom, start: m[2], end: m[3] };
}

export function buildWindow(chrom: string, start: string, end: string): string {
  const trimmed = chrom.trim();
  const normalized = trimmed.toLowerCase().startsWith("chr") ? trimmed : `chr${trimmed}`;
  return `${normalized}:${start.trim()}-${end.trim()}`;
}

export function chromosomeFromWindow(window: string | null | undefined): string | null {
  return parseWindowParts(window ?? "")?.chrom ?? null;
}

/** Canonicalize a platform region string when possible. */
export function normalizeRegion(region: string | null | undefined): string | null {
  if (!region?.trim()) return null;
  const parts = parseWindowParts(region);
  if (parts) return buildWindow(parts.chrom, parts.start, parts.end);
  return region.trim();
}
