#!/usr/bin/env bash
set -o pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ZSH_NAME=""
source /opt/openfoam13/etc/bashrc
set -e
[ -f "$ROOT/.venv/bin/activate" ] && source "$ROOT/.venv/bin/activate"
ALLOW_MESH_WARNINGS="${ALLOW_MESH_WARNINGS:-false}"

if [ "$#" -gt 0 ]; then
    LEVELS=("$@")
else
    LEVELS=(quick balanced highFidelity)
fi

CONFIG="$ROOT/config/parameters.yaml"
BACKUP="$ROOT/config/parameters.yaml.meshStudyBackup"
cp "$CONFIG" "$BACKUP"
restore(){ cp "$BACKUP" "$CONFIG"; rm -f "$BACKUP"; }
trap restore EXIT

for level in "${LEVELS[@]}"; do
    case "$level" in
        quick|balanced|highFidelity) ;;
        *) echo "Unknown mesh level: $level"; exit 2 ;;
    esac

    echo
    echo "===== MESH STUDY: $level ====="

    python3 - "$CONFIG" "$level" <<'PY'
import sys
import yaml
from pathlib import Path
p = Path(sys.argv[1])
d = yaml.safe_load(p.read_text(encoding="utf-8"))
d.setdefault("mesh", {})["level"] = sys.argv[2]
p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
print("Selected mesh level:", sys.argv[2])
PY

    OUT="$ROOT/results/meshStudy/$level"
    rm -rf "$OUT"
    mkdir -p "$OUT"

    ALLOW_MESH_WARNINGS="$ALLOW_MESH_WARNINGS" \
        "$ROOT/scripts/run_case.sh" full

    cp "$CONFIG" "$OUT/parameters.yaml"

    for f in log.blockMesh log.snappyHexMesh log.checkMesh log.simpleFoam log.foamToVTK; do
        if [ -f "$ROOT/case/$f" ]; then
            cp "$ROOT/case/$f" "$OUT/"
        fi
    done

    if [ -f "$ROOT/case/constant/geometryMetrics.json" ]; then
        cp "$ROOT/case/constant/geometryMetrics.json" "$OUT/"
    fi

    if [ -f "$ROOT/case/system/snappyHexMeshDict" ]; then
        cp "$ROOT/case/system/snappyHexMeshDict" "$OUT/"
    fi

    [ -d "$ROOT/case/postProcessing" ] && cp -a "$ROOT/case/postProcessing" "$OUT/"
    [ -d "$ROOT/case/VTK" ] && cp -a "$ROOT/case/VTK" "$OUT/"
    [ -d "$ROOT/results/slices_vtk" ] && cp -a "$ROOT/results/slices_vtk" "$OUT/"
    [ -f "$ROOT/results/FormulaStudent_results.xlsx" ] && cp "$ROOT/results/FormulaStudent_results.xlsx" "$OUT/"
    [ -d "$ROOT/results/temp" ] && cp -a "$ROOT/results/temp" "$OUT/"

    echo "Archived: $OUT"
done

echo
echo "Mesh study completed: ${LEVELS[*]}"
echo "Configuration restored: $CONFIG"
