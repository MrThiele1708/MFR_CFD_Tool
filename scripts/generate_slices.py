#!/usr/bin/env python3

from pathlib import Path
import json

from paraview.simple import *
from paraview import servermanager


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case"

metrics = json.loads(
    (CASE / "constant" / "geometryMetrics.json").read_text(
        encoding="utf-8"
    )
)

config = json.loads(
    (CASE / "effective.json").read_text(
        encoding="utf-8"
    )
)

rho = float(config["air"]["rho"])
u_inf = float(config["flow"]["speed"])
image_width = int(config["postProcessing"]["imageWidth"])
image_height = int(config["postProcessing"]["imageHeight"])

output_root = ROOT / "results" / "slices"
output_root.mkdir(parents=True, exist_ok=True)

reader = OpenFOAMReader(
    FileName=str(CASE / "case.foam")
)

reader.MeshRegions = ["internalMesh"]
reader.CellArrays = ["p", "U"]

latest_time = max(reader.TimestepValues)
print("Using latest OpenFOAM time:", latest_time)

UpdatePipeline(
    time=latest_time,
    proxy=reader
)

point_data = CellDatatoPointData(
    Input=reader
)

UpdatePipeline(
    time=latest_time,
    proxy=point_data
)

merged_data = MergeBlocks(
    Input=point_data
)

UpdatePipeline(
    time=latest_time,
    proxy=merged_data
)


# Show vehicle surfaces as a grey contour.
view = CreateView("RenderView")
view.ViewSize = [image_width, image_height]
view.Background = [1.0, 1.0, 1.0]

stl_sources = []

for stl_file in sorted(
    (CASE / "constant" / "triSurface").glob("*.stl")
):
    if "radiator" in stl_file.name:
        continue

    try:
        stl = STLReader(
            FileNames=[str(stl_file)]
        )
        stl_display = Show(stl, view)
        stl_display.DiffuseColor = [0.45, 0.45, 0.45]
        stl_display.Opacity = 0.55
        stl_sources.append(stl)
    except Exception as error:
        print("Could not load contour:", stl_file, error)


field_specs = [
    (
        "pressure",
        "pOverInlet",
        f'inputs[0].PointData["p"] * {rho}',
        [-100.0, 100.0],
    ),
    (
        "velocity",
        "velocityMagnitude",
        (
            'mag(inputs[0].PointData["U"])'
        ),
        [8.0, 16.0],
    ),
    (
        "totalPressure",
        "totalPressureOverInlet",
        (
            f'inputs[0].PointData["p"] * {rho} + '
            f'0.5 * {rho} * mag(inputs[0].PointData["U"])**2 - '
            f'0.5 * {rho} * {u_inf}**2'
        ),
        [-100.0, 100.0],
    ),
]


bbox = metrics["bbox_m"]
vehicle_front_x = float(bbox[1][0])
vehicle_length = float(metrics["vehicleLength"])
vehicle_width = float(metrics["vehicleWidth"])
vehicle_height = float(metrics["vehicleHeight"])

slice_start = float(
    config["postProcessing"]["sliceStart"]
)
slice_spacing = float(
    config["postProcessing"]["sliceSpacing"]
)
slice_end = vehicle_length + float(
    config["postProcessing"]["sliceBehind"]
)

slice_positions = []
s = slice_start

while s <= slice_end + 1e-9:
    slice_positions.append((s, vehicle_front_x - s))
    s += slice_spacing

print("Number of slice stations:", len(slice_positions))

for station_index, (s, x_position) in enumerate(slice_positions):

    slice_filter = Slice(
        Input=merged_data
    )

    slice_filter.SliceType = "Plane"
    slice_filter.SliceType.Origin = [
        x_position,
        0.0,
        0.0,
    ]
    slice_filter.SliceType.Normal = [
        1.0,
        0.0,
        0.0,
    ]

    UpdatePipeline(
        time=latest_time,
        proxy=slice_filter
    )

    for folder, array_name, expression, limits in field_specs:

        output_folder = output_root / folder
        output_folder.mkdir(
            parents=True,
            exist_ok=True
        )


        calculator = PythonCalculator(
            Input=slice_filter
        )

        calculator.ArrayAssociation = "Point Data"
        calculator.ArrayName = array_name
        calculator.Expression = expression

        UpdatePipeline(
            time=latest_time,
            proxy=calculator
        )

        display = Show(
            calculator,
            view
        )

        ColorBy(
            display,
            ("POINTS", array_name)
        )

        lookup_table = GetColorTransferFunction(
            array_name
        )

        lookup_table.RescaleTransferFunction(
            float(limits[0]),
            float(limits[1])
        )

        lookup_table.ApplyPreset(
            "Cool to Warm",
            True
        )

        display.SetScalarBarVisibility(
            view,
            True
        )

        view.CameraPosition = [
            x_position + 10.0,
            0.0,
            0.5 * vehicle_height,
        ]

        view.CameraFocalPoint = [
            x_position,
            0.0,
            0.5 * vehicle_height,
        ]

        view.CameraViewUp = [
            0.0,
            0.0,
            1.0,
        ]

        view.CameraParallelScale = max(
            vehicle_width * 0.8,
            1.0
        )

        image_path = (
            output_folder
            / f"slice_{station_index:03d}_s_{s:+.2f}.png"
        )

        SaveScreenshot(
            str(image_path),
            view,
            ImageResolution=[
                image_width,
                image_height,
            ],
        )

        Hide(
            calculator,
            view
        )

        Delete(calculator)

    Delete(slice_filter)

for stl in stl_sources:
    Delete(stl)

Delete(merged_data)
Delete(point_data)
Delete(reader)

print(
    "Slice generation completed:",
    len(slice_positions) * len(field_specs),
    "images"
)
