#!/usr/bin/env python3

from pathlib import Path
import json

from config_utils import load_config, case_dir

ROOT = Path(__file__).resolve().parents[1]
config = load_config()
case = case_dir(config)

effective = case / "effective.json"
effective_config = (
    json.loads(effective.read_text(encoding="utf-8"))
    if effective.exists()
    else config
)

metrics = json.loads(
    (case / "constant/geometryMetrics.json").read_text(
        encoding="utf-8"
    )
)

rho = effective_config.get("air", {}).get("rho", 1.2041)
speed = effective_config.get("flow", {}).get("speed", 13.889)
length = effective_config.get("reference", {}).get("length", 1.0)
area = effective_config.get("reference", {}).get("area", 1.0)

moment = metrics.get("momentCenter", [0.0, 0.0, 0.0])
active = sorted(set(metrics.get("patches", [])))

groups = {
    "total": active,
    "body": ["body", "driver", "rollhoop"],
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

solver_config = effective_config.get("solver", {})

configured_end_time = solver_config.get(
    "steadyEndTime",
    150,
)

configured_write_interval = solver_config.get(
    "steadyWriteInterval",
    10,
)

blocks = []

for name, patches in groups.items():
    blocks.append(
        f"""
{name}
{{
    type forceCoeffs;
    libs ("libforces.so");
    patches ({" ".join(patches)});
    rho rhoInf;
    rhoInf {rho};
    CofR ({moment[0]} {moment[1]} {moment[2]});
    dragDir (1 0 0);
    sideDir (0 1 0);
    liftDir (0 0 1);
    pitchAxis (0 1 0);
    yawAxis (0 0 1);
    rollAxis (1 0 0);
    magUInf {speed};
    lRef {length};
    Aref {area};
    writeControl timeStep;
    writeInterval 50;
}}"""
    )

text = f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object controlDict;
}}

application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {configured_end_time};
deltaT 1;
writeControl timeStep;
writeInterval {configured_write_interval};
purgeWrite 5;

functions
{{
{''.join(blocks)}

    residuals
    {{
        type residuals;
        libs ("libutilityFunctionObjects.so");
        fields (p U k omega);
    }}

    yPlus
    {{
        type yPlus;
        libs ("libfieldFunctionObjects.so");
        writeControl writeTime;
    }}
}}
"""

output = case / "system/controlDict"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(text, encoding="utf-8")

print("Generated controlDict for patches:", active)
