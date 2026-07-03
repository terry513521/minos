#!/usr/bin/env bash
# Build a portable Worker archive for copying to another machine.
#
# Usage:
#   ./package.sh              # source only (~1 MB) — run ./setup.sh on target
#   ./package.sh --with-datasets   # includes datasets/ (~5+ GB) — ready after venv
#   ./package.sh --output /tmp
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

INCLUDE_DATASETS=0
OUTPUT_DIR="$ROOT_DIR/dist"
STAMP="$(date -u +%Y%m%d)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-datasets)
      INCLUDE_DATASETS=1
      shift
      ;;
    --output)
      OUTPUT_DIR="${2:?missing path after --output}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PKG_NAME="effortless-worker-${STAMP}"
if [[ "$INCLUDE_DATASETS" -eq 1 ]]; then
  PKG_NAME="${PKG_NAME}-full"
else
  PKG_NAME="${PKG_NAME}-src"
fi

STAGE="$WORK/$PKG_NAME"
mkdir -p "$STAGE"

TAR_EXCLUDES=(
  --exclude='.venv'
  --exclude='.env'
  --exclude='runs'
  --exclude='__pycache__'
  --exclude='*.py[cod]'
  --exclude='.pytest_cache'
  --exclude='dist'
  --exclude='datasets/vcf_cache'
)

if [[ "$INCLUDE_DATASETS" -eq 0 ]]; then
  TAR_EXCLUDES+=(--exclude='./datasets')
fi

echo "==> Staging $PKG_NAME"
tar -C "$ROOT_DIR" "${TAR_EXCLUDES[@]}" -cf - . | tar -C "$STAGE" -xf -

if [[ "$INCLUDE_DATASETS" -eq 0 ]]; then
  mkdir -p "$STAGE/datasets"
  cat > "$STAGE/datasets/README.txt" <<'EOF'
Datasets are not included in the source package.

On the target machine, from the Worker directory:
  ./setup.sh

That downloads reference FASTA, SDF, Docker images, benchmark BAMs, and GIAB truth.
EOF
fi

cat > "$STAGE/INSTALL.txt" <<'EOF'
Effortless Worker — install on a new machine
============================================

Requirements:
  - Linux, Python 3.10+
  - Docker (for GATK / hap.py)
  - ~12 GB RAM recommended (concurrency=1); more for parallel trials

Optimization algorithms (set in Main dispatch or POST /optimize):
  optuna, gp, random, sobol, lhs
  Python deps: optuna>=3.6 (TPE + GP), scipy>=1.11 (Sobol + LHS)

Quick start:
  tar -xzf effortless-worker-*-src.tar.gz
  cd effortless-worker-*
  cp .env.example .env    # edit WORKER_NAME, chromosomes, etc.
  ./setup.sh              # venv + datasets + Docker images
  ./start-prod.sh         # binds 0.0.0.0:8080

Register in Main control plane:
  health_url = http://<this-host>:8080/health
  base_url   = http://<this-host>:8080

Optional systemd:
  sudo cp deploy/effortless-worker.service /etc/systemd/system/
  # edit paths/User in the unit file, then:
  sudo systemctl daemon-reload
  sudo systemctl enable --now effortless-worker
EOF

ARCHIVE="$OUTPUT_DIR/${PKG_NAME}.tar.gz"
echo "==> Creating $ARCHIVE"
tar -C "$WORK" -czf "$ARCHIVE" "$PKG_NAME"

BYTES="$(wc -c < "$ARCHIVE" | tr -d ' ')"
if command -v numfmt >/dev/null 2>&1; then
  SIZE="$(numfmt --to=iec-i --suffix=B "$BYTES")"
else
  SIZE="${BYTES} bytes"
fi

echo
echo "Package ready:"
echo "  $ARCHIVE"
echo "  size: $SIZE"
echo
echo "Copy to another host:"
echo "  scp $ARCHIVE user@remote:/opt/"
echo "  ssh user@remote 'cd /opt && tar -xzf ${PKG_NAME}.tar.gz && cd $PKG_NAME && ./setup.sh'"
echo
if [[ "$INCLUDE_DATASETS" -eq 0 ]]; then
  echo "Tip: use --with-datasets for an offline-ready bundle (large, ~5+ GB)."
else
  echo "Full bundle includes datasets/; still run ./setup.sh once for venv + Docker images."
fi
echo
echo "GitHub alternative (after Worker is pushed):"
echo "  git clone https://github.com/minos-protocol/minos_subnet.git"
echo "  cd minos_subnet/Worker && cp .env.example .env && ./setup.sh && ./start-prod.sh"
