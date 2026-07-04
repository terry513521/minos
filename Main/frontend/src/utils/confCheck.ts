import { WorkerDispatchPayload } from "../api/client";
import { listToolOptionKeys } from "./candidateAssign";
import { buildGatkReferenceConf } from "./paramBounds";
import { parseAutoModeTunableImport } from "./autoModeTunableFile";
import {
  buildDispatchBaseConf,
  CONF_CHECK_ADAPTIVE_MAX_TRIALS,
  CONF_CHECK_TRIAL_MEMORY_GB,
  CONF_CHECK_TRIAL_THREADS,
  DEFAULT_ALGORITHM,
  DEFAULT_LIMIT_SECONDS,
  ToolkitOption,
  TOOLKIT_OPTIONS,
} from "../types/workerAssignment";
import { analyzeBenchmarkWindow } from "./window";

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
): { ok: true; payload: WorkerDispatchPayload } | { ok: false; error: string } {
  const analysis = analyzeBenchmarkWindow(regionInput);
  if (!analysis.valid || !analysis.window) {
    return { ok: false, error: analysis.error ?? "Invalid region for benchmark." };
  }

  const param = minimalBenchmarkParam(parsed.tool, parsed.baseConf);
  return {
    ok: true,
    payload: {
      window: analysis.window,
      tool: parsed.tool,
      base_conf: buildDispatchBaseConf(
        parsed.baseConf,
        CONF_CHECK_TRIAL_THREADS,
        CONF_CHECK_TRIAL_MEMORY_GB,
      ),
      params: [param],
      concurrency: 1,
      algorithm: DEFAULT_ALGORITHM,
      limit_seconds: DEFAULT_LIMIT_SECONDS,
      adaptive_max_trials: CONF_CHECK_ADAPTIVE_MAX_TRIALS,
    },
  };
}
