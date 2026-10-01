# FormulaStudentCFD v0.1

OpenFOAM Foundation 13 framework for Formula Student external aerodynamics. The included STL files are procedural demo geometry only. Keep real Siemens NX STL files locally and replace the files in `geometry/production/`.

Quick start in Ubuntu:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/make_demo_geometry.py
python3 scripts/prepare_case.py
./scripts/run_straight.sh
```

Read `docs/INSTALLATION.md`, `docs/CAD_WORKFLOW.md` and `docs/STUDIES.md` before using production geometry.
