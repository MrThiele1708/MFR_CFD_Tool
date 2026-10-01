# Installationsleitfaden (Deutsch)

**FormulaStudentCFD_v0_8 – Kurz- und Bedienungsanleitung**

# Was wird benötigt?

Die Simulation läuft unter Linux/WSL mit OpenFOAM 13. Die Projektdateien können unter Windows gespeichert und über Google Drive verteilt werden, die Berechnung sollte aber innerhalb des Linux-Dateisystems von WSL erfolgen, zum Beispiel unter ~/FormulaStudentCFD_v0_8.

- Windows 10 oder Windows 11 mit WSL2.
- Ubuntu innerhalb von WSL2.
- OpenFOAM 13 inklusive MPI, ParaView/pvpython, blockMesh, snappyHexMesh, checkMesh, topoSet, mapFields und foamToVTK.
- Python 3 mit venv-Unterstützung.
# Projekt entpacken

```bash
cd ~
unzip FormulaStudentCFD_v0_8_package.zip
cd FormulaStudentCFD_v0_8
```

Der genaue Name des entpackten Ordners kann abweichen. Entscheidend ist, dass die Datei scripts/run_production.sh innerhalb des Projektordners existiert.

# OpenFOAM prüfen

```bash
source /opt/openfoam13/etc/bashrc
foamVersion
which blockMesh
which snappyHexMesh
which mapFields
which pvpython
```

Wenn OpenFOAM an einem anderen Pfad installiert ist, muss der Pfad in scripts/run_case.sh und scripts/run_surface_features.sh angepasst werden.

# Python-Umgebung einrichten

```bash
cd ~/FormulaStudentCFD_v0_8
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
chmod +x scripts/*.sh scripts/*.py
```

# Installation prüfen

```bash
python3 -m py_compile scripts/*.py
bash -n scripts/run_case.sh
./scripts/run_production.sh config
./scripts/run_single_part.sh config
```

Der config-Modus startet keine Simulation. Er zeigt nur, welche Konfiguration und welche Case-/Ergebnisordner verwendet werden.

# Erste kurze Prüfung

```bash
ALLOW_MESH_WARNINGS=true \
./scripts/run_production.sh mesh
```

Für die erste Prüfung kann ein schnelles Mesh verwendet werden. Meshwarnungen dürfen zu Testzwecken explizit erlaubt werden. Für endgültige Ergebnisse sollte später ohne ALLOW_MESH_WARNINGS=true gerechnet werden.

# Wichtige Regeln

- Die virtuelle Umgebung .venv nicht zwischen Rechnern kopieren; auf jedem Rechner neu erzeugen.
- Produktions- und Single-Part-Wrapper nicht vermischen.
- Geometrieänderungen nicht direkt im case-Ordner durchführen.
- Die STL-Dateien immer in den dafür vorgesehenen geometry-Ordner legen.