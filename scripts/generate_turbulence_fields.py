#!/usr/bin/env python3

from pathlib import Path

import yaml

from config_utils import (
    load_config,
    load_manifest,
    case_dir,
)

config = load_config()
manifest = load_manifest(config)
case = case_dir(config)

zero_dir = case / "0.orig"
zero_dir.mkdir(parents=True, exist_ok=True)

flow = config.get("flow", {})
speed = float(flow.get("speed", 13.889))
intensity = float(
    flow.get("turbulenceIntensity", 0.01)
)

k_value = 1.5 * (
    speed * intensity
) ** 2

omega_value = 1.0

boundary_parts = sorted(
    {
        spec["patch"]
        for spec in manifest.get("parts", {}).values()
        if spec.get("include", True)
    }
)

boundary_conditions = config.get(
    "boundaryConditions",
    {}
)

ground_condition = boundary_conditions.get(
    "groundCondition",
    "fixedValue",
)


def ground_entry(body, value):
    if ground_condition == "slip":
        return "type zeroGradient;"

    return (
        f"type {body}; "
        f"value uniform {value};"
    )


def scalar_field(name, dimensions, internal, wall_type):
    part_entries = []

    for patch in boundary_parts:
        part_entries.append(
            f"""
    {patch}
    {{
        type {wall_type};
        value uniform {internal};
    }}"""
        )

    ground = ground_entry(
        wall_type,
        internal,
    )

    text = f"""FoamFile
{{
    version 2.0;
    format ascii;
    class volScalarField;
    object {name};
}}

dimensions {dimensions};
internalField uniform {internal};

boundaryField
{{
    inlet
    {{
        type fixedValue;
        value uniform {internal};
    }}

    outlet
    {{
        type inletOutlet;
        inletValue uniform {internal};
        value uniform {internal};
    }}

    ground
    {{
        {ground}
    }}

    top
    {{
        type zeroGradient;
    }}

    sideLeft
    {{
        type zeroGradient;
    }}

    sideRight
    {{
        type zeroGradient;
    }}
{''.join(part_entries)}
}}
"""

    (zero_dir / name).write_text(
        text,
        encoding="utf-8",
    )


scalar_field(
    "k",
    "[0 2 -2 0 0 0 0]",
    k_value,
    "kqRWallFunction",
)

scalar_field(
    "omega",
    "[0 0 -1 0 0 0 0]",
    omega_value,
    "omegaWallFunction",
)

scalar_field(
    "nut",
    "[0 2 -1 0 0 0 0]",
    0.0,
    "nutkWallFunction",
)

print("Generated turbulence fields in:", zero_dir)
print("Active vehicle patches:", boundary_parts)
print("Ground condition:", ground_condition)
