# Effortless — Config Optimization Control Plane

Main server for the standalone config-optimization system ([plan](../docs/config-optimization-plan.md)).

```
Main/
├── backend/     FastAPI control plane
└── frontend/    React web console
```

## Platform round polling

Effortless polls the Minos platform like the miner (`POST /v2/round-status` or `/v2/demo/round-status`):

- **Backend** caches the result and refreshes every `MAIN_PLATFORM_POLL_SECONDS` (default 10s).
- **Frontend** reads `GET /api/v1/platform/round` (instant) + WebSocket pushes on change.

Configure in `backend/.env` (see `.env.example`). Default is **demo mode** with an ephemeral keypair — no wallet required.

```bash
MAIN_PLATFORM_ENABLED=true
MAIN_PLATFORM_DEMO_MODE=true
```

For live rounds, set `MAIN_PLATFORM_DEMO_MODE=false` and your Bittensor wallet name/hotkey.

## History import

Effortless loads Minos tuning exports (`round_history.json`) into SQLite for base-config selection.

Default paths (override with `MAIN_HISTORY_JSON_PATHS`, comma-separated):

- `.../instances/gatk/tuning/data/round_history.json` — GATK HaplotypeCaller history
- `.../instances/newgatk/tuning/data/round_history.json` — additional GATK + bcftools history

On first startup (empty `round_history` table), scored rows (`combined_final`) are imported automatically. Re-import manually:

```bash
curl -X POST 'http://localhost:8000/api/v1/history/import?replace=true'
```

### Save new history (SQL database)

Effortless uses **SQLite** via SQLAlchemy (`MAIN_DATABASE_URL`, default `main.db`). The `round_history` table stores `(window, tool, conf, score)` for candidate selection.

**Create a row:**

```bash
curl -X POST http://localhost:8000/api/v1/history \
  -H 'Content-Type: application/json' \
  -d '{
    "window": "chr20:10000000-15000000",
    "tool": "gatk",
    "score": 0.82,
    "conf": {"gatk_options": {"pcr_indel_model": "NONE"}}
  }'
```

**Save a run winner** (when `winner_conf` / `winner_score` exist):

```bash
curl -X POST http://localhost:8000/api/v1/history/from-run/{run_id}
```

The UI exposes **Sync JSON** in the history panel. Save-winner UI is planned when optimization runs complete.

## Quick start

### Backend

```bash
cd Main/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd Main/frontend
npm install
npm run dev
```

Web UI: http://localhost:5173 (proxies `/api` → backend)

## Environment

Copy `backend/.env.example` to `backend/.env` and adjust if needed.
