# Bedienungsanleitung (Deutsch)

**FormulaStudentCFD_v0_8 – Kurz- und Bedienungsanleitung**

# Einfachster Start: Assembly-Simulation

Für eine normale vollständige Assembly-Simulation genügt normalerweise der folgende Befehl:

```bash
./scripts/run_production.sh full
```

Dieser Ablauf bereitet die Geometrie vor, erzeugt das Mesh, startet den Solver und führt anschließend VTK-, Slice- und Excel-Postprocessing aus.

# Geometrie für den Assembly-Case

1. Die vollständige Fahrzeuggeometrie in geometry/production ablegen.
1. Die erforderlichen Produktions-STLs und assembly.stl müssen vorhanden sein.
1. Das Mapping wird bei aktivierter assemblyMapping-Konfiguration automatisch ausgeführt.
Das automatisch erzeugte Profil geometry/production_mapped muss normalerweise nicht manuell bearbeitet werden.

# Einfachster Start: Single-Part-Simulation

1. Genau eine STL-Datei in geometry/single_part ablegen.
1. Die Single-Part-Konfiguration und das Manifest müssen auf diese Datei zeigen.
1. Den Lauf mit dem Single-Part-Wrapper starten.
```bash
./scripts/run_single_part.sh full
```

Im Single-Part-Case sind Assembly-Mapping, Moving Ground und rotierende Räder deaktiviert. Der Einlass verwendet die Windgeschwindigkeit; der Boden ist eine Slip-Grenze.

# Die wichtigsten Modi

Befehl | Verwendung
--- | ---
run_production.sh full | Vollständiger Produktionslauf: Vorbereitung, Mesh, Solver, Postprocessing.
run_production.sh mesh | Nur Vorbereitung und Mesh. Kein Solver.
run_production.sh solve | Solver auf einem bereits vorhandenen Mesh.
run_production.sh continue | Fortsetzung mit identischem Mesh ab dem letzten vollständigen Zeitstand.
run_production.sh mappedRestart | Geometrie-/Meshänderung: neues Mesh, mapFields und Neustart.
run_production.sh postprocess | Nur VTK, Slices, Excel und Ergebnisablage.
run_single_part.sh ... | Dieselben Modi für den getrennten Single-Part-Case.

# Parallel rechnen

```bash
PARALLEL=true \
NPROCS=6 \
./scripts/run_production.sh full
```

PARALLEL=true verwendet decomposePar, MPI und reconstructPar. PARALLEL=false rechnet seriell. Für Fehlersuche ist seriell oft einfacher.

# Meshwarnungen

```bash
ALLOW_MESH_WARNINGS=true \
PARALLEL=true \
NPROCS=6 \
./scripts/run_production.sh mappedRestart
```

Diese Option ist nur für Integrationstests gedacht. Sie ersetzt keine Meshvalidierung.

# Parameter ändern

Parameter | Bedeutung
--- | ---
flow.speed | Windgeschwindigkeit in m/s, zum Beispiel 13.889.
flow.yawAngle | Gierwinkel der Anströmung in Grad.
flow.wheelSlip | Radschlupf als Faktor.
solver.steadyEndTime | Absolute Zieliteration.
solver.steadyWriteInterval | Abstand zwischen vollständigen Zeitständen.
geometry.rideHeight | Fahrzeug-/Karosserieanhebung in Metern.
geometry.pitchAngle | Nickwinkel in Grad.
geometry.rollAngle | Rollwinkel in Grad.
geometry.steeringAngle | Lenkwinkel in Grad.

Nach Änderung von speed, yawAngle, wheelSlip oder Endzeit kann continue verwendet werden. Nach Änderung von Geometrie, STL-Dateien, Meshleveln, Layern oder Refinement-Regionen muss mappedRestart oder full verwendet werden.

# ParaView öffnen

```bash
/usr/bin/paraview \
    results/temp/paraViewCase/case.foam
```

Für Single-Part:

```bash
/usr/bin/paraview \
    results_single_part/temp/paraViewCase/case.foam
```

Die physikalische OpenFOAM-Zeit steht in der ParaView-Zeitsteuerung. VTK-Dateinamen können bei Restarts relative Zeitindizes enthalten; das ist normal.

# Postprocessing und Ergebnisse

- Produktions-Excel: results/FormulaStudent_results.xlsx
- Single-Part-Excel: results_single_part/FormulaStudent_results.xlsx
- Produktions-Slices: results/slices_vtk/
- Single-Part-Slices: results_single_part/slices_vtk/
- Temporäre ParaView-Kopie: results/temp/paraViewCase/
- Single-Part-ParaView-Kopie: results_single_part/temp/paraViewCase/
- Solverlogs liegen im jeweiligen case-Ordner.
# Force- und Koeffizientendateien

- Rohkräfte: postProcessing/forces_total/.../forces.dat
- Kraftkoeffizienten: postProcessing/total/.../forceCoeffs.dat
Wenn forces.dat fehlt, muss forces_total vor dem Solverstart im controlDict vorhanden sein. Ein späteres Postprocessing kann fehlende Force-Daten nicht nachträglich erzeugen.
