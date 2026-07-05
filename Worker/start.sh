#!/usr/bin/env bash
# Development launcher (same bind as production; use ./start-prod.sh for preflight + prod flags).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

resolve_venv_python() {
  local d
  for d in .venv venv; do
    if [[ -x "$ROOT_DIR/$d/bin/python" ]]; then
      echo "$ROOT_DIR/$d/bin/python"
      return 0
    fi
  done
  return 1
}

if ! VENV_PYTHON="$(resolve_venv_python)"; then
  echo "Virtualenv missing. Run ./setup.sh first." >&2
  exit 1
fi

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

if ! "$VENV_PYTHON" -c "import uvicorn" 2>/dev/null; then
  echo "uvicorn not installed in virtualenv. Run ./setup.sh" >&2
  exit 1
fi

GRACEFUL_SHUTDOWN="${WORKER_GRACEFUL_SHUTDOWN_SEC:-120}"

echo "Worker status lines every \${WORKER_STATUS_INTERVAL_SEC:-20}s (GET /best polls hidden from access log)"

exec "$VENV_PYTHON" -m uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --timeout-graceful-shutdown "$GRACEFUL_SHUTDOWN"
