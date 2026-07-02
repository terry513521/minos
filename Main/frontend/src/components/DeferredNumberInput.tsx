import { InputHTMLAttributes, useEffect, useState } from "react";

interface DeferredNumberInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> {
  value: number | undefined;
  onCommit: (value: number | undefined) => void;
}

function parseOptionalNumber(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (trimmed === "") return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

/** Number input that commits on blur/Enter so typing decimals is not fighting live clamping. */
export function DeferredNumberInput({
  value,
  onCommit,
  onBlur,
  onKeyDown,
  ...props
}: DeferredNumberInputProps) {
  const [draft, setDraft] = useState(() => (value == null ? "" : String(value)));

  useEffect(() => {
    setDraft(value == null ? "" : String(value));
  }, [value]);

  function commit(nextRaw = draft) {
    onCommit(parseOptionalNumber(nextRaw));
  }

  return (
    <input
      {...props}
      type="number"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={(e) => {
        commit(e.target.value);
        onBlur?.(e);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
        onKeyDown?.(e);
      }}
    />
  );
}
