import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { deriveBaseUrlFromHealth, parseApiError } from "../utils/workerUrls";

export const WORKERS_CHANGED_EVENT = "effortless:workers-changed";
export const WORKERS_STOP_ALL_EVENT = "effortless:workers-stop-all";
export const WORKERS_START_ALL_EVENT = "effortless:workers-start-all";
export const WORKERS_START_ALL_RESULT_EVENT = "effortless:workers-start-all-result";

export interface WorkersStartAllResultDetail {
  started: number;
  failed: number;
  skipped: number;
}

interface AddWorkerModalProps {
  open: boolean;
  onClose: () => void;
}

function parseApiErrorFromRegister(raw: string): string {
  return parseApiError(raw) || "Failed to add worker";
}

export function AddWorkerModal({ open, onClose }: AddWorkerModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [name, setName] = useState("");
  const [healthUrl, setHealthUrl] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [baseUrlTouched, setBaseUrlTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setToken(null);
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setToken(null);
    setLoading(true);
    try {
      const result = await api.registerWorker({
        name: name.trim(),
        health_url: healthUrl.trim(),
        base_url: baseUrl.trim(),
      });
      setToken(result.registration_token);
      window.dispatchEvent(new Event(WORKERS_CHANGED_EVENT));
      setName("");
      setHealthUrl("");
      setBaseUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add worker");
      if (err instanceof Error) setError(parseApiErrorFromRegister(err.message));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-panel"
        ref={dialogRef}
        role="dialog"
        aria-labelledby="add-worker-title"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="add-worker-title">Add worker</h2>
          <button type="button" className="button ghost modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="modal-lead">Register an optimizer subsystem with health and main API endpoints.</p>

        <form className="form modal-form" onSubmit={handleSubmit}>
          <label>
            <span className="field-label">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="optimizer-1"
              required
            />
          </label>
          <label>
            <span className="field-label">Health check API</span>
            <input
              className="input-mono"
              value={healthUrl}
              onChange={(e) => {
                const next = e.target.value;
                setHealthUrl(next);
                if (!baseUrlTouched) {
                  setBaseUrl(deriveBaseUrlFromHealth(next));
                }
              }}
              placeholder="http://192.168.1.10:8080/health"
              required
            />
          </label>
          <label>
            <span className="field-label">Main API</span>
            <input
              className="input-mono"
              value={baseUrl}
              onChange={(e) => {
                setBaseUrlTouched(true);
                setBaseUrl(e.target.value);
              }}
              placeholder="http://192.168.1.10:8080"
              required
            />
          </label>
          <p className="modal-hint">
            Health check runs from the <strong>Main server</strong>, not your browser. Use an address
            the control plane can reach (public IP, same LAN as Main, or <code>127.0.0.1</code> if
            worker runs on the same host as Main).
          </p>

          {error && <div className="alert error">{error}</div>}
          {token && (
            <div className="alert ok">
              Worker registered. Token: <code>{token}</code>
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="button ghost" onClick={onClose}>
              {token ? "Close" : "Cancel"}
            </button>
            {!token && (
              <button type="submit" className="button primary" disabled={loading}>
                {loading ? "Checking…" : "Add worker"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
