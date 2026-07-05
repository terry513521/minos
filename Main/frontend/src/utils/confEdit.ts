import { getParamBound, ParamBoundSpec } from "./paramBounds";
import { buildToolReferenceConf } from "./paramBounds";
import { listToolOptionEntries, toolOptionsKey } from "./candidateAssign";

/** Merge reference `{tool}_options` when missing or empty (e.g. DeepVariant defaults). */
export function ensureToolOptionsInBaseConf(
  baseConf: Record<string, unknown>,
  tool: string,
): Record<string, unknown> {
  const key = toolOptionsKey(tool);
  const existing = baseConf[key];
  const hasOptions =
    existing &&
    typeof existing === "object" &&
    !Array.isArray(existing) &&
    Object.keys(existing as Record<string, unknown>).length > 0;
  if (hasOptions) {
    return baseConf;
  }
  const reference = buildToolReferenceConf(tool);
  const refOptions = reference[key];
  const mergedOptions =
    refOptions && typeof refOptions === "object" && !Array.isArray(refOptions)
      ? { ...(refOptions as Record<string, unknown>) }
      : {};
  if (existing && typeof existing === "object" && !Array.isArray(existing)) {
    Object.assign(mergedOptions, existing as Record<string, unknown>);
  }
  return { ...baseConf, [key]: mergedOptions };
}

export function getToolOptions(
  baseConf: Record<string, unknown>,
  tool: string,
): Record<string, unknown> {
  const options = baseConf[toolOptionsKey(tool)];
  if (!options || typeof options !== "object" || Array.isArray(options)) {
    return {};
  }
  return { ...(options as Record<string, unknown>) };
}

export function setToolOptions(
  baseConf: Record<string, unknown>,
  tool: string,
  options: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...baseConf,
    [toolOptionsKey(tool)]: { ...options },
  };
}

export function setToolOption(
  baseConf: Record<string, unknown>,
  tool: string,
  param: string,
  value: unknown,
): Record<string, unknown> {
  const options = getToolOptions(baseConf, tool);
  options[param] = value;
  return setToolOptions(baseConf, tool, options);
}

export function parseToolOptionValue(
  tool: string,
  param: string,
  raw: string,
  spec?: ParamBoundSpec | null,
): unknown {
  const bound = spec ?? getParamBound(tool, param);
  const trimmed = raw.trim();

  if (bound?.type === "bool") {
    if (trimmed === "true" || trimmed === "1") return true;
    if (trimmed === "false" || trimmed === "0") return false;
    return raw;
  }

  if (bound?.type === "enum" && bound.allowedValues?.length) {
    return bound.allowedValues.includes(trimmed) ? trimmed : raw;
  }

  if (bound?.type === "int") {
    const parsed = Number.parseInt(trimmed, 10);
    if (Number.isFinite(parsed)) {
      if (bound.min != null && bound.max != null) {
        return Math.min(bound.max, Math.max(bound.min, parsed));
      }
      return parsed;
    }
    return raw;
  }

  if (bound?.type === "float") {
    const parsed = Number.parseFloat(trimmed);
    if (Number.isFinite(parsed)) {
      if (bound.min != null && bound.max != null) {
        return Math.min(bound.max, Math.max(bound.min, parsed));
      }
      return parsed;
    }
    return raw;
  }

  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  const asNum = Number(trimmed);
  if (trimmed !== "" && Number.isFinite(asNum)) {
    return Number.isInteger(asNum) && !trimmed.includes(".") ? asNum : asNum;
  }
  return raw;
}

export function parseToolOptionsJson(
  tool: string,
  text: string,
): { ok: true; options: Record<string, unknown> } | { ok: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Invalid JSON",
    };
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: "Tool config must be a JSON object" };
  }

  const options: Record<string, unknown> = {};
  for (const [param, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (value != null && typeof value === "object") {
      return { ok: false, error: `Invalid value for ${param}: must be scalar` };
    }
    options[param] =
      typeof value === "string"
        ? parseToolOptionValue(tool, param, value)
        : value;
  }

  return { ok: true, options };
}

export function toolOptionsToJson(
  baseConf: Record<string, unknown>,
  tool: string,
  pretty = true,
): string {
  return JSON.stringify(getToolOptions(baseConf, tool), null, pretty ? 2 : 0);
}

export function listEditableToolParams(
  baseConf: Record<string, unknown>,
  tool: string,
): Array<[string, string]> {
  return listToolOptionEntries(baseConf, tool);
}
