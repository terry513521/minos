export interface ConfRow {
  path: string;
  value: string;
  baseValue: string | null;
  changed: boolean;
}

export function flattenConf(conf: Record<string, unknown>): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  const walk = (obj: Record<string, unknown>, prefix: string) => {
    for (const [key, value] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (value != null && typeof value === "object" && !Array.isArray(value)) {
        walk(value as Record<string, unknown>, path);
      } else {
        rows.push([path, String(value)]);
      }
    }
  };
  walk(conf, "");
  return rows;
}

export function buildConfRows(
  conf: Record<string, unknown>,
  baseConf?: Record<string, unknown> | null,
): ConfRow[] {
  const bestRows = flattenConf(conf);
  if (!baseConf) {
    return bestRows.map(([path, value]) => ({
      path,
      value,
      baseValue: null,
      changed: false,
    }));
  }

  const baseFlat = Object.fromEntries(flattenConf(baseConf));
  return bestRows.map(([path, value]) => {
    const baseValue = Object.prototype.hasOwnProperty.call(baseFlat, path)
      ? baseFlat[path]
      : null;
    const changed = baseValue !== value;
    return { path, value, baseValue, changed };
  });
}

export function confToJson(conf: Record<string, unknown>, pretty = true): string {
  return JSON.stringify(conf, null, pretty ? 2 : 0);
}

export async function copyConfToClipboard(conf: Record<string, unknown>): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(confToJson(conf));
    return true;
  } catch {
    return false;
  }
}

export function downloadConfFile(conf: Record<string, unknown>, fileName: string): void {
  const blob = new Blob([confToJson(conf)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName.endsWith(".json") ? fileName : `${fileName}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function countChangedConfRows(rows: ConfRow[]): number {
  return rows.filter((row) => row.changed).length;
}
