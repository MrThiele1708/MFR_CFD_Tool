#!/usr/bin/env bash
# FormulaStudentCFD runner with complete ParaView case copy.
set -o pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ZSH_NAME=""
source /opt/openfoam13/etc/bashrc
set -e
[ -f "$ROOT/.venv/bin/activate" ] && source "$ROOT/.venv/bin/activate"

CONFIG_PATH="${CFD_CONFIG:-$ROOT/config/parameters.yaml}"

if [[ "$CONFIG_PATH" != /* ]]; then
    CONFIG_PATH="$ROOT/$CONFIG_PATH"
fi

CONFIG_PATH="$(realpath "$CONFIG_PATH")"
export CFD_CONFIG="$CONFIG_PATH"

CASE_DIR="$(
    python3 "$ROOT/scripts/select_project_path.py" case
)"

RESULTS_DIR="$(
    python3 "$ROOT/scripts/select_project_path.py" results
)"

MANIFEST_PATH="$(
    python3 "$ROOT/scripts/select_project_path.py" manifest
)"

export CASE_DIR
export RESULTS_DIR
export CFD_CASE="$CASE_DIR"
export CFD_RESULTS="$RESULTS_DIR"
export CFD_MANIFEST="$MANIFEST_PATH"

mkdir -p "$RESULTS_DIR"

MODE="${1:-full}"
ALLOW_MESH_WARNINGS="${ALLOW_MESH_WARNINGS:-false}"
PARALLEL="${PARALLEL:-false}"
NPROCS="${NPROCS:-6}"
mkdir -p "$RESULTS_DIR"
log_step(){ echo; echo "=== $1 ==="; }
SOLVER=$(python3 - "$CONFIG_PATH" <<'PY'
import sys
import yaml
with open(sys.argv[1], encoding="utf-8") as f:
    config = yaml.safe_load(f)
solver = config.get("solver", {})
mode = solver.get("mode", "steady")
print(solver.get("transient", "pimpleFoam") if mode == "transient" else solver.get("steady", "simpleFoam"))
PY
)
prepare(){
    log_step "Clean old numeric time directories"
    python3 "$ROOT/scripts/clear_numeric_times.py"
 log_step "Prepare case"
python3 "$ROOT/scripts/resolve_single_part_geometry.py"
python3 "$ROOT/scripts/auto_map_geometry.py"
 python3 "$ROOT/scripts/write_effective.py"
 python3 "$ROOT/scripts/prepare_case.py"
GLOBAL_MORPH_ENABLED=$(python3 - "$CONFIG_PATH" <<'PY_GLOBAL_MORPH'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream)

print(
    str(
        bool(
            config.get("geometry", {})
            .get("globalAssemblyMorph", {})
            .get("enabled", False)
        )
    ).lower()
)
PY_GLOBAL_MORPH
)

if [ "$GLOBAL_MORPH_ENABLED" = "true" ]; then
    python3 "$ROOT/scripts/apply_global_assembly_rigid_transition.py"
else
    python3 "$ROOT/scripts/apply_contact_aware_morph.py"
fi

if [ "$GLOBAL_MORPH_ENABLED" = "true" ]; then
    log_step "Validate final transformed geometry"

    python3 "$ROOT/scripts/validate_combined_geometry.py" \
        --input "$CASE_DIR/constant/triSurface" \
        --units m \
        --exclude assembly.stl \
                  radiator_left_volume.stl \
                  radiator_right_volume.stl \
        --output "$RESULTS_DIR/final_case_geometry_check.json" \
        --strict
fi
 python3 "$ROOT/scripts/generate_case_files.py"
python3 "$ROOT/scripts/generate_physical_properties.py"
 python3 "$ROOT/scripts/generate_snappy_v13.py"
bash "$ROOT/scripts/run_surface_features.sh"
 python3 "$ROOT/scripts/generate_turbulence_fields.py"
 python3 "$ROOT/scripts/enable_layers.py"
 python3 "$ROOT/scripts/generate_control.py"
python3 "$ROOT/scripts/apply_solver_control.py" --mode fresh
 python3 "$ROOT/scripts/add_forces_objects.py"
}
mesh(){
 rm -rf "$CASE_DIR/constant/polyMesh" "$CASE_DIR/0"
 cp -a "$CASE_DIR/0.orig" "$CASE_DIR/0"
 touch "$CASE_DIR/case.foam"
 cd "$CASE_DIR"
 log_step "blockMesh"
 blockMesh 2>&1 | tee log.blockMesh
 log_step "snappyHexMesh"
 snappyHexMesh -overwrite 2>&1 | tee log.snappyHexMesh
 log_step "checkMesh (no functionObjects)"
 set +e
 checkMesh -noFunctionObjects -allGeometry -allTopology 2>&1 | tee log.checkMesh
 status=${PIPESTATUS[0]}
 set -e
 echo "checkMesh exit code: $status"
 if grep -q "Mesh OK" log.checkMesh; then
 echo "checkMesh passed."
 else
 case "${ALLOW_MESH_WARNINGS:-false}" in
 true|TRUE|1|yes|YES) echo "WARNING: continuing with allowed mesh warnings.";;
 *) echo "Stopping: checkMesh did not report Mesh OK."; exit 2;;
 esac
 fi

    log_step "Generate radiator source dictionaries"
    python3 "$ROOT/scripts/generate_radiator_sources.py"

    if [ -f "$CASE_DIR/system/topoSetDict" ]; then
        cd "$CASE_DIR"

        log_step "Create radiator cell zones"
        topoSet 2>&1 | tee log.topoSet

        cd "$ROOT"
    fi

 cd "$ROOT"
}
reset_solver(){
 rm -rf "$CASE_DIR/0" "$CASE_DIR/postProcessing" "$CASE_DIR/VTK"
 cp -a "$CASE_DIR/0.orig" "$CASE_DIR/0"
 touch "$CASE_DIR/case.foam"
 python3 "$ROOT/scripts/apply_wheel_rotation.py"
}
solve(){
    log_step "Clean old numeric time directories"
    python3 "$ROOT/scripts/clear_numeric_times.py"
 python3 "$ROOT/scripts/apply_solver_control.py" --mode fresh
 reset_solver
 cd "$CASE_DIR"
 log_step "Solver: $SOLVER"
 if [ "$PARALLEL" = "true" ]; then
 python3 "$ROOT/scripts/generate_decompose_par.py"
 decomposePar -force 2>&1 | tee log.decomposePar
 mpirun -np "$NPROCS" "$SOLVER" -parallel 2>&1 | tee "log.$SOLVER"
 reconstructPar -latestTime 2>&1 | tee log.reconstructPar
 else
 "$SOLVER" 2>&1 | tee "log.$SOLVER"
 fi
 cd "$ROOT"
}
postprocess(){
 local latest_complete
 latest_complete=$(python3 "$ROOT/scripts/select_restart_time.py")

 cd "$CASE_DIR"

 rm -rf "$CASE_DIR/VTK"

 log_step "foamToVTK complete time: $latest_complete"
 foamToVTK -time "$latest_complete" 2>&1 | tee log.foamToVTK

 cd "$ROOT"

 rm -rf "$RESULTS_DIR/slices_vtk"

 log_step "VTK slices"
 PYTHONPATH=/usr/lib/python3/dist-packages \
 /usr/bin/pvpython scripts/generate_slices_vtk.py \
 2>&1 | tee results/log.slices_vtk

 log_step "Excel"
 if [ -f "$ROOT/scripts/create_excel_v6.py" ]; then
     python3 scripts/create_excel_v6.py \
         2>&1 | tee results/log.excel
 else
     python3 scripts/create_excel.py \
         2>&1 | tee results/log.excel
 fi
}

copy_temp(){
 log_step "Copy results to results/temp"
 rm -rf "$RESULTS_DIR/temp"
 mkdir -p "$RESULTS_DIR/temp"

 PVCASE="$RESULTS_DIR/temp/paraViewCase"
 mkdir -p "$PVCASE"

 cp -f "$CASE_DIR/case.foam" "$PVCASE/"
 cp -a "$CASE_DIR/system" "$PVCASE/"
 cp -a "$CASE_DIR/constant" "$PVCASE/"

 if [ -d "$CASE_DIR/0" ]; then
     mkdir -p "$PVCASE/0"
     cp -a "$CASE_DIR/0/." "$PVCASE/0/"
     printf '0\n' > "$PVCASE/initialTime.txt"

     mkdir -p "$RESULTS_DIR/temp/initialTime"
     cp -a "$CASE_DIR/0/." \
         "$RESULTS_DIR/temp/initialTime/"
     printf '0\n' > "$RESULTS_DIR/temp/initialTime.txt"
 fi

 latest=$(python3 "$ROOT/scripts/select_restart_time.py")

 if [ -n "${latest:-}" ] &&
    [ -d "$CASE_DIR/$latest" ]; then

     mkdir -p "$PVCASE/$latest"
     cp -a "$CASE_DIR/$latest/." "$PVCASE/$latest/"
     printf '%s\n' "$latest" > "$PVCASE/latestTime.txt"

     mkdir -p "$RESULTS_DIR/temp/latestTime"
     cp -a "$CASE_DIR/$latest/." \
         "$RESULTS_DIR/temp/latestTime/"
     printf '%s\n' "$latest" \
         > "$RESULTS_DIR/temp/latestTime.txt"
 fi

 cat > "$PVCASE/README.txt" <<EOF
Open this directory as an OpenFOAM case in ParaView.
Initial time: 0
Latest complete time: ${latest:-not found}
Example from WSL:
cd $PVCASE
/usr/bin/paraview case.foam
EOF

 if [ -d "$CASE_DIR/postProcessing" ]; then
     cp -a "$CASE_DIR/postProcessing" \
         "$RESULTS_DIR/temp/"
 fi

 if [ -d "$CASE_DIR/VTK" ]; then
     cp -a "$CASE_DIR/VTK" \
         "$RESULTS_DIR/temp/"
 fi

 if [ -d "$RESULTS_DIR/slices_vtk" ]; then
     cp -a "$RESULTS_DIR/slices_vtk" \
         "$RESULTS_DIR/temp/"
 fi

 if [ -f "$RESULTS_DIR/FormulaStudent_results.xlsx" ]; then
     cp -f "$RESULTS_DIR/FormulaStudent_results.xlsx" \
         "$RESULTS_DIR/temp/"
 fi

 for f in \
     log.blockMesh \
     log.snappyHexMesh \
     log.checkMesh \
     "log.$SOLVER" \
     log.foamToVTK; do

     if [ -f "$CASE_DIR/$f" ]; then
         cp -f "$CASE_DIR/$f" \
             "$RESULTS_DIR/temp/"
     fi
 done

 echo "Copied latest complete time: ${latest:-none}"
 echo "ParaView case copy: $PVCASE"
}

continue_case() {
    local restart_time

    restart_time=$(
        python3 "$ROOT/scripts/select_restart_time.py"
    )

    log_step "Selected complete restart time: $restart_time"

    log_step "Validate restart compatibility"
    python3 "$ROOT/scripts/validate_restart.py" \
        --time "$restart_time"

    log_step "Archive incomplete times after $restart_time"
    python3 "$ROOT/scripts/archive_incomplete_times.py" \
        --after "$restart_time"

    log_step "Configure restart from $restart_time"
    python3 "$ROOT/scripts/apply_solver_control.py" \
        --mode continue \
        --restart-time "$restart_time"

    log_step "Apply operating conditions to $restart_time"
    python3 "$ROOT/scripts/apply_operating_conditions.py" \
        --time "$restart_time" \
        --workflow continue

    log_step "Validate restart after operating conditions"
    python3 "$ROOT/scripts/validate_restart.py" \
        --time "$restart_time"

    cd "$CASE_DIR"

    log_step "Continue solver: $SOLVER"

    if [ "$PARALLEL" = "true" ]; then
        python3 "$ROOT/scripts/generate_decompose_par.py"
        decomposePar -force 2>&1 | tee log.decomposePar_continue

        mpirun -np "$NPROCS" "$SOLVER" -parallel \
            2>&1 | tee "log.${SOLVER}_continue"

        reconstructPar -latestTime \
            2>&1 | tee log.reconstructPar_continue
    else
        "$SOLVER" \
            2>&1 | tee "log.${SOLVER}_continue"
    fi

    cd "$ROOT"

    log_step "Postprocess continued solution"
    postprocess

    copy_temp
}

mapped_restart_case() {
    local source_time
    local source_root
    local source_case
    local stamp

    source_time=$(
        python3 "$ROOT/scripts/select_restart_time.py"
    )

    log_step "Select mappedRestart source: $source_time"

    python3 "$ROOT/scripts/validate_restart.py" \
        --time "$source_time"

    stamp=$(date +%Y%m%d_%H%M%S)

    source_root="$RESULTS_DIR/mappedRestart_sources/${stamp}_from_${source_time}"
    source_case="$source_root/sourceCase"

    log_step "Create mappedRestart source snapshot"
    python3 "$ROOT/scripts/create_mapped_restart_source.py" \
        --time "$source_time" \
        --output "$source_case"

    log_step "Clear old target time directories"
    python3 "$ROOT/scripts/clear_numeric_times.py"

    log_step "Prepare new target case"
    prepare

    log_step "Generate new target mesh"
    mesh

    log_step "Create mapFieldsDict"
    python3 "$ROOT/scripts/create_map_fields_dict.py"

    cd "$CASE_DIR"

    log_step "mapFields from source time $source_time"
    mapFields "$source_case" \
        -sourceTime "$source_time" \
        2>&1 | tee log.mapFields

    cd "$ROOT"

    log_step "Promote mapped fields to source time"
    python3 "$ROOT/scripts/promote_mapped_time.py" \
        --time "$source_time"

    log_step "Validate mapped fields"
    python3 "$ROOT/scripts/validate_restart.py" \
        --time "$source_time"

    log_step "Configure mapped solver restart"
    python3 "$ROOT/scripts/apply_solver_control.py" \
        --mode continue \
        --restart-time "$source_time"

    log_step "Apply operating conditions to mapped fields"
    python3 "$ROOT/scripts/apply_operating_conditions.py" \
        --time "$source_time" \
        --workflow mappedRestart

    log_step "Validate mapped fields after operating conditions"
    python3 "$ROOT/scripts/validate_restart.py" \
        --time "$source_time"

    cd "$CASE_DIR"

    log_step "Mapped solver: $SOLVER"

    if [ "$PARALLEL" = "true" ]; then
        python3 "$ROOT/scripts/generate_decompose_par.py"
        decomposePar -force 2>&1 | tee log.decomposePar_mappedRestart

        mpirun -np "$NPROCS" "$SOLVER" -parallel \
            2>&1 | tee "log.${SOLVER}_mappedRestart"

        reconstructPar -latestTime \
            2>&1 | tee log.reconstructPar_mappedRestart
    else
        "$SOLVER" \
            2>&1 | tee "log.${SOLVER}_mappedRestart"
    fi

    cd "$ROOT"

    log_step "Postprocess mapped solution"
    postprocess

    copy_temp
}

case "$MODE" in
 config)
     echo "CFD_CONFIG=$CFD_CONFIG"
     echo "CFD_MANIFEST=$CFD_MANIFEST"
     echo "CASE_DIR=$CASE_DIR"
     echo "RESULTS_DIR=$RESULTS_DIR"
     echo "SOLVER=$SOLVER"
     exit 0
     ;;
 mesh) prepare; mesh;;
 solve) solve;;
 full) prepare; mesh; solve; postprocess; copy_temp;;
 postprocess) postprocess; copy_temp;;
 continue) continue_case;;
 mappedRestart) mapped_restart_case;;
 *) echo "Usage: $0 mesh|solve|full|postprocess|continue|mappedRestart"; exit 2;;
esac
echo
echo "=== Workflow completed: $MODE ==="
