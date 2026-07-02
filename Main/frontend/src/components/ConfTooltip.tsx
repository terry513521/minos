import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildConfRows,
  copyConfToClipboard,
  countChangedConfRows,
  downloadConfFile,
} from "../utils/confDisplay";

interface ConfTooltipProps {
  conf: Record<string, unknown>;
  label?: string;
  /** panel = full-width inline drawer below button (worker assignment) */
  layout?: "popover" | "panel";
  /** When set, rows that differ from base are highlighted */
  baseConf?: Record<string, unknown> | null;
  /** Show View + Copy + Download toolbar (intended for worker best conf) */
  showActions?: boolean;
  downloadFileName?: string;
}

export function ConfTooltip({
  conf,
  label = "Conf",
  layout = "popover",
  baseConf = null,
  showActions = false,
  downloadFileName = "conf",
}: ConfTooltipProps) {
  const [open, setOpen] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const wrapRef = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => buildConfRows(conf, baseConf), [conf, baseConf]);
  const changedCount = useMemo(() => countChangedConfRows(rows), [rows]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (copyState === "idle") return;
    const timer = window.setTimeout(() => setCopyState("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  async function handleCopy() {
    const ok = await copyConfToClipboard(conf);
    setCopyState(ok ? "copied" : "failed");
  }

  function handleDownload() {
    downloadConfFile(conf, downloadFileName);
  }

  const viewLabel = open ? "Hide" : "View";

  return (
    <div
      className={`conf-tooltip-wrap${layout === "panel" ? " conf-tooltip-wrap--panel" : ""}${showActions ? " conf-tooltip-wrap--actions" : ""}`}
      ref={wrapRef}
    >
      {showActions ? (
        <div className="conf-toolbar" role="group" aria-label={`${label} actions`}>
          <button
            type="button"
            className="button ghost conf-toolbar-btn"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-haspopup="dialog"
          >
            {viewLabel}
          </button>
          <button
            type="button"
            className="button ghost conf-toolbar-btn"
            onClick={() => void handleCopy()}
          >
            {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
          </button>
          <button
            type="button"
            className="button ghost conf-toolbar-btn"
            onClick={handleDownload}
          >
            Download
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="button conf-tooltip-btn"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-haspopup="dialog"
        >
          {label}
        </button>
      )}

      {open && (
        <div
          className={`conf-tooltip-popover${layout === "panel" ? " conf-tooltip-popover--panel" : ""}`}
          role="dialog"
          aria-label="Config parameters"
        >
          <div className="conf-tooltip-arrow" aria-hidden />
          {baseConf && changedCount > 0 && (
            <p className="conf-diff-legend">
              {changedCount} parameter{changedCount === 1 ? "" : "s"} changed from base conf
            </p>
          )}
          <table className="conf-params-table">
            <tbody>
              {rows.map((row) => (
                <tr key={row.path} className={row.changed ? "conf-param-changed" : undefined}>
                  <th>{row.path}</th>
                  <td>
                    <code>{row.value}</code>
                    {row.changed && row.baseValue != null && (
                      <span className="conf-param-was">
                        was <code>{row.baseValue}</code>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
