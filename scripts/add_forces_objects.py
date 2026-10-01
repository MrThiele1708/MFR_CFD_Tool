#!/usr/bin/env python3

from pathlib import Path
import json
import re

from config_utils import load_config, case_dir

ROOT = Path(__file__).resolve().parents[1]
config = load_config()
case = case_dir(config)

control = case / "system/controlDict"
metrics_path = case / "constant/geometryMetrics.json"

if not control.exists():
    raise SystemExit(f"Missing controlDict: {control}")

if not metrics_path.exists():
    raise SystemExit(f"Missing geometry metrics: {metrics_path}")

text = control.read_text(encoding="utf-8")
metrics = json.loads(
    metrics_path.read_text(encoding="utf-8")
)

active = sorted(set(metrics.get("patches", [])))

if not active:
    raise SystemExit("No active patches found.")

groups = {
    "total": active,
    "body": [
        "body",
        "driver",
        "rollhoop",
    ],
    "frontWing": ["frontWing"],
    "rearWing": ["rearWing"],
    "counterWings": [
        "counterWingLeft",
        "counterWingRight",
    ],
    "diffuser": ["diffuser"],
    "underbody": ["underbody"],
    "sidepods": [
        "sidepodLeft",
        "sidepodRight",
    ],
    "suspension": [
        "suspensionFL",
        "suspensionFR",
        "suspensionRL",
        "suspensionRR",
    ],
    "wheels": [
        "wheelFL",
        "wheelFR",
        "wheelRL",
        "wheelRR",
    ],
}

groups = {
    name: [
        patch
        for patch in patches
        if patch in active
    ]
    for name, patches in groups.items()
}

groups = {
    name: patches
    for name, patches in groups.items()
    if patches
}

rho = float(
    config.get("air", {}).get("rho", 1.2041)
)

center = metrics.get(
    "momentCenter",
    [0.0, 0.0, 0.0],
)

blocks = []

for name, patches in groups.items():
    object_name = f"forces_{name}"

    exists = re.search(
        rf"(?m)^[ \t]*{re.escape(object_name)}[ \t]*\{{",
        text,
    )

    if exists:
        print("Already present:", object_name)
        continue

    blocks.append(
        f"""
{object_name}
{{
    type forces;
    libs ("libforces.so");
    patches ({" ".join(patches)});
    rho rhoInf;
    rhoInf {rho};
    CofR ({center[0]} {center[1]} {center[2]});
    writeControl timeStep;
    writeInterval 50;
}}
"""
    )

if not blocks:
    print("No missing force objects.")
    raise SystemExit(0)

position = text.rfind("}")

if position < 0:
    raise SystemExit(
        "controlDict closing brace not found."
    )

control.write_text(
    text[:position]
    + "".join(blocks)
    + text[position:],
    encoding="utf-8",
)

print(
    "Added force objects:",
    ", ".join(
        f"forces_{name}"
        for name in groups
    ),
)
