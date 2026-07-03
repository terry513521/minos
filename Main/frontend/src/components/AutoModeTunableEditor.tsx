import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, AutoModeConfig, WorkerRecord } from "../api/client";
import { DEFAULT_FINE_TUNE_PARAMS } from "../utils/candidateAssign";
import {
  buildDispatchParamIntervals,
  buildGatkReferenceConf,
  defaultParamInterval,
  ParamInterval,
} from "../utils/paramBounds";
import { paramIntervalsFromAutoConfig, workerAlgorithmsFromAutoConfig, workerConcurrencyFromAutoConfig, workerSettingForName, workerTrialMemoryGbFromAutoConfig, workerTrialThreadsFromAutoConfig } from "../utils/autoModeSync";
import { syncManualParamDefaultsFromAutoConfig } from "../utils/manualParamDefaults";
import { ALGORITHM_OPTIONS, AlgorithmOption, clampConcurrency, clampTrialMemoryGb, clampTrialThreads, CONCURRENCY_OPTIONS, MAX_TRIAL_THREADS } from "../types/workerAssignment";
import { ConfParamPicker } from "./ConfParamPicker";
import { DeferredNumberInput } from "./DeferredNumberInput";
import { AUTO_MODE_CHANGED_EVENT } from "./AutoModePanel";

interface AutoModeTunableEditorProps {
  open: boolean;
  config: AutoModeConfig;
  tool: string;
  running: boolean;
  /** `enable` = arm auto mode after save; `edit` = save parameters only */
  variant?: "edit" | "enable";
  onClose: () => void;
  onSaved?: () => void;
  /** Called after config save when variant is `enable`. */
  onEnable?: () => void | Promise<void>;
}

export function AutoModeTunableEditor({
  open,
  config,
  tool,
  running,
  variant = "edit",
  onClose,
  onSaved,
  onEnable,
}: AutoModeTunableEditorProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const referenceConf = buildGatkReferenceConf();
  const [selectedParams, setSelectedParams] = useState<string[]>([...config.params]);
  const [paramIntervals, setParamIntervals] = useState<Record<string, ParamInterval>>(() =>
    paramIntervalsFromAutoConfig(config),
  );
  const [workerAlgorithms, setWorkerAlgorithms] = useState<Record<string, AlgorithmOption>>(() =>
    workerAlgorithmsFromAutoConfig(config),
  );
  const [workerTrialThreads, setWorkerTrialThreads] = useState<Record<string, number>>(() =>
    workerTrialThreadsFromAutoConfig(config),
  );
  const [workerTrialMemoryGb, setWorkerTrialMemoryGb] = useState<Record<string, number>>(() =>
    workerTrialMemoryGbFromAutoConfig(config),
  );
  const [workerConcurrency, setWorkerConcurrency] = useState<Record<string, number>>(() =>
    workerConcurrencyFromAutoConfig(config),
  );
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registeredWorkers, setRegisteredWorkers] = useState<WorkerRecord[]>([]);

  const workerNames = useMemo(() => {
    if (registeredWorkers.length > 0) {
      return [...registeredWorkers]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((worker) => worker.name);
    }
    return [...config.worker_names];
  }, [registeredWorkers, config.worker_names]);

  function applyConfigToState(nextConfig: AutoModeConfig, names: string[]) {
    setSelectedParams([...nextConfig.params]);
    setParamIntervals(paramIntervalsFromAutoConfig(nextConfig));
    setWorkerAlgorithms(
      Object.fromEntries(
        names.map((name) => [
          name,
          workerSettingForName(workerAlgorithmsFromAutoConfig(nextConfig), name) ?? "optuna",
        ]),
      ) as Record<string, AlgorithmOption>,
    );
    setWorkerTrialThreads(
      Object.fromEntries(
        names.map((name) => [
          name,
          clampTrialThreads(
            workerSettingForName(workerTrialThreadsFromAutoConfig(nextConfig), name) ?? 4,
          ),
        ]),
      ),
    );
    setWorkerTrialMemoryGb(
      Object.fromEntries(
        names.map((name) => [
          name,
          clampTrialMemoryGb(
            workerSettingForName(workerTrialMemoryGbFromAutoConfig(nextConfig), name) ?? 6,
          ),
        ]),
      ),
    );
    setWorkerConcurrency(
      Object.fromEntries(
        names.map((name) => [
          name,
          clampConcurrency(workerSettingForName(workerConcurrencyFromAutoConfig(nextConfig), name) ?? 1),
        ]),
      ),
    );
  }

  useEffect(() => {
    if (!open) {
      setRegisteredWorkers([]);
      setHydrating(false);
      return;
    }

    let cancelled = false;
    setHydrating(true);
    setError(null);

    void (async () => {
      try {
        const [workers, status] = await Promise.all([api.listWorkers(), api.getAutoMode()]);
        if (cancelled) return;

        setRegisteredWorkers(workers);
        const names =
          workers.length > 0
            ? [...workers].sort((a, b) => a.name.localeCompare(b.name)).map((worker) => worker.name)
            : [...status.config.worker_names];
        applyConfigToState(status.config, names);
      } catch {
        if (cancelled) return;
        const names = [...config.worker_names];
        setRegisteredWorkers([]);
        applyConfigToState(config, names);
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function toggleParam(param: string) {
    if (selectedParams.includes(param)) {
      const next = selectedParams.filter((name) => name !== param);
      const { [param]: _removed, ...rest } = paramIntervals;
      setSelectedParams(next);
      setParamIntervals(rest);
      return;
    }
    const options = referenceConf[`${tool}_options`];
    const baseValue =
      options && typeof options === "object" && !Array.isArray(options)
        ? String((options as Record<string, unknown>)[param] ?? "")
        : "";
    setSelectedParams([...selectedParams, param]);
    setParamIntervals({
      ...paramIntervals,
      [param]: paramIntervals[param] ?? defaultParamInterval(tool, param, baseValue),
    });
  }

  function updateInterval(param: string, patch: Partial<ParamInterval>) {
    setParamIntervals({
      ...paramIntervals,
      [param]: { ...paramIntervals[param], ...patch },
    });
  }

  function resetDefaults() {
    const params = [...DEFAULT_FINE_TUNE_PARAMS];
    const intervals: Record<string, ParamInterval> = {};
    for (const param of params) {
      const options = referenceConf[`${tool}_options`];
      const baseValue =
        options && typeof options === "object" && !Array.isArray(options)
          ? String((options as Record<string, unknown>)[param] ?? "")
          : "";
      intervals[param] = defaultParamInterval(tool, param, baseValue);
    }
    setSelectedParams(params);
    setParamIntervals(intervals);
    const defaults: AutoModeConfig = {
      ...config,
      worker_names: workerNames,
      params,
      param_intervals: Object.fromEntries(
        Object.entries(intervals).map(([name, interval]) => [
          name,
          {
            min: interval.min,
            max: interval.max,
            step: interval.step,
            values: interval.values,
          },
        ]),
      ),
      worker_algorithms: Object.fromEntries(workerNames.map((name) => [name, "optuna"])),
      worker_trial_threads: Object.fromEntries(workerNames.map((name) => [name, 4])),
      worker_trial_memory_gb: Object.fromEntries(workerNames.map((name) => [name, 6])),
      worker_concurrency: Object.fromEntries(workerNames.map((name) => [name, 1])),
    };
    applyConfigToState(defaults, workerNames);
  }

  async function saveTunableConfig(enableAfterSave = false) {
    if (selectedParams.length === 0) {
      setError("Select at least one parameter to tune.");
      return;
    }
    if (workerNames.length === 0) {
      setError("Add at least one worker before saving auto mode settings.");
      return;
    }
    const dispatchIntervals = buildDispatchParamIntervals(tool, selectedParams, paramIntervals);
    if (!dispatchIntervals) {
      setError("Each selected parameter needs a valid search interval.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const status = await api.updateAutoModeConfig({
        params: selectedParams,
        param_intervals: dispatchIntervals,
        worker_algorithms: workerAlgorithms,
        worker_trial_threads: workerTrialThreads,
        worker_trial_memory_gb: workerTrialMemoryGb,
        worker_concurrency: workerConcurrency,
      });
      syncManualParamDefaultsFromAutoConfig(status.config);
      window.dispatchEvent(new Event(AUTO_MODE_CHANGED_EVENT));
      if (enableAfterSave && onEnable) {
        await onEnable();
      } else {
        onSaved?.();
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save auto mode parameters");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await saveTunableConfig(variant === "enable");
  }

  async function handleSaveOnly(e: FormEvent) {
    e.preventDefault();
    await saveTunableConfig(false);
  }

  const isEnable = variant === "enable";
  const workerListLabel =
    workerNames.length > 0 ? workerNames.join(", ") : "registered workers";

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-panel modal-panel-auto-tunable"
        ref={dialogRef}
        role="dialog"
        aria-labelledby="auto-tunable-title"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3 id="auto-tunable-title">
            {isEnable ? "Enable auto mode" : "Edit auto mode parameters"}
          </h3>
          <button type="button" className="button ghost modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="modal-lead">
          {isEnable ? (
            <>
              Review tunable parameters before arming overnight orchestration for{" "}
              <strong>{workerListLabel}</strong>. Workers run only after{" "}
              <code>POST /api/v1/auto/start</code>.
            </>
          ) : (
            <>
              Parameters and search intervals used when <code>POST /api/v1/auto/start</code>{" "}
              dispatches {workerListLabel}. Changes apply to the next auto start.
            </>
          )}
        </p>
        {workerNames.length === 0 && (
          <div className="alert warn">
            No workers registered yet — add workers before enabling auto mode.
          </div>
        )}
        {running && (
          <div className="alert warn">
            An auto session is running — stop or restart the session before saving changes.
          </div>
        )}
        {error && <div className="alert error">{error}</div>}
        {hydrating && <div className="alert">Loading saved auto mode parameters…</div>}

        <form className="form modal-form modal-form-auto-tunable" onSubmit={(e) => void handleSubmit(e)}>
          <fieldset className="auto-mode-tunable-fieldset" disabled={hydrating || loading || running}>
          <div className="auto-mode-tunable-scroll">
            <div className="auto-mode-worker-algorithms">
            <span className="auto-mode-section-title">Worker settings</span>
            <p className="auto-mode-worker-algorithms-lead">
              Algorithm, parallel trials, and per-trial Docker CPU/RAM for each auto worker.
            </p>
            <div className="auto-mode-worker-settings-table-wrap">
              <table className="auto-mode-worker-settings-table">
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Algorithm</th>
                    <th>Concurrency</th>
                    <th>CPUs / trial</th>
                    <th>RAM (GB) / trial</th>
                  </tr>
                </thead>
                <tbody>
                  {workerNames.map((workerName) => (
                    <tr key={workerName}>
                      <td className="auto-mode-worker-settings-name">{workerName}</td>
                      <td>
                        <select
                          className="input-mono auto-mode-worker-algorithm-select"
                          value={workerAlgorithms[workerName] ?? "optuna"}
                          onChange={(e) =>
                            setWorkerAlgorithms({
                              ...workerAlgorithms,
                              [workerName]: e.target.value as AlgorithmOption,
                            })
                          }
                          disabled={loading || running}
                          aria-label={`Algorithm for ${workerName}`}
                        >
                          {ALGORITHM_OPTIONS.map((algorithm) => (
                            <option key={algorithm} value={algorithm}>
                              {algorithm}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          className="input-mono auto-mode-worker-resource-input"
                          value={workerConcurrency[workerName] ?? 1}
                          onChange={(e) =>
                            setWorkerConcurrency({
                              ...workerConcurrency,
                              [workerName]: clampConcurrency(Number(e.target.value)),
                            })
                          }
                          disabled={loading || running}
                          aria-label={`Concurrency for ${workerName}`}
                        >
                          {CONCURRENCY_OPTIONS.map((value) => (
                            <option key={value} value={value}>
                              {value}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <DeferredNumberInput
                          className="auto-mode-worker-resource-input input-mono"
                          value={workerTrialThreads[workerName] ?? 4}
                          min={1}
                          max={MAX_TRIAL_THREADS}
                          step={1}
                          onCommit={(value) =>
                            setWorkerTrialThreads({
                              ...workerTrialThreads,
                              [workerName]: clampTrialThreads(value ?? 4),
                            })
                          }
                          disabled={loading || running}
                          aria-label={`CPUs per trial for ${workerName}`}
                        />
                      </td>
                      <td>
                        <DeferredNumberInput
                          className="auto-mode-worker-resource-input input-mono"
                          value={workerTrialMemoryGb[workerName] ?? 6}
                          min={4}
                          max={128}
                          step={1}
                          onCommit={(value) =>
                            setWorkerTrialMemoryGb({
                              ...workerTrialMemoryGb,
                              [workerName]: clampTrialMemoryGb(value ?? 6),
                            })
                          }
                          disabled={loading || running}
                          aria-label={`RAM per trial for ${workerName}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <ConfParamPicker
            baseConf={referenceConf}
            tool={tool}
            selectedParams={selectedParams}
            paramIntervals={paramIntervals}
            onToggle={toggleParam}
            onIntervalChange={updateInterval}
          />
          </div>
          </fieldset>

          <div className="modal-actions modal-actions-auto-tunable">
            <button
              type="button"
              className="button ghost"
              onClick={resetDefaults}
              disabled={loading || hydrating || running}
            >
              Reset to defaults
            </button>
            <button type="button" className="button ghost" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            {isEnable && (
              <button
                type="button"
                className="button ghost"
                disabled={loading || hydrating || running || workerNames.length === 0}
                onClick={(e) => void handleSaveOnly(e)}
              >
                {loading ? "Saving…" : "Save parameters only"}
              </button>
            )}
            <button
              type="submit"
              className="button primary"
              disabled={loading || hydrating || running || workerNames.length === 0}
            >
              {loading
                ? isEnable
                  ? "Enabling…"
                  : "Saving…"
                : isEnable
                  ? "Save & enable auto mode"
                  : "Save parameters"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
