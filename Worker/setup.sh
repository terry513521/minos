#!/usr/bin/env bash
# Bootstrap Python environment for the Effortless worker API.
# Copy this Worker/ folder to any machine and run: ./setup.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$("$PYTHON" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')"
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
  echo "error: Python 3.10+ required (found $PY_VERSION)." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv in .venv …"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Fix hard-coded paths if this Worker folder was moved after venv creation.
python -m venv --upgrade .venv 2>/dev/null || true

python -m pip install --upgrade pip
pip install -r requirements.txt

merge_env_defaults() {
  local key line
  [[ -f .env.example ]] || return 0
  [[ -f .env ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    key="${line%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ -n "$key" ]] || continue
    if ! grep -q "^${key}=" .env 2>/dev/null; then
      echo "$line" >> .env
      echo "  added missing .env key: ${key}"
    fi
  done < .env.example
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
else
  echo "Updating .env with any new keys from .env.example …"
  merge_env_defaults
fi

chmod +x start.sh start-prod.sh scripts/setup_assets.py scripts/verify_datasets.py

if ! command -v docker >/dev/null 2>&1; then
  echo
  echo "warning: docker not found — GATK, hap.py, and persistent containers require Docker." >&2
elif ! docker info >/dev/null 2>&1; then
  echo
  echo "warning: docker daemon not reachable — start Docker before running optimizations." >&2
fi

echo
echo "== Datasets and Docker images =="
echo "Downloads GRCh38 reference, SDF, variant-caller images, and (optionally) benchmark BAMs."
echo
echo "Benchmark mode (default): fixed HG002 BAM + GIAB truth; only the round region comes from the UI."
echo "BAM lookup: datasets/bams/{chr}.bam | HG002_{chr}_{start}-{end}.bam | HG002_{chr}_minos_window.bam"
echo "Truth:      datasets/data/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
echo
echo "Tune Worker/.env before the asset step if needed:"
echo "  WORKER_CHROMOSOMES=chr20,chr21,chr22"
echo "  WORKER_DOWNLOAD_GIAB_SLICES=true   # slice HG002 BAM from NCBI FTP (chr22 too)"
echo "  WORKER_ADAPTIVE_MAX_TRIALS=44      # 1 base + N search trials"
echo "  WORKER_BENCHMARK_SUBWINDOW_MB=5    # full 5M round (0 = entire dispatch)"
echo "  WORKER_TRIAL_THREADS=4             # CPUs per concurrent slot"
echo "  WORKER_TRIAL_MEMORY_GB=6           # RAM per concurrent slot"
echo "  Algorithms: optuna, gp, random, sobol, lhs (via dispatch)"
echo

if [[ "${WORKER_SKIP_ASSETS:-}" == "1" ]]; then
  echo "WORKER_SKIP_ASSETS=1 — skipping dataset and Docker setup."
else
  python scripts/setup_assets.py "$@"
fi

mkdir -p datasets/vcf_cache runs

echo
echo "== Dataset check =="
if python scripts/verify_datasets.py; then
  echo "Datasets look ready."
else
  echo "warning: verify_datasets reported missing files — see output above." >&2
fi

echo
echo "Worker environment ready."
echo "  datasets/reference/{chr}/     GRCh38 FASTA + SDF"
echo "  datasets/giab/bam/          HG002 regional slices (NCBI FTP; includes chr22)"
echo "  datasets/bams/              optional legacy benchmark BAM(s)"
echo "  datasets/data/              GIAB truth VCF"
echo "  datasets/vcf_cache/         scored VCF cache (per config)"
echo "  runs/                       ephemeral job artifacts"
echo
echo "API:"
echo "  Health:  http://<this-host>:8080/health"
echo "  Best:    GET  http://<this-host>:8080/best"
echo "  Optimize POST http://<this-host>:8080/optimize"
echo
echo "Start the server:"
echo "  ./start.sh          # development"
echo "  ./start-prod.sh     # production (bind 0.0.0.0, preflight checks)"
echo
echo "Optional systemd unit: deploy/effortless-worker.service"
echo "Portable package:      ./package.sh  (creates dist/effortless-worker-*-src.tar.gz)"
echo
echo "Register in Effortless UI:"
echo "  health_url = http://<this-host>:8080/health"
echo "  base_url   = http://<this-host>:8080"
echo
echo "Resource hint: concurrency N with 4 CPUs + 7 GB/slot needs ~N×7 GB RAM for GATK"
echo "(plus hap.py). Use concurrency=1 on ~8–11 GB hosts."
