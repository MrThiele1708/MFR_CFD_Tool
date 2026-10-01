# FormulaStudentCFD_v0_8 distribution

## Requirements

- Ubuntu or WSL2
- OpenFOAM 13 available at `/opt/openfoam13/etc/bashrc`
- Python 3.10 or newer
- OpenMPI for optional parallel runs
- ParaView/pvpython for postprocessing

## Installation

From the extracted project root:

```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

The installer creates `.venv` and installs `requirements.txt`. OpenFOAM and
ParaView are external system dependencies and are not installed by pip.

## Geometry

Production source geometry belongs in `geometry/production/`.
Single-Part geometry belongs in `geometry/single_part/`. For Single-Part,
place exactly one STL in that directory. The workflow automatically updates
the Single-Part manifest to the actual STL filename.

## Production commands

```bash
./scripts/run_production.sh config
ALLOW_MESH_WARNINGS=true ./scripts/run_production.sh mesh
ALLOW_MESH_WARNINGS=true ./scripts/run_production.sh full
```

`full` starts the configured solver after mesh generation. Use `mesh` first
and inspect `checkMesh` before using `full`.

## Single-Part commands

```bash
./scripts/run_single_part.sh config
ALLOW_MESH_WARNINGS=true ./scripts/run_single_part.sh mesh
ALLOW_MESH_WARNINGS=true ./scripts/run_single_part.sh full
```

Production and Single-Part cases/results are kept separate. Do not mix their
configuration, geometry, case or results directories.

## Parallel execution

```bash
PARALLEL=true NPROCS=6 ALLOW_MESH_WARNINGS=true \
    ./scripts/run_production.sh mesh
```

## Results

Generated cases and results are intentionally not included in this source
ZIP. They are produced locally by the workflows under `case/`,
`case_single_part/`, `results/` and `results_single_part/`.

The current production workflow uses position-only surface point mapping and
global rigid-transition assembly morphing. `flippedFaces` are reported as a
configured warning, while watertightness, boundary edges and non-manifold
edges remain geometry gates. `ALLOW_MESH_WARNINGS=true` is required to
continue past non-fatal `checkMesh` warnings.
