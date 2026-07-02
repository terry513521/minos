#!/usr/bin/env bash
# Development launcher (same bind as production; use ./start-prod.sh for preflight + prod flags).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "Virtualenv missing. Run ./setup.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="${WORKER_HOST:-0.0.0.0}"
PORT="${WORKER_PORT:-8080}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  HOST="${WORKER_HOST:-$HOST}"
  PORT="${WORKER_PORT:-$PORT}"
fi

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
