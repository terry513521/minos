import { WorkerDispatchPayload } from "../api/client";
import { listToolOptionKeys } from "./candidateAssign";
import { buildGatkReferenceConf } from "./paramBounds";
import { parseAutoModeTunableImport } from "./autoModeTunableFile";
import {
  assignmentWindowFromRegion,
  buildDispatchBaseConf,
  CONF_CHECK_ADAPTIVE_MAX_TRIALS,
  DEFAULT_ALGORITHM,
  DEFAULT_LIMIT_SECONDS,
  DEFAULT_TRIAL_MEMORY_GB,
  DEFAULT_TRIAL_THREADS,
  ToolkitOption,
  TOOLKIT_OPTIONS,
} from "../types/workerAssignment";
import { normalizeRegion } from "./window";

export interface ParsedConfCheckFile {
  tool: ToolkitOption;
  baseConf: Record<string, unknown>;
  fileName?: string;
}

export function parseConfCheckFile(
  text: string,
  toolHint: ToolkitOption = "gatk",
): { ok: true; result: ParsedConfCheckFile } | { ok: false; error: string } {
  const reference = buildGatkReferenceConf();
  const parsed = parseAutoModeTunableImport(text, toolHint, reference);
  if (!parsed.ok) {
    return { ok: false, error: parsed.error };
  }

  if (parsed.result.kind === "tunable") {
    const toolRaw = (parsed.result.data.baseConf
      ? Object.keys(parsed.result.data.baseConf).find((key) => key.endsWith("_options"))?.replace(/_options$/, "")
      : toolHint) ?? toolHint;
    const tool = TOOLKIT_OPTIONS.includes(toolRaw as ToolkitOption)
      ? (toolRaw as ToolkitOption)
      : toolHint;
    const baseConf = parsed.result.data.baseConf ?? reference;
    return { ok: true, result: { tool, baseConf: structuredClone(baseConf) } };
  }

  const baseConf = parsed.result.baseConf;
  const optionKey = Object.keys(baseConf).find((key) => key.endsWith("_options"));
  const toolRaw = optionKey?.replace(/_options$/, "") ?? toolHint;
  const tool = TOOLKIT_OPTIONS.includes(toolRaw as ToolkitOption)
    ? (toolRaw as ToolkitOption)
    : toolHint;
  return { ok: true, result: { tool, baseConf: structuredClone(baseConf) } };
}

export function minimalBenchmarkParam(
  tool: ToolkitOption,
  baseConf: Record<string, unknown>,
): string {
  const keys = listToolOptionKeys(baseConf, tool);
  if (keys.length > 0) return keys[0];
  return "pcr_indel_model";
}

export function buildConfCheckDispatchPayload(
  regionInput: string,
  parsed: ParsedConfCheckFile,
): WorkerDispatchPayload | null {
  const window = assignmentWindowFromRegion(regionInput, "");
  if (!window) return null;

  const param = minimalBenchmarkParam(parsed.tool, parsed.baseConf);
  return {
    window: normalizeRegion(window) ?? window,
    tool: parsed.tool,
    base_conf: buildDispatchBaseConf(
      parsed.baseConf,
      DEFAULT_TRIAL_THREADS,
      DEFAULT_TRIAL_MEMORY_GB,
    ),
    params: [param],
    concurrency: 1,
    algorithm: DEFAULT_ALGORITHM,
    limit_seconds: DEFAULT_LIMIT_SECONDS,
    adaptive_max_trials: CONF_CHECK_ADAPTIVE_MAX_TRIALS,
  };
}
