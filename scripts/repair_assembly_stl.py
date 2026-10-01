#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil

import trimesh

from config_utils import load_config

ROOT = Path(__file__).resolve().parents[1]
config = load_config()

mapping = config.get("geometry", {}).get(
    "assemblyMapping",
    {},
)

if not bool(mapping.get("enabled", False)):
    print("Assembly mapping disabled; repair skipped.")
    raise SystemExit(0)

source_profile = mapping.get(
    "sourceProfile",
    "production",
)

assembly_file = mapping.get(
    "assemblyFile",
    "assembly.stl",
)

assembly_path = (
    ROOT / "geometry" / source_profile / assembly_file
)

if not assembly_path.exists():
    raise SystemExit(
        f"Assembly STL not found: {assembly_path}"
    )

# Check the raw STL without processing.
raw = trimesh.load(
    assembly_path,
    force="mesh",
    process=False,
)

print("Raw assembly:")
print("  triangles:", len(raw.faces))
print("  watertight:", raw.is_watertight)
print("  winding:", raw.is_winding_consistent)

if raw.is_watertight and raw.is_winding_consistent:
    print("Assembly already normalized.")
    raise SystemExit(0)

# Keep a backup of the original raw STL.
backup_dir = (
    ROOT
    / "results"
    / "geometry_backups"
)
backup_dir.mkdir(parents=True, exist_ok=True)

stamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

backup_path = (
    backup_dir
    / f"{assembly_file}.raw_{stamp}.stl"
)

shutil.copy2(
    assembly_path,
    backup_path,
)

print("Raw assembly backup:", backup_path)

# Let Trimesh merge coincident vertices and repair
# the indexed surface representation.
repaired = trimesh.load(
    assembly_path,
    force="mesh",
    process=True,
)

repaired.remove_unreferenced_vertices()
repaired.fix_normals()

print("Processed assembly:")
print("  triangles:", len(repaired.faces))
print("  watertight:", repaired.is_watertight)
print("  winding:", repaired.is_winding_consistent)

if not repaired.is_watertight:
    raise SystemExit(
        "Processed assembly is still not watertight."
    )

temporary = assembly_path.with_suffix(
    ".repaired.tmp.stl"
)

repaired.export(temporary)
temporary.replace(assembly_path)

print("Repaired assembly written:", assembly_path)
