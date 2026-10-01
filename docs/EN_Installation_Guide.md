# Installation Guide (English)

**FormulaStudentCFD_v0_8 – Kurz- und Bedienungsanleitung**

# What is required?

The simulation runs under Linux/WSL with OpenFOAM 13. The project may be distributed through Google Drive, but the calculations should be performed inside the WSL Linux filesystem, for example under ~/FormulaStudentCFD_v0_8.

- Windows 10 or Windows 11 with WSL2.
- Ubuntu inside WSL2.
- OpenFOAM 13 with MPI, ParaView/pvpython, blockMesh, snappyHexMesh, checkMesh, topoSet, mapFields and foamToVTK.
- Python 3 with venv support.
# Extract and prepare the project

```bash
cd ~
unzip FormulaStudentCFD_v0_8_package.zip
cd FormulaStudentCFD_v0_8

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
chmod +x scripts/*.sh scripts/*.py
```

# Check OpenFOAM

```bash
source /opt/openfoam13/etc/bashrc
foamVersion
which blockMesh
which snappyHexMesh
which mapFields
which pvpython
```

If OpenFOAM is installed elsewhere, adjust the OpenFOAM source path in scripts/run_case.sh and scripts/run_surface_features.sh.

# Basic validation

```bash
python3 -m py_compile scripts/*.py
bash -n scripts/run_case.sh
./scripts/run_production.sh config
./scripts/run_single_part.sh config
```

The config mode does not run a solver. It only displays the selected configuration, case, results and manifest paths.

# Important rules

- Do not copy the .venv between computers; create it again on each computer.
- Keep production and single-part workflows separate.
- Do not edit generated files in case/ manually.
- Put STL files only into the documented geometry folders.