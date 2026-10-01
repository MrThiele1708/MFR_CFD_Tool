#!/usr/bin/env python3

from pathlib import Path
import sys

from config_utils import (
    load_config,
    case_dir,
    results_dir,
    manifest_path,
)

config = load_config()

if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: select_project_path.py "
        "case|results|manifest"
    )

kind = sys.argv[1]

if kind == "case":
    print(case_dir(config))
elif kind == "results":
    print(results_dir(config))
elif kind == "manifest":
    print(manifest_path(config))
else:
    raise SystemExit(
        f"Unknown path type: {kind}"
    )
