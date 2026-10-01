#!/usr/bin/env python3
import os

from pathlib import Path
import argparse
import shutil

from restart_utils import latest_complete_time, is_complete_time

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

parser = argparse.ArgumentParser()
parser.add_argument("--time", default=None)
parser.add_argument("--output", required=True)
args = parser.parse_args()

if args.time is None:
    source_time = latest_complete_time(CASE)
else:
    source_time = CASE / args.time

if not source_time.is_dir():
    raise SystemExit(f"Source time directory missing: {source_time}")

if not is_complete_time(source_time):
    raise SystemExit(
        f"Source time is incomplete: {source_time.name}"
    )

output = Path(args.output).resolve()

if output.exists():
    raise SystemExit(
        f"Mapped-restart source already exists: {output}"
    )

source_mesh = CASE / "constant/polyMesh"
source_control = CASE / "system/controlDict"

if not source_mesh.is_dir():
    raise SystemExit(f"Source mesh missing: {source_mesh}")

if not source_control.is_file():
    raise SystemExit(f"Source controlDict missing: {source_control}")

(output / "constant").mkdir(parents=True, exist_ok=True)
(output / "system").mkdir(parents=True, exist_ok=True)
(output / source_time.name).mkdir(parents=True, exist_ok=True)

shutil.copytree(
    source_mesh,
    output / "constant/polyMesh",
)

shutil.copy2(
    source_control,
    output / "system/controlDict",
)

# Core restart fields. phi is copied when available.
fields = ("U", "p", "k", "omega", "nut", "phi")

for field in fields:
    source = source_time / field

    if source.is_file():
        shutil.copy2(
            source,
            output / source_time.name / field,
        )
        print("Copied source field:", field)

(output / "sourceTime.txt").write_text(
    source_time.name + "\n",
    encoding="utf-8",
)

print("Mapped-restart source created:", output)
print("Source time:", source_time.name)
