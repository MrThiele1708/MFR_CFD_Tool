#!/usr/bin/env python3
import os

from pathlib import Path
import shutil

from restart_utils import numeric_time_directories

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

for value, path in numeric_time_directories(CASE):
    if value <= 0:
        continue

    print("Removing target time directory:", path)
    shutil.rmtree(path)

print("Numeric target time directories cleared.")
