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

/** Extract `{tool}_options` inner dict for miner-style .conf export. */
export function extractConfOptions(conf: Record<string, unknown>): Record<string, unknown> {
  const optionKeys = Object.keys(conf).filter((key) => key.endsWith("_options"));
  if (optionKeys.length > 0) {
    const preferred =
      optionKeys.find((key) => key === "gatk_options") ??
      optionKeys.find((key) => key === "bcftools_options") ??
      optionKeys.find((key) => key === "deepvariant_options") ??
      optionKeys[0];
    const inner = conf[preferred];
    if (inner && typeof inner === "object" && !Array.isArray(inner)) {
      return inner as Record<string, unknown>;
    }
  }

  const scalars = Object.fromEntries(
    Object.entries(conf).filter(
      ([, value]) => value == null || typeof value !== "object" || Array.isArray(value),
    ),
  );
  if (Object.keys(scalars).length > 0) {
    return scalars;
  }

  return conf;
}

function formatConfValue(value: unknown): string {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : String(value);
  }
  if (value == null) {
    return "";
  }
  return String(value);
}

/** Minos miner format: one `key=value` per line (see configs/*.conf). */
export function confToDotConf(conf: Record<string, unknown>): string {
  const options = extractConfOptions(conf);
  const lines = Object.entries(options)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}=${formatConfValue(value)}`);
  return lines.length > 0 ? `${lines.join("\n")}\n` : "";
}

export async function copyConfToClipboard(conf: Record<string, unknown>): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(confToDotConf(conf));
    return true;
  } catch {
    return false;
  }
}

export function downloadConfFile(conf: Record<string, unknown>, fileName: string): void {
  const blob = new Blob([confToDotConf(conf)], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const base = fileName.replace(/\.(json|conf)$/i, "");
  anchor.download = `${base}.conf`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function countChangedConfRows(rows: ConfRow[]): number {
  return rows.filter((row) => row.changed).length;
}
