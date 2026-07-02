const WINDOW_RE = /^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$/i;

export interface WindowParts {
  chrom: string;
  start: string;
  end: string;
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
