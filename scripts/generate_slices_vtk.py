#!/usr/bin/env python3
from pathlib import Path
import os
import json
import re
from paraview.simple import *

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

metrics = json.loads(
    (CASE / "constant/geometryMetrics.json").read_text(encoding="utf-8")
)
config = json.loads(
    (CASE / "effective.json").read_text(encoding="utf-8")
)

vtk_files = sorted(
    (CASE / "VTK").glob("case_*.vtk"),
    key=lambda p: float(p.stem.split("_")[-1]),
)
if not vtk_files:
    raise RuntimeError("No VTK case file found. Run foamToVTK -latestTime first.")

reader = LegacyVTKReader(FileNames=[str(vtk_files[-1])])
UpdatePipeline()
point_data = CellDatatoPointData(Input=reader)
UpdatePipeline()

rho = float(config["air"]["rho"])
uinf = float(config["flow"]["speed"])
width = int(config["postProcessing"]["imageWidth"])
height = int(config["postProcessing"]["imageHeight"])

out = Path(os.environ.get("CFD_RESULTS", str(ROOT / "results"))) / "slices_vtk"
out.mkdir(parents=True, exist_ok=True)

bbox = metrics["bbox_m"]
xfront = float(bbox[1][0])
vehicle_length = float(metrics["vehicleLength"])
vehicle_width = float(metrics["vehicleWidth"])
vehicle_height = float(metrics["vehicleHeight"])

start = float(config["postProcessing"]["sliceStart"])
spacing = float(config["postProcessing"]["sliceSpacing"])
end = vehicle_length + float(config["postProcessing"]["sliceBehind"])

stations = []
s = start
while s <= end + 1e-9:
    stations.append((s, xfront - s))
    s += spacing

fields = [
    (
        "pressure",
        "pOverInlet",
        f'inputs[0].PointData["p"] * {rho}',
        (-100.0, 100.0),
    ),
    (
        "velocity",
        "velocityMagnitude",
        'mag(inputs[0].PointData["U"])',
        (8.0, 16.0),
    ),
    (
        "totalPressure",
        "totalPressureOverInlet",
        (
            f'inputs[0].PointData["p"] * {rho} + '
            f'0.5 * {rho} * mag(inputs[0].PointData["U"])**2 - '
            f'0.5 * {rho} * {uinf}**2'
        ),
        (-100.0, 100.0),
    ),
]

view = CreateView("RenderView")
view.ViewSize = [width, height]
view.Background = [0.92, 0.92, 0.92]

stl_files = [
    f for f in sorted((CASE / "constant/triSurface").glob("*.stl"))
    if "radiator" not in f.name
]

for index, (s, x) in enumerate(stations):
    field_slice = Slice(Input=point_data)
    field_slice.SliceType = "Plane"
    field_slice.SliceType.Origin = [x, 0.0, 0.0]
    field_slice.SliceType.Normal = [1.0, 0.0, 0.0]
    UpdatePipeline(proxy=field_slice)

    contour_objects = []
    for stl_file in stl_files:
        source = STLReader(FileNames=[str(stl_file)])
        contour = Slice(Input=source)
        contour.SliceType = "Plane"
        contour.SliceType.Origin = [x, 0.0, 0.0]
        contour.SliceType.Normal = [1.0, 0.0, 0.0]
        UpdatePipeline(proxy=contour)
        contour_display = Show(contour, view)
        contour_display.DiffuseColor = [0.45, 0.45, 0.45]
        contour_display.Opacity = 0.85
        contour_display.SetScalarBarVisibility(view, False)
        contour_objects.append((source, contour))

    for folder, array_name, expression, limits in fields:
        output_folder = out / folder
        output_folder.mkdir(parents=True, exist_ok=True)

        calculator = PythonCalculator(Input=field_slice)
        calculator.ArrayAssociation = "Point Data"
        calculator.ArrayName = array_name
        calculator.Expression = expression
        UpdatePipeline(proxy=calculator)

        display = Show(calculator, view)
        ColorBy(display, ("POINTS", array_name))
        display.SetScalarBarVisibility(view, True)

        lookup = GetColorTransferFunction(array_name)
        lookup.ApplyPreset("Cool to Warm", True)
        lookup.RescaleTransferFunction(float(limits[0]), float(limits[1]))

        view.CameraPosition = [x + 10.0, 0.0, 0.5 * vehicle_height]
        view.CameraFocalPoint = [x, 0.0, 0.5 * vehicle_height]
        view.CameraViewUp = [0.0, 0.0, 1.0]
        view.CameraParallelScale = max(vehicle_width * 0.8, 1.0)

        image = output_folder / f"slice_{index:03d}_s_{s:+.2f}.png"
        SaveScreenshot(str(image), view, ImageResolution=[width, height])

        Hide(calculator, view)
        Delete(calculator)

    for source, contour in contour_objects:
        Delete(contour)
        Delete(source)
    Delete(field_slice)

Delete(point_data)
Delete(reader)
print("Clipped VTK slice generation completed:", len(stations) * len(fields), "images")
