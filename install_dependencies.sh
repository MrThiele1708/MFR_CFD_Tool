#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chmod +x scripts/*.sh scripts/*.py 2>/dev/null || true

echo
 echo "Python environment ready: $ROOT/.venv"
 echo "Check OpenFOAM separately with: source /opt/openfoam13/etc/bashrc"
