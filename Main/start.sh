#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${MAIN_HOST:-0.0.0.0}"
PORT="${MAIN_PORT:-8000}"

echo "==> Building frontend"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build

echo "==> Starting control plane on ${HOST}:${PORT} (API + static UI)"
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export MAIN_HOST="$HOST"
export MAIN_PORT="$PORT"
export MAIN_SERVE_FRONTEND=true
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
