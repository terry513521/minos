import { InputHTMLAttributes, useEffect, useState } from "react";

interface DeferredTextInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> {
  value: string;
  onCommit: (value: string) => void;
}

/** Text/number input that commits on blur/Enter for smoother editing. */
export function DeferredTextInput({
  value,
  onCommit,
  onBlur,
  onKeyDown,
  ...props
}: DeferredTextInputProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  function commit(nextRaw = draft) {
    onCommit(nextRaw);
  }

  return (
    <input
      {...props}
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
