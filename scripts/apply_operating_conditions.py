#!/usr/bin/env python3
import os

from pathlib import Path
import argparse
import math
import re

import trimesh
import yaml

from restart_utils import latest_complete_time

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--time",
    default=None,
    help="Explicit complete solver time, for example 1600",
)
parser.add_argument(
    "--workflow",
    choices=("continue", "mappedRestart", "manual"),
    default="continue",
    help="Workflow context for geometry-change reporting",
)
args = parser.parse_args()


def _matching_brace(text, open_pos):
    depth = 0
    in_string = False
    escaped = False

    for index in range(open_pos, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index

    raise SystemExit("Unclosed OpenFOAM dictionary block")


def replace_patch(text, patch, block):
    boundary_match = re.search(
        r"\bboundaryField\s*\{",
        text,
    )

    if not boundary_match:
        raise SystemExit("boundaryField block not found in U")

    boundary_open = text.find(
        "{",
        boundary_match.start(),
        boundary_match.end(),
    )

    key_pattern = re.compile(
        r'\s*("([^"]+)"|([A-Za-z_][A-Za-z0-9_.-]*))\s*\{'
    )

    depth = 1
    index = boundary_open + 1

    while index < len(text):
        if depth == 1:
            key_match = key_pattern.match(text, index)

            if key_match:
                key = key_match.group(2) or key_match.group(3)
                patch_open = key_match.end() - 1
                patch_close = _matching_brace(text, patch_open)

                if key == patch:
                    return (
                        text[:key_match.start()]
                        + block
                        + text[patch_close + 1:]
                    )

                index = patch_close + 1
                continue

        char = text[index]

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break

        index += 1

    raise SystemExit(f"Patch not found in U: {patch}")


config = yaml.safe_load(
    (Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(
        encoding="utf-8"
    )
)

case = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

if args.time is None:
    time = latest_complete_time(case)
else:
    time = case / args.time
    if not time.is_dir():
        raise SystemExit(f"Time directory does not exist: {time}")

ufile = time / "U"

if not ufile.exists():
    raise SystemExit(f"Missing U field: {ufile}")

flow = config.get("flow", {})
speed = float(flow.get("speed", 13.889))
yaw = math.radians(float(flow.get("yawAngle", 0.0)))
slip = float(flow.get("wheelSlip", 0.0))

vector = (
    -speed * math.cos(yaw),
    speed * math.sin(yaw),
    0.0,
)

vec = " ".join(f"{value:.9g}" for value in vector)

text = ufile.read_text(encoding="utf-8")

wall = (
    "{\n"
    "        type fixedValue;\n"
    f"        value uniform ({vec});\n"
    "    }"
)

text = replace_patch(text, "inlet", "    inlet " + wall)
text = replace_patch(text, "ground", "    ground " + wall)

diameter = float(
    config.get("vehicle", {}).get("tireDiameter", 0.410)
)

omega = speed / (diameter / 2.0) * (1.0 + slip)

for patch, filename in {
    "wheelFL": "wheel_FL.stl",
    "wheelFR": "wheel_FR.stl",
    "wheelRL": "wheel_RL.stl",
    "wheelRR": "wheel_RR.stl",
}.items():
    stl = ROOT / "case/constant/triSurface" / filename

    if not stl.exists():
        print("Missing wheel:", stl)
        continue

    mesh = trimesh.load(stl, force="mesh")
    center = mesh.bounds.mean(axis=0)
    origin = " ".join(f"{float(value):.9g}" for value in center)

    block = (
        "{\n"
        "        type rotatingWallVelocity;\n"
        f"        origin ({origin});\n"
        "        axis (0 1 0);\n"
        f"        omega {omega:.9g};\n"
        "        value uniform (0 0 0);\n"
        "    }"
    )

    text = replace_patch(
        text,
        patch,
        "    " + patch + " " + block,
    )

geometry = config.get("geometry", {})
geometry_changes = [
    key
    for key in (
        "rideHeight",
        "pitchAngle",
        "rollAngle",
        "steeringAngle",
    )
    if abs(float(geometry.get(key, 0.0))) > 1e-12
]

if geometry_changes:
    if args.workflow == "mappedRestart":
        print(
            "INFO: geometry parameters were changed and "
            "the case was remeshed for mappedRestart:",
            ", ".join(geometry_changes),
        )
    elif args.workflow == "continue":
        print(
            "INFO: continue assumes that the existing mesh "
            "already matches the geometry parameters:",
            ", ".join(geometry_changes),
        )
    else:
        print(
            "INFO: geometry parameters are nonzero:",
            ", ".join(geometry_changes),
        )

ufile.write_text(text, encoding="utf-8")

print("Updated operating conditions in:", ufile)
print("selectedTime:", time.name)
print("Uinf:", vector)
print("wheel omega:", omega, "rad/s")
