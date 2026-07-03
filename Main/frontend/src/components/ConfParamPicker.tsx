import { useMemo, useState } from "react";
import { getParamBound, ParamInterval, clampParamInterval, formatBoundHint } from "../utils/paramBounds";
import { listToolOptionEntries } from "../utils/candidateAssign";
import { DeferredNumberInput } from "./DeferredNumberInput";
import { DeferredTextInput } from "./DeferredTextInput";

interface ConfParamPickerProps {
  baseConf: Record<string, unknown>;
  tool: string;
  selectedParams: string[];
  paramIntervals: Record<string, ParamInterval>;
  onToggle: (param: string) => void;
  onIntervalChange: (param: string, patch: Partial<ParamInterval>) => void;
  onBaseValueChange?: (param: string, raw: string) => void;
  /** When true, show tune params without allowing edits (e.g. optimization running). */
  readOnly?: boolean;
}

export function ConfParamPicker({
  baseConf,
  tool,
  selectedParams,
  paramIntervals,
  onToggle,
  onIntervalChange,
  onBaseValueChange,
  readOnly = false,
}: ConfParamPickerProps) {
  const [search, setSearch] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);

  const entries = useMemo(() => {
    const all = listToolOptionEntries(baseConf, tool);
    const query = search.trim().toLowerCase();
    let filtered = all;
    if (query) {
      filtered = filtered.filter(([param]) => param.toLowerCase().includes(query));
    }
    if (selectedOnly) {
      filtered = filtered.filter(([param]) => selectedParams.includes(param));
    }
    return filtered.sort(([a], [b]) => {
      const aSel = selectedParams.includes(a);
      const bSel = selectedParams.includes(b);
      if (aSel !== bSel) return aSel ? -1 : 1;
      return a.localeCompare(b);
    });
  }, [baseConf, tool, search, selectedOnly, selectedParams]);

  return (
    <div className={`worker-conf-picker${readOnly ? " worker-conf-picker--readonly" : ""}`}>
      <div className="worker-conf-picker-head">
        <span className="worker-assignment-label">Tune parameters</span>
        <span className="worker-conf-picker-hint">
          {readOnly
            ? "Read-only while optimization is running"
            : "Check params to search · edit base values inline · min/max/step when selected"}
        </span>
      </div>

      <div className="worker-conf-picker-toolbar">
        <input
          type="search"
          className="worker-conf-picker-search"
          placeholder="Filter parameters…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Filter parameters"
        />
        <label className="worker-conf-picker-selected-only">
          <input
            type="checkbox"
            checked={selectedOnly}
            onChange={(e) => setSelectedOnly(e.target.checked)}
          />
          <span>Selected only ({selectedParams.length})</span>
        </label>
      </div>

      {listToolOptionEntries(baseConf, tool).length === 0 ? (
        <p className="worker-conf-picker-empty">
          No {tool}_options in this base conf.
        </p>
      ) : entries.length === 0 ? (
        <p className="worker-conf-picker-empty">No parameters match your filter.</p>
      ) : (
        <div className="worker-conf-picker-list" role="group" aria-label="Base conf parameters">
          {entries.map(([param, value]) => {
            const selected = selectedParams.includes(param);
            const bound = getParamBound(tool, param);
            const interval = paramIntervals[param];
            const isNumeric =
              bound?.type === "int" ||
              bound?.type === "float" ||
              (!bound && Number.isFinite(Number(value)));
            const boundHint = formatBoundHint(tool, param);
            const baseValueEditor = readOnly ? undefined : onBaseValueChange;

            return (
              <div
                key={param}
                className={`worker-conf-picker-row${selected ? " selected" : ""}`}
              >
                <div className="worker-conf-picker-main">
                  <label className="worker-conf-picker-check">
                    <input
                      type="checkbox"
                      checked={selected}
                      disabled={readOnly}
                      onChange={() => onToggle(param)}
                      aria-label={`Tune ${param}`}
                    />
                  </label>
                  <span className="worker-conf-picker-name" title={param}>
                    {param}
                  </span>
                  {baseValueEditor ? (
                    bound?.type === "enum" && bound.allowedValues?.length ? (
                      <select
                        className="worker-conf-picker-base-input"
                        value={value}
                        onChange={(e) => baseValueEditor!(param, e.target.value)}
                        aria-label={`${param} base value`}
                      >
                        {bound.allowedValues.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    ) : bound?.type === "bool" ? (
                      <label className="worker-conf-picker-base-bool">
                        <input
                          type="checkbox"
                          checked={value === "true"}
                          onChange={(e) =>
                            baseValueEditor!(param, e.target.checked ? "true" : "false")
                          }
                          aria-label={`${param} base value`}
                        />
                        <span>{value === "true" ? "true" : "false"}</span>
                      </label>
                    ) : (
                      <DeferredTextInput
                        className="worker-conf-picker-base-input input-mono"
                        value={value}
                        onCommit={(next) => baseValueEditor!(param, next)}
                        type={isNumeric ? "number" : "text"}
                        step={bound?.type === "float" ? "any" : bound?.type === "int" ? 1 : undefined}
                        min={bound?.min}
                        max={bound?.max}
                        spellCheck={false}
                        aria-label={`${param} base value`}
                      />
                    )
                  ) : (
                    <code className="worker-conf-picker-value">{value}</code>
                  )}
                </div>

                {selected && isNumeric && (
                  <div className="worker-param-interval">
                    {boundHint && (
                      <span className="worker-param-interval-hint">{boundHint}</span>
                    )}
                    <div className="worker-param-interval-fields">
                      <label className="worker-param-interval-field">
                        <span>Min</span>
                        <DeferredNumberInput
                          step="any"
                          min={bound?.min}
                          max={bound?.max}
                          value={interval?.min}
                          disabled={readOnly}
                          onCommit={(min) =>
                            onIntervalChange(
                              param,
                              clampParamInterval(tool, param, { ...interval, min }),
                            )
                          }
                          aria-label={`${param} min`}
                        />
                      </label>
                      <label className="worker-param-interval-field">
                        <span>Max</span>
                        <DeferredNumberInput
                          step="any"
                          min={bound?.min}
                          max={bound?.max}
                          value={interval?.max}
                          disabled={readOnly}
                          onCommit={(max) =>
                            onIntervalChange(
                              param,
                              clampParamInterval(tool, param, { ...interval, max }),
                            )
                          }
                          aria-label={`${param} max`}
                        />
                      </label>
                      <label className="worker-param-interval-field">
                        <span>Step</span>
                        <DeferredNumberInput
                          step="any"
                          min={0}
                          value={interval?.step}
                          disabled={readOnly}
                          onCommit={(step) =>
                            onIntervalChange(
                              param,
                              clampParamInterval(tool, param, { ...interval, step }),
                            )
                          }
                          aria-label={`${param} step`}
                        />
                      </label>
                    </div>
                  </div>
                )}

                {selected && bound?.type === "enum" && bound.allowedValues && (
                  <div className="worker-param-interval worker-param-interval-enum">
                    <span className="worker-param-interval-label">Search values</span>
                    <div className="worker-param-enum-values">
                      {bound.allowedValues.map((opt) => {
                        const checked = (interval?.values ?? []).includes(opt);
                        return (
                          <label key={opt} className="worker-param-enum-option">
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={readOnly}
                              onChange={() => {
                                const current = interval?.values ?? [];
                                const next = checked
                                  ? current.filter((v) => v !== opt)
                                  : [...current, opt];
                                onIntervalChange(param, { values: next });
                              }}
                            />
                            <span>{opt}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
