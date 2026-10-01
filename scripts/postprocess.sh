#!/usr/bin/env bash

set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export ZSH_NAME=""

source /opt/openfoam13/etc/bashrc
set -e

if [ -f "$ROOT/.venv/bin/activate" ]; then
    source "$ROOT/.venv/bin/activate"
fi

mkdir -p "$ROOT/results"

cd "$ROOT/case"

echo "=== Running yPlus post-processing ==="
postProcess -func yPlus 2>&1 | tee "$ROOT/results/log.yPlus" || true

echo "=== Running residual post-processing ==="
postProcess -func residuals 2>&1 | tee "$ROOT/results/log.residuals" || true

cd "$ROOT"

echo "=== Generating slices ==="
PYTHONPATH=/usr/lib/python3/dist-packages /usr/bin/pvpython scripts/generate_slices.py \
    2>&1 | tee "$ROOT/results/log.slices" || true

echo "=== Creating Excel report ==="
python3 scripts/create_excel.py \
    2>&1 | tee "$ROOT/results/log.excel"

echo "=== Post-processing finished ==="
