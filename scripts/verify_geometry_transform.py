#!/usr/bin/env python3

from pathlib import Path
import math

import trimesh
import yaml

ROOT = Path(__file__).resolve().parents[1]

config = yaml.safe_load(
    (ROOT / "config/parameters.yaml").read_text(
        encoding="utf-8"
    )
)

manifest = yaml.safe_load(
    (ROOT / "config/geometryManifest.yaml").read_text(
        encoding="utf-8"
    )
)

profile = config["geometry"]["profile"]
source_dir = ROOT / "geometry" / profile
target_dir = ROOT / "case/constant/triSurface"

units = str(
    config["geometry"].get("inputUnits", "m")
).lower()

scale = (
    0.001
    if units in ("mm", "millimeter", "millimetre")
    else 1.0
)

geometry = config.get("geometry", {})
ride_height = float(
    geometry.get("rideHeight", 0.0)
)

pitch_angle = float(
    geometry.get("pitchAngle", 0.0)
)

roll_angle = float(
    geometry.get("rollAngle", 0.0)
)

steering_angle = float(
    geometry.get("steeringAngle", 0.0)
)

print("===== GEOMETRY TRANSFORM CHECK =====")
print("Profile:", profile)
print("Expected rideHeight:", ride_height, "m")
print("pitchAngle:", pitch_angle, "deg")
print("rollAngle:", roll_angle, "deg")
print("steeringAngle:", steering_angle, "deg")
print()

tolerance = 1e-7
failed = False

for key, spec in manifest["parts"].items():
    if not spec.get("include", True):
        continue

    filename = spec["file"]
    source_file = source_dir / filename
    target_file = target_dir / filename

    if not source_file.exists():
        print(key, "SOURCE MISSING:", source_file)
        failed = True
        continue

    if not target_file.exists():
        print(key, "TARGET MISSING:", target_file)
        failed = True
        continue

    source_mesh = trimesh.load(
        source_file,
        force="mesh",
    )
    source_mesh.apply_scale(scale)

    target_mesh = trimesh.load(
        target_file,
        force="mesh",
    )

    source_bounds = source_mesh.bounds
    target_bounds = target_mesh.bounds

    delta_min = target_bounds[0] - source_bounds[0]
    delta_max = target_bounds[1] - source_bounds[1]

    source_center = source_bounds.mean(axis=0)
    target_center = target_bounds.mean(axis=0)
    delta_center = target_center - source_center

    print(
        f"{key:20s}"
        f" dMin=({delta_min[0]: .8f},"
        f" {delta_min[1]: .8f},"
        f" {delta_min[2]: .8f})"
        f" dMax=({delta_max[0]: .8f},"
        f" {delta_max[1]: .8f},"
        f" {delta_max[2]: .8f})"
        f" dCenter=({delta_center[0]: .8f},"
        f" {delta_center[1]: .8f},"
        f" {delta_center[2]: .8f})"
    )

    # For the isolated rideHeight test, all points should
    # move by the same amount in z.
    if (
        abs(pitch_angle) < 1e-12
        and abs(roll_angle) < 1e-12
        and abs(steering_angle) < 1e-12
    ):
        group = spec.get("group", "unsprung")
        expected = ride_height if group == "sprung" else 0.0

        if (
            abs(float(delta_min[2]) - expected) > tolerance
            or abs(float(delta_max[2]) - expected) > tolerance
        ):
            print(
                f"  EXPECTED z-shift for group {group}: "
                f"{expected:.8f} m"
            )
            failed = True

if failed:
    print()
    print("GEOMETRY TRANSFORM CHECK: FAILED")
    raise SystemExit(1)

print()
print("GEOMETRY TRANSFORM CHECK: PASSED")
