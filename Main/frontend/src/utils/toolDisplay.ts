import { TOOLKIT_OPTIONS, ToolkitOption } from "../types/workerAssignment";

const TOOL_LABELS: Record<ToolkitOption, string> = {
  gatk: "GATK",
  bcftools: "BCFtools",
  deepvariant: "DeepVariant",
};

export function formatToolLabel(tool: string): string {
  const key = tool.toLowerCase();
  if (TOOLKIT_OPTIONS.includes(key as ToolkitOption)) {
    return TOOL_LABELS[key as ToolkitOption];
  }
  return tool;
}

export function normalizeToolKey(tool: string): ToolkitOption | null {
  const key = tool.toLowerCase();
  return TOOLKIT_OPTIONS.includes(key as ToolkitOption) ? (key as ToolkitOption) : null;
}

export function toolBadgeClass(tool: string): string {
  const key = normalizeToolKey(tool);
  return key ? `tool-badge--${key}` : "tool-badge--unknown";
}
