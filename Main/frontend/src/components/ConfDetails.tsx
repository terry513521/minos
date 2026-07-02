import { useState } from "react";

interface ConfDetailsProps {
  conf: Record<string, unknown>;
  label?: string;
  compact?: boolean;
}

function flattenConf(conf: Record<string, unknown>): Array<[string, string]> {
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

export function ConfDetails({ conf, label = "Conf", compact = false }: ConfDetailsProps) {
  const [open, setOpen] = useState(false);
  const rows = flattenConf(conf);

  return (
    <div className="conf-details">
      <button
        type="button"
        className={`button conf-details-btn${compact ? " compact" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "Hide" : label}
      </button>
      {open && (
        <div className="conf-details-panel">
          <table className="conf-params-table">
            <tbody>
              {rows.map(([key, value]) => (
                <tr key={key}>
                  <th>{key}</th>
                  <td><code>{value}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
