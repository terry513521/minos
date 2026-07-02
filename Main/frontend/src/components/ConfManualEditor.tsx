import { useEffect, useState } from "react";
import { getParamBound } from "../utils/paramBounds";
import {
  getToolOptions,
  listEditableToolParams,
  parseToolOptionValue,
  parseToolOptionsJson,
  setToolOption,
  setToolOptions,
  toolOptionsToJson,
} from "../utils/confEdit";

interface ConfManualEditorProps {
  baseConf: Record<string, unknown>;
  tool: string;
  onChange: (nextBaseConf: Record<string, unknown>) => void;
}

type EditorMode = "form" | "json";

export function ConfManualEditor({ baseConf, tool, onChange }: ConfManualEditorProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<EditorMode>("form");
  const [jsonText, setJsonText] = useState(() => toolOptionsToJson(baseConf, tool));
  const [jsonError, setJsonError] = useState<string | null>(null);

  const entries = listEditableToolParams(baseConf, tool);
  const optionsKey = `${tool}_options`;

  useEffect(() => {
    if (!open || mode !== "json") return;
    setJsonText(toolOptionsToJson(baseConf, tool));
    setJsonError(null);
  }, [baseConf, tool, open, mode]);

  function handleFormChange(param: string, raw: string) {
    const value = parseToolOptionValue(tool, param, raw);
    onChange(setToolOption(baseConf, tool, param, value));
  }

  function handleApplyJson() {
    const result = parseToolOptionsJson(tool, jsonText);
    if (!result.ok) {
      setJsonError(result.error);
      return;
    }
    setJsonError(null);
    onChange(setToolOptions(baseConf, tool, result.options));
    setMode("form");
  }

  function handleResetJson() {
    setJsonText(toolOptionsToJson(baseConf, tool));
    setJsonError(null);
  }

  return (
    <div className="worker-conf-manual">
      <button
        type="button"
        className="button ghost worker-conf-manual-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? "Hide manual edit" : "Edit tool config"}
      </button>

      {open && (
        <div className="worker-conf-manual-panel" role="region" aria-label="Manual tool config editor">
          <div className="worker-conf-manual-tabs" role="tablist" aria-label="Editor mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "form"}
              className={`worker-conf-manual-tab${mode === "form" ? " active" : ""}`}
              onClick={() => setMode("form")}
            >
              Form
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "json"}
              className={`worker-conf-manual-tab${mode === "json" ? " active" : ""}`}
              onClick={() => setMode("json")}
            >
              JSON
            </button>
          </div>

          {mode === "form" ? (
            entries.length === 0 ? (
              <p className="worker-conf-manual-empty">No {optionsKey} in this base conf.</p>
            ) : (
              <div className="worker-conf-manual-form">
                {entries.map(([param, value]) => {
                  const bound = getParamBound(tool, param);
                  const current = getToolOptions(baseConf, tool)[param];
                  const displayValue = String(current ?? value);

                  if (bound?.type === "enum" && bound.allowedValues?.length) {
                    return (
                      <label key={param} className="worker-conf-manual-field">
                        <span className="worker-conf-manual-label">{param}</span>
                        <select
                          value={displayValue}
                          onChange={(e) => handleFormChange(param, e.target.value)}
                        >
                          {bound.allowedValues.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </label>
                    );
                  }

                  if (bound?.type === "bool") {
                    return (
                      <label key={param} className="worker-conf-manual-field worker-conf-manual-field--bool">
                        <span className="worker-conf-manual-label">{param}</span>
                        <input
                          type="checkbox"
                          checked={displayValue === "true"}
                          onChange={(e) =>
                            handleFormChange(param, e.target.checked ? "true" : "false")
                          }
                        />
                      </label>
                    );
                  }

                  return (
                    <label key={param} className="worker-conf-manual-field">
                      <span className="worker-conf-manual-label">{param}</span>
                      <input
                        type={bound?.type === "int" || bound?.type === "float" ? "number" : "text"}
                        step={bound?.type === "float" ? "any" : bound?.type === "int" ? 1 : undefined}
                        min={bound?.min}
                        max={bound?.max}
                        value={displayValue}
                        onChange={(e) => handleFormChange(param, e.target.value)}
                        spellCheck={false}
                      />
                    </label>
                  );
                })}
              </div>
            )
          ) : (
            <div className="worker-conf-manual-json">
              <p className="worker-conf-manual-json-hint">
                Edit <code>{optionsKey}</code> as JSON, then Apply.
              </p>
              <textarea
                className="worker-conf-manual-json-input input-mono"
                value={jsonText}
                onChange={(e) => {
                  setJsonText(e.target.value);
                  setJsonError(null);
                }}
                rows={12}
                spellCheck={false}
                aria-label={`${optionsKey} JSON`}
              />
              {jsonError && <div className="alert error worker-conf-manual-json-error">{jsonError}</div>}
              <div className="worker-conf-manual-json-actions">
                <button type="button" className="button ghost" onClick={handleResetJson}>
                  Reset
                </button>
                <button type="button" className="button primary" onClick={handleApplyJson}>
                  Apply JSON
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
