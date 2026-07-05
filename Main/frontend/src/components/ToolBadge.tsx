import { formatToolLabel, toolBadgeClass } from "../utils/toolDisplay";

interface ToolBadgeProps {
  tool: string;
  className?: string;
  title?: string;
}

export function ToolBadge({ tool, className = "", title }: ToolBadgeProps) {
  const extra = className.trim();
  return (
    <span
      className={`chip tool-badge ${toolBadgeClass(tool)}${extra ? ` ${extra}` : ""}`}
      title={title}
    >
      {formatToolLabel(tool)}
    </span>
  );
}
