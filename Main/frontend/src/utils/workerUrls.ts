/** Derive worker main API root from a health URL (…/health → …). */
export function deriveBaseUrlFromHealth(healthUrl: string): string {
  const trimmed = healthUrl.trim().replace(/\/+$/, "");
  if (trimmed.toLowerCase().endsWith("/health")) {
    return trimmed.slice(0, -"/health".length);
  }
  return trimmed;
}

export function parseApiError(raw: string): string {
  try {
    const data = JSON.parse(raw) as { detail?: string | { msg?: string }[] };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {
    /* use raw */
  }
  return raw || "Request failed";
}
