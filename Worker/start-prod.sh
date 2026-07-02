#!/usr/bin/env bash
# Production launcher for the Effortless optimizer worker API.
# Binds 0.0.0.0 by default; use a single uvicorn process (in-memory job state).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "error: virtualenv missing. Run ./setup.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="${WORKER_HOST:-0.0.0.0}"
PORT="${WORKER_PORT:-8080}"
LOG_LEVEL="${WORKER_LOG_LEVEL:-info}"
WORKER_NAME="${WORKER_NAME:-optimizer-1}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  HOST="${WORKER_HOST:-$HOST}"
  PORT="${WORKER_PORT:-$PORT}"
  LOG_LEVEL="${WORKER_LOG_LEVEL:-$LOG_LEVEL}"
  WORKER_NAME="${WORKER_NAME:-$WORKER_NAME}"
fi

detect_public_ip() {
  local ip=""
  ip="$(curl -fsS --max-time 3 -4 ifconfig.me 2>/dev/null || true)"
  if [[ -n "$ip" ]]; then
    echo "$ip"
    return
  fi
  ip="$(curl -fsS --max-time 3 ifconfig.me 2>/dev/null || true)"
  if [[ -n "$ip" ]]; then
    echo "$ip"
    return
  fi
  hostname -I 2>/dev/null | awk '{print $1}'
}

if ! command -v docker >/dev/null 2>&1; then
  echo "warning: docker not found — GATK optimizations require Docker." >&2
elif ! docker info >/dev/null 2>&1; then
  echo "warning: docker daemon not reachable — start Docker before dispatching jobs." >&2
fi

if [[ "${WORKER_SKIP_VERIFY:-}" != "1" ]]; then
  if ! python scripts/verify_datasets.py; then
    echo "warning: dataset verification failed — optimizations may error until assets are ready." >&2
  fi
fi

PUBLIC_IP="$(detect_public_ip)"
BASE_URL="http://${PUBLIC_IP:-<host>}:${PORT}"

echo "== Effortless Worker (production) =="
echo "  name:      ${WORKER_NAME}"
echo "  bind:      ${HOST}:${PORT}"
echo "  log level: ${LOG_LEVEL}"
echo
echo "  health:    ${BASE_URL}/health"
echo "  best:      ${BASE_URL}/best"
echo "  optimize:  POST ${BASE_URL}/optimize"
echo "  stop:      POST ${BASE_URL}/stop"
echo
echo "Register in Main control plane:"
echo "  health_url = ${BASE_URL}/health"
echo "  base_url   = ${BASE_URL}"
echo

exec uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level "$LOG_LEVEL" \
  --no-use-colors
