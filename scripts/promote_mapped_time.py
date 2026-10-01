#!/usr/bin/env python3
import os

from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

parser = argparse.ArgumentParser()
parser.add_argument(
    "--time",
    required=True,
    help="Mapped source time, for example 1630",
)
args = parser.parse_args()

source = CASE / "0"
initial = CASE / "0.orig"
target = CASE / args.time

if not source.is_dir():
    raise SystemExit(f"Mapped target directory missing: {source}")

if not initial.is_dir():
    raise SystemExit(f"Initial target directory missing: {initial}")

if target.exists():
    raise SystemExit(
        f"Target time already exists and will not be overwritten: {target}"
    )

print(f"Promoting mapped fields: {source} -> {target}")
shutil.move(str(source), str(target))

print(f"Restoring initial target fields: {initial} -> {source}")
shutil.copytree(initial, source)

print("Mapped target-time promotion completed.")
print("Mapped solver time:", args.time)
