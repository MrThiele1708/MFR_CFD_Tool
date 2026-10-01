# User Guide (English)

**FormulaStudentCFD_v0_8 – Kurz- und Bedienungsanleitung**

# Simplest start: Assembly simulation

```bash
./scripts/run_production.sh full
```

This prepares the geometry, creates the mesh, runs the solver, and performs VTK, slice and Excel postprocessing.

# Assembly geometry

1. Put the complete vehicle geometry into geometry/production.
1. Make sure assembly.stl and the required production component STLs exist.
1. Assembly mapping is run automatically when enabled in the configuration.
# Simplest start: Single-part simulation

1. Put exactly one STL into geometry/single_part.
1. Make sure the single-part manifest refers to that file.
1. Run the separated single-part workflow.
```bash
./scripts/run_single_part.sh full
```

The single-part workflow disables assembly mapping, moving ground and rotating wheels. The inlet uses the configured wind speed and the ground uses a slip condition.

# Main run modes

Command | Purpose
--- | ---
run_production.sh full | Complete production workflow: prepare, mesh, solver, postprocessing.
run_production.sh mesh | Prepare and generate the mesh only.
run_production.sh solve | Run the solver on an existing mesh.
run_production.sh continue | Continue from the latest complete time using the same mesh.
run_production.sh mappedRestart | Build a new mesh, map fields with mapFields and continue.
run_production.sh postprocess | Run only VTK, slices, Excel and result packaging.
run_single_part.sh ... | The same modes for the separated single-part case.

# Parallel execution

```bash
PARALLEL=true \
NPROCS=6 \
./scripts/run_production.sh full
```

PARALLEL=true uses decomposePar, MPI and reconstructPar. PARALLEL=false runs serially and is often easier for debugging.

# Mesh warnings

```bash
ALLOW_MESH_WARNINGS=true \
PARALLEL=true \
NPROCS=6 \
./scripts/run_production.sh mappedRestart
```

Use this only for integration tests. It is not a production mesh validation.

# Changing parameters

Parameter | Meaning
--- | ---
flow.speed | Freestream speed in m/s, for example 13.889.
flow.yawAngle | Yaw angle of the incoming flow in degrees.
flow.wheelSlip | Wheel slip factor.
solver.steadyEndTime | Absolute target iteration.
solver.steadyWriteInterval | Interval between complete field time directories.
geometry.rideHeight | Body/vehicle height change in metres.
geometry.pitchAngle | Pitch angle in degrees.
geometry.rollAngle | Roll angle in degrees.
geometry.steeringAngle | Steering angle in degrees.

Use continue after flow or target-time changes that do not change the mesh. Use mappedRestart or full after geometry, STL, mesh-level, layer or refinement changes.

# Opening ParaView

```bash
/usr/bin/paraview \
    results/temp/paraViewCase/case.foam
```

For the single-part case:

```bash
/usr/bin/paraview \
    results_single_part/temp/paraViewCase/case.foam
```

VTK filenames can contain a relative restart index instead of the physical OpenFOAM time. The physical time is shown in the ParaView time control and the OpenFOAM log.

# Postprocessing and results

- Production Excel: results/FormulaStudent_results.xlsx
- Single-part Excel: results_single_part/FormulaStudent_results.xlsx
- Production slices: results/slices_vtk/
- Single-part slices: results_single_part/slices_vtk/
- Temporary ParaView copy: results/temp/paraViewCase/
- Single-part ParaView copy: results_single_part/temp/paraViewCase/
- Solver logs are stored in the corresponding case directory.
# Forces and coefficients

- Raw forces: postProcessing/forces_total/.../forces.dat
- Force coefficients: postProcessing/total/.../forceCoeffs.dat
If forces.dat is missing, forces_total must be present in controlDict before the solver starts. Postprocessing cannot recreate missing force data.
