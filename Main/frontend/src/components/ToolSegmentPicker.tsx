import { TOOLKIT_OPTIONS, ToolkitOption } from "../types/workerAssignment";
import { formatToolLabel } from "../utils/toolDisplay";

interface ToolSegmentPickerProps {
  value: ToolkitOption;
  onChange: (tool: ToolkitOption) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function ToolSegmentPicker({
  value,
  onChange,
  disabled = false,
  "aria-label": ariaLabel = "Variant caller",
}: ToolSegmentPickerProps) {
  return (
    <div
      className={`tool-segment-group${disabled ? " tool-segment-group--disabled" : ""}`}
      role="radiogroup"
      aria-label={ariaLabel}
    >
      {TOOLKIT_OPTIONS.map((option) => {
        const active = value === option;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            className={`tool-segment-btn tool-segment-btn--${option}${active ? " active" : ""}`}
            onClick={() => onChange(option)}
          >
            {formatToolLabel(option)}
          </button>
        );
      })}
    </div>
  );
}
