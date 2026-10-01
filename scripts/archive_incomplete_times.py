#!/usr/bin/env python3
import os

from pathlib import Path
from datetime import datetime
import argparse
import shutil

from restart_utils import numeric_time_directories, is_complete

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument("--after", required=True, help="Restart time")
parser.add_argument(
    "--archive-root",
    default="results/restart_archives",
)
args = parser.parse_args()

case = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))
after = float(args.after)

targets = []

for value, path in numeric_time_directories(case):
    if value <= after:
        continue

    if is_complete_time := is_complete(path):
        print("KEEP complete time:", path.name)
        continue

    targets.append(path)

if not targets:
    print("No incomplete time directories require archiving.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
archive_dir = ROOT / args.archive_root / f"after_{args.after}_{stamp}"
archive_dir.mkdir(parents=True, exist_ok=True)

for path in targets:
    destination = archive_dir / f"{path.name}_incomplete"
    print("ARCHIVE:", path, "->", destination)
    shutil.move(str(path), str(destination))

print("Archived incomplete directories in:", archive_dir)
