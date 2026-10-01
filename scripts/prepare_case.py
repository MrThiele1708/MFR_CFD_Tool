#!/usr/bin/env python3
import os

from pathlib import Path
import json
import math

import trimesh
import yaml

ROOT = Path(__file__).resolve().parents[1]

config = yaml.safe_load(
    (Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(
        encoding="utf-8"
    )
)

manifest = yaml.safe_load(
    (Path(os.environ.get("CFD_MANIFEST", str(ROOT / "config/geometryManifest.yaml")))).read_text(
        encoding="utf-8"
    )
)

profile = config["geometry"]["profile"]
source_dir = ROOT / "geometry" / profile
case_dir = ROOT / config["project"]["case"]
tri_dir = case_dir / "constant" / "triSurface"

tri_dir.mkdir(parents=True, exist_ok=True)

for path in tri_dir.glob("*.stl"):
    path.unlink()

units = str(
    config["geometry"].get("inputUnits", "m")
).lower()

scale = (
    0.001
    if units in ("mm", "millimeter", "millimetre")
    else 1.0
)

geometry = config.get("geometry", {})

contact_aware_enabled = bool(
    geometry.get("contactAwareMorph", {})
    .get("enabled", False)
)
ride_height = float(geometry.get("rideHeight", 0.0))
pitch_angle = float(geometry.get("pitchAngle", 0.0))
roll_angle = float(geometry.get("rollAngle", 0.0))
steering_angle = float(
    geometry.get("steeringAngle", 0.0)
)

loaded = {}

for key, spec in manifest["parts"].items():
    source_file = source_dir / spec["file"]

    if not source_file.exists():
        print("MISSING:", source_file)
        continue

    mesh = trimesh.load(
        source_file,
        force="mesh",
        process=False,
    )

    mesh.apply_scale(scale)
    loaded[key] = mesh

if not loaded:
    raise SystemExit("No geometry parts could be loaded.")

# Moment center from the wheelbase before transformations.
centers = {
    key: mesh.bounds.mean(axis=0)
    for key, mesh in loaded.items()
}

front_centers = [
    centers[key]
    for key in ("wheelFL", "wheelFR")
    if key in centers
]

rear_centers = [
    centers[key]
    for key in ("wheelRL", "wheelRR")
    if key in centers
]

moment_center = [0.0, 0.0, 0.0]

if front_centers and rear_centers:
    front_x = sum(
        float(point[0])
        for point in front_centers
    ) / len(front_centers)

    rear_x = sum(
        float(point[0])
        for point in rear_centers
    ) / len(rear_centers)

    moment_center = [
        0.5 * (front_x + rear_x),
        0.0,
        0.0,
    ]

# Apply vehicle-level transformations only to sprung parts.
for key, mesh in loaded.items():
    spec = manifest["parts"][key]

    if not spec.get("include", True):
        continue

    group = spec.get("group", "unsprung")

    if group == "sprung" and not contact_aware_enabled:
        roll_transform = (
            trimesh.transformations.rotation_matrix(
                math.radians(roll_angle),
                [1.0, 0.0, 0.0],
                moment_center,
            )
        )

        pitch_transform = (
            trimesh.transformations.rotation_matrix(
                math.radians(pitch_angle),
                [0.0, 1.0, 0.0],
                moment_center,
            )
        )

        mesh.apply_transform(
            pitch_transform @ roll_transform
        )

        mesh.apply_translation(
            [0.0, 0.0, ride_height]
        )

    # Steering rotates only the front wheels around their own centers.
    if (
        key in ("wheelFL", "wheelFR")
        and abs(steering_angle) > 1e-12
    ):
        wheel_center = mesh.bounds.mean(axis=0)

        steering_transform = (
            trimesh.transformations.rotation_matrix(
                math.radians(steering_angle),
                [0.0, 0.0, 1.0],
                wheel_center,
            )
        )

        mesh.apply_transform(steering_transform)


    target_file = tri_dir / spec["file"]
    mesh.export(target_file)
    print("Exported:", target_file)

metrics_meshes = [
    mesh
    for key, mesh in loaded.items()
    if manifest["parts"][key].get("include", True)
]

combined = trimesh.util.concatenate(metrics_meshes)
bounds = combined.bounds

metrics = {
    "profile": profile,
    "bbox_m": bounds.tolist(),
    "vehicleLength": float(combined.extents[0]),
    "vehicleWidth": float(combined.extents[1]),
    "vehicleHeight": float(combined.extents[2]),
    "momentCenter": [
        float(value)
        for value in moment_center
    ],
    "patches": sorted(
        set(
            spec["patch"]
            for spec in manifest["parts"].values()
            if spec.get("include", True)
        )
    ),
    "transformations": {
        "rideHeight": ride_height,
        "pitchAngle": pitch_angle,
        "rollAngle": roll_angle,
        "steeringAngle": steering_angle,
    },
}

metrics_path = (
    case_dir / "constant" / "geometryMetrics.json"
)

metrics_path.write_text(
    json.dumps(metrics, indent=2),
    encoding="utf-8",
)

print(json.dumps(metrics, indent=2))
