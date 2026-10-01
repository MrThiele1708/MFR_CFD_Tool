#!/usr/bin/env python3

from pathlib import Path
import os

from config_utils import load_config, case_dir

config = load_config()
case = case_dir(config)

solver = config.get("solver", {})

nprocs = int(
    os.environ.get(
        "NPROCS",
        solver.get("nProcs", 6),
    )
)

method = solver.get(
    "decompositionMethod",
    "scotch",
)

text = f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object decomposeParDict;
}}

numberOfSubdomains {nprocs};
method {method};
"""

output = case / "system/decomposeParDict"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(text, encoding="utf-8")

print("Generated:", output)
print("numberOfSubdomains:", nprocs)
print("method:", method)
