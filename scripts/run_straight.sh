#!/usr/bin/env bash

set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export ZSH_NAME=""

source /opt/openfoam13/etc/bashrc
set -e

if [ -f "$ROOT/.venv/bin/activate" ]; then
    source "$ROOT/.venv/bin/activate"
fi

echo "=== FormulaStudentCFD straight-line test ==="
echo "Project root: $ROOT"

mkdir -p "$ROOT/results"
echo "=== Writing configuration ==="
python3 "$ROOT/scripts/write_effective.py"

echo "=== Preparing geometry ==="
python3 "$ROOT/scripts/prepare_case.py"

echo "=== Generating OpenFOAM dictionaries ==="
python3 "$ROOT/scripts/generate_case_files.py"
python3 "$ROOT/scripts/generate_snappy_v13.py"

echo "=== Generating turbulence fields ==="
python3 "$ROOT/scripts/generate_turbulence_fields.py"

echo "=== Enabling mesh layers ==="
python3 "$ROOT/scripts/enable_layers.py"

echo "=== Generating force functions ==="
python3 "$ROOT/scripts/generate_control.py"
python3 "$ROOT/scripts/add_forces_objects.py"

echo "=== Creating time-zero directory ==="
rm -rf "$ROOT/case/0"
cp -a "$ROOT/case/0.orig" "$ROOT/case/0"
python3 "$ROOT/scripts/apply_wheel_rotation.py"
touch "$ROOT/case/case.foam"

cd "$ROOT/case"

echo "=== Running blockMesh ==="
blockMesh 2>&1 | tee log.blockMesh

echo "=== Running snappyHexMesh ==="
snappyHexMesh -overwrite 2>&1 | tee log.snappyHexMesh
echo "=== Running checkMesh ==="
checkMesh 2>&1 | tee log.checkMesh

echo "=== Running simpleFoam ==="
simpleFoam 2>&1 | tee log.simpleFoam

echo "=== Straight-line test finished ==="
