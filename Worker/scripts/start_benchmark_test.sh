#!/usr/bin/env bash
# Preflight datasets, then run the sample A-vs-B GIAB benchmark comparison.
#
# Usage:
#   ./scripts/start_benchmark_test.sh              # 1 Mb crop (fast smoke)
#   ./scripts/start_benchmark_test.sh --full       # full 5 Mb chr21 window
#   ./scripts/start_benchmark_test.sh --rich -v    # extra hap.py metrics + debug logs
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  echo "Virtualenv missing. Run ./setup.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "== Worker benchmark test =="
echo "Root: $ROOT_DIR"
echo

python scripts/verify_datasets.py
VERIFY_RC=$?
if [[ $VERIFY_RC -ne 0 ]]; then
  echo
  echo "Dataset preflight failed. Run ./setup.sh or fix missing reference under datasets/reference/." >&2
  exit "$VERIFY_RC"
fi

SUBWINDOW_MB=1
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --full)
      SUBWINDOW_MB=0
      ;;
    *)
      EXTRA_ARGS+=("$arg")
      ;;
  esac
done

WINDOW="${BENCHMARK_TEST_WINDOW:-chr21:35444092-40444092}"
CONFIG_A="${BENCHMARK_TEST_CONFIG_A:-scripts/samples/config_baseline.json}"
CONFIG_B="${BENCHMARK_TEST_CONFIG_B:-scripts/samples/config_tuned.json}"

echo
echo "== Compare two configs =="
echo "Window:      $WINDOW"
echo "Subwindow:   ${SUBWINDOW_MB} Mb (use --full for entire window)"
echo "Config A:    $CONFIG_A"
echo "Config B:    $CONFIG_B"
echo

exec python scripts/compare_benchmark.py \
  --window "$WINDOW" \
  --subwindow-mb "$SUBWINDOW_MB" \
  --config-a "$CONFIG_A" \
  --config-b "$CONFIG_B" \
  "${EXTRA_ARGS[@]}"
