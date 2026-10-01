#!/usr/bin/env python3
import os

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))
SYSTEM = CASE / "system"

config = yaml.safe_load(
    (Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(
        encoding="utf-8"
    )
)

radiator = config.get("radiator", {}) or {}
enabled = bool(radiator.get("enabled", False))

topo_path = SYSTEM / "topoSetDict"
fv_path = SYSTEM / "fvOptions"

if not enabled:
    topo_path.unlink(missing_ok=True)
    fv_path.unlink(missing_ok=True)
    print("Radiator disabled; removed radiator source files.")
    raise SystemExit(0)

manifest = yaml.safe_load(
    (Path(os.environ.get("CFD_MANIFEST", str(ROOT / "config/geometryManifest.yaml")))).read_text(
        encoding="utf-8"
    )
)

radiator_parts = radiator.get(
    "parts",
    {
        "radiatorLeft": "radiator_left_volume.stl",
        "radiatorRight": "radiator_right_volume.stl",
    },
)

darcy = float(radiator.get("darcy", 1000.0))
forchheimer = float(
    radiator.get("forchheimer", 10.0)
)

for key, filename in radiator_parts.items():
    path = CASE / "constant/triSurface" / filename

    if not path.exists():
        raise SystemExit(
            f"Radiator STL missing: {path}"
        )

topo_actions = []
fv_blocks = []

for key, filename in radiator_parts.items():
    cells_name = f"{key}Cells"

    topo_actions.append(
        f"""
    {{
        name {cells_name};
        type cellSet;
        action new;
        source surfaceToCell;
        sourceInfo
        {{
            file "constant/triSurface/{filename}";
            outsidePoints ((0 0 0));
            includeInside true;
            curvature 0.3;
            includeOutside false;
            includeCut true;
            nearDistance 1e-6;
        }}
    }}

    {{
        name {key};
        type cellZoneSet;
        action new;
        source setToCellZone;
        sourceInfo
        {{
            set {cells_name};
        }}
    }}
"""
    )

    fv_blocks.append(
        f"""
{key}Porosity
{{
    type explicitPorositySource;
    active yes;

    explicitPorositySourceCoeffs
    {{
        selectionMode cellZone;
        cellZone {key};

        type DarcyForchheimer;

        DarcyForchheimerCoeffs
        {{
            d ({darcy} {darcy} {darcy});
            f ({forchheimer} {forchheimer} {forchheimer});

            coordinateSystem
            {{
                type cartesian;
                origin (0 0 0);

                coordinateRotation
                {{
                    type axesRotation;
                    e1 (1 0 0);
                    e2 (0 1 0);
                }}
            }}
        }}
    }}
}}
"""
    )

topo_text = f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object topoSetDict;
}}

actions
(
{''.join(topo_actions)}
);
"""

fv_text = f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object fvOptions;
}}

{''.join(fv_blocks)}
"""

SYSTEM.mkdir(parents=True, exist_ok=True)
topo_path.write_text(topo_text, encoding="utf-8")
fv_path.write_text(fv_text, encoding="utf-8")

print("Created:", topo_path)
print("Created:", fv_path)
print("Darcy coefficient:", darcy)
print("Forchheimer coefficient:", forchheimer)
