import { FormEvent, useEffect, useState } from "react";
import { api, WorkerRecord } from "../api/client";
import { deriveBaseUrlFromHealth, parseApiError } from "../utils/workerUrls";

interface WorkerEndpointsEditorProps {
  worker: WorkerRecord;
  onUpdated: (worker: WorkerRecord) => void;
}

export function WorkerEndpointsEditor({ worker, onUpdated }: WorkerEndpointsEditorProps) {
  const [editing, setEditing] = useState(false);
  const [healthUrl, setHealthUrl] = useState(worker.health_url ?? "");
  const [baseUrl, setBaseUrl] = useState(worker.base_url ?? "");
  const [baseUrlTouched, setBaseUrlTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (editing) return;
    setHealthUrl(worker.health_url ?? "");
    setBaseUrl(worker.base_url ?? "");
    setBaseUrlTouched(false);
    setError(null);
    setSaved(false);
  }, [worker.id, worker.health_url, worker.base_url, editing]);

  const dirty =
    healthUrl.trim() !== (worker.health_url ?? "").trim() ||
    baseUrl.trim() !== (worker.base_url ?? "").trim();

  function resetDraft() {
    setHealthUrl(worker.health_url ?? "");
    setBaseUrl(worker.base_url ?? "");
    setBaseUrlTouched(false);
    setError(null);
    setSaved(false);
  }

  function handleCancel() {
    resetDraft();
    setEditing(false);
  }

  function handleStartEdit() {
    resetDraft();
    setEditing(true);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!dirty) {
      setEditing(false);
      return;
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.updateWorker(worker.id, {
        health_url: healthUrl.trim(),
        base_url: baseUrl.trim(),
      });
      onUpdated(updated);
      setHealthUrl(updated.health_url ?? "");
      setBaseUrl(updated.base_url ?? "");
      setBaseUrlTouched(false);
      setSaved(true);
      setEditing(false);
    } catch (err) {
      const message = err instanceof Error ? parseApiError(err.message) : "Failed to save endpoints";
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="worker-endpoints-form" onSubmit={handleSave}>
      <div className="worker-endpoints-head">
        <span className="worker-endpoints-title">Endpoints</span>
        {!editing && (
          <button
            type="button"
            className="button ghost worker-endpoints-edit"
            onClick={handleStartEdit}
          >
            Edit
          </button>
        )}
      </div>

      <dl className="worker-endpoints">
        <div>
          <dt>Health</dt>
          <dd>
            <input
              className="input-mono worker-endpoint-input"
              value={healthUrl}
              disabled={!editing}
              onChange={(e) => {
                const next = e.target.value;
                setHealthUrl(next);
                setSaved(false);
                if (!baseUrlTouched) {
                  setBaseUrl(deriveBaseUrlFromHealth(next));
                }
              }}
              placeholder="http://192.168.1.10:8080/health"
              aria-label={`${worker.name} health URL`}
            />
          </dd>
        </div>
        <div>
          <dt>Main API</dt>
          <dd>
            <input
              className="input-mono worker-endpoint-input"
              value={baseUrl}
              disabled={!editing}
              onChange={(e) => {
                setBaseUrlTouched(true);
                setBaseUrl(e.target.value);
                setSaved(false);
              }}
              placeholder="http://192.168.1.10:8080"
              aria-label={`${worker.name} main API URL`}
            />
          </dd>
        </div>
      </dl>

      {error && <div className="alert error worker-endpoints-error">{error}</div>}
      {saved && !editing && !error && (
        <div className="worker-endpoints-saved">Endpoints saved</div>
      )}

      {editing && (
        <div className="worker-endpoints-actions">
          <button
            type="submit"
            className="button ghost worker-endpoints-save"
            disabled={saving || !healthUrl.trim() || !baseUrl.trim() || !dirty}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            className="button ghost worker-endpoints-cancel"
            onClick={handleCancel}
            disabled={saving}
          >
            Cancel
          </button>
        </div>
      )}
    </form>
  );
}
