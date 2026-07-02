import { getParamBound, ParamInterval, clampParamInterval, formatBoundHint } from "../utils/paramBounds";
import { listToolOptionEntries } from "../utils/candidateAssign";

interface ConfParamPickerProps {
  baseConf: Record<string, unknown>;
  tool: string;
  selectedParams: string[];
  paramIntervals: Record<string, ParamInterval>;
  onToggle: (param: string) => void;
  onIntervalChange: (param: string, patch: Partial<ParamInterval>) => void;
}

function parseNum(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

export function ConfParamPicker({
  baseConf,
  tool,
  selectedParams,
  paramIntervals,
  onToggle,
  onIntervalChange,
}: ConfParamPickerProps) {
  const entries = listToolOptionEntries(baseConf, tool);

  return (
    <div className="worker-conf-picker">
      <div className="worker-conf-picker-head">
        <span className="worker-assignment-label">Base conf</span>
        <span className="worker-conf-picker-hint">
          Check parameters to tune · set min/max/step per worker
        </span>
      </div>

      {entries.length === 0 ? (
        <p className="worker-conf-picker-empty">
          No {tool}_options in this base conf.
        </p>
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

            return (
              <div
                key={param}
                className={`worker-conf-picker-row${selected ? " selected" : ""}`}
              >
                <label className="worker-conf-picker-main">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => onToggle(param)}
                    aria-label={`Tune ${param}`}
                  />
                  <span className="worker-conf-picker-name">{param}</span>
                  <code className="worker-conf-picker-value">{value}</code>
                </label>

                {selected && isNumeric && (
                  <div className="worker-param-interval">
                    {boundHint && (
                      <span className="worker-param-interval-hint">{boundHint}</span>
                    )}
                    <div className="worker-param-interval-fields">
                    <label className="worker-param-interval-field">
                      <span>Min</span>
                      <input
                        type="number"
                        step="any"
                        min={bound?.min}
                        max={bound?.max}
                        value={interval?.min ?? ""}
                        onChange={(e) =>
                          onIntervalChange(
                            param,
                            clampParamInterval(tool, param, {
                              ...interval,
                              min: parseNum(e.target.value),
                            }),
                          )
                        }
                        aria-label={`${param} min`}
                      />
                    </label>
                    <label className="worker-param-interval-field">
                      <span>Max</span>
                      <input
                        type="number"
                        step="any"
                        min={bound?.min}
                        max={bound?.max}
                        value={interval?.max ?? ""}
                        onChange={(e) =>
                          onIntervalChange(
                            param,
                            clampParamInterval(tool, param, {
                              ...interval,
                              max: parseNum(e.target.value),
                            }),
                          )
                        }
                        aria-label={`${param} max`}
                      />
                    </label>
                    <label className="worker-param-interval-field">
                      <span>Step</span>
                      <input
                        type="number"
                        step="any"
                        min={0}
                        value={interval?.step ?? ""}
                        onChange={(e) =>
                          onIntervalChange(
                            param,
                            clampParamInterval(tool, param, {
                              ...interval,
                              step: parseNum(e.target.value),
                            }),
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
                    <span className="worker-param-interval-label">Values</span>
                    <div className="worker-param-enum-values">
                      {bound.allowedValues.map((opt) => {
                        const checked = (interval?.values ?? []).includes(opt);
                        return (
                          <label key={opt} className="worker-param-enum-option">
                            <input
                              type="checkbox"
                              checked={checked}
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
