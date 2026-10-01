#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${ROOT}/.distribution_stage"
ZIP="${ROOT}/FormulaStudentCFD_v0_8_package.zip"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"

rsync -a \
    --exclude='.venv/' \
    --exclude='case/' \
    --exclude='results/' \
    --exclude='case_single_part/' \
    --exclude='results_single_part/' \
    --exclude='geometry/production_mapped/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='*:Zone.Identifier' \
    "$ROOT/" "$STAGE/FormulaStudentCFD_v0_8/"

mkdir -p \
    "$STAGE/FormulaStudentCFD_v0_8/case" \
    "$STAGE/FormulaStudentCFD_v0_8/results" \
    "$STAGE/FormulaStudentCFD_v0_8/case_single_part" \
    "$STAGE/FormulaStudentCFD_v0_8/results_single_part"

python3 - "$STAGE/FormulaStudentCFD_v0_8" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])

for name in (
    'config/parameters.yaml',
    'config/parameters_single_part.yaml',
):
    path = root / name
    if not path.exists():
        continue
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    data.setdefault('project', {})['windowsResults'] = ''
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
PY

cp "$ROOT/README_SETUP.md" "$STAGE/FormulaStudentCFD_v0_8/README_SETUP.md" 2>/dev/null || true
cp "$ROOT/requirements.txt" "$STAGE/FormulaStudentCFD_v0_8/requirements.txt" 2>/dev/null || true

chmod +x "$STAGE/FormulaStudentCFD_v0_8/scripts/"*.sh 2>/dev/null || true

(cd "$STAGE" && zip -r "$ZIP" FormulaStudentCFD_v0_8 >/dev/null)
rm -rf "$STAGE"

echo "Created: $ZIP"
