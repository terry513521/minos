import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export const WORKERS_CHANGED_EVENT = "effortless:workers-changed";

function deriveBaseUrl(healthUrl: string): string {
  const trimmed = healthUrl.trim().replace(/\/+$/, "");
  if (trimmed.toLowerCase().endsWith("/health")) {
    return trimmed.slice(0, -"/health".length);
  }
  return trimmed;
}

interface AddWorkerModalProps {
  open: boolean;
  onClose: () => void;
}

function parseApiError(raw: string): string {
  try {
    const data = JSON.parse(raw) as { detail?: string | { msg?: string }[] };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {
    /* use raw */
  }
  return raw || "Failed to add worker";
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
      if (err instanceof Error) setError(parseApiError(err.message));
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
                  setBaseUrl(deriveBaseUrl(next));
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
          <p className="modal-hint">Main API must include the port (e.g. <code>:8080</code>), same host as health check.</p>

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
