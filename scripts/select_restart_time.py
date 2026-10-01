#!/usr/bin/env python3
import os

from pathlib import Path
import sys

from restart_utils import latest_complete_time

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

try:
    print(latest_complete_time(CASE).name)
except Exception as exc:
    print(f"Restart-time selection failed: {exc}", file=sys.stderr)
    sys.exit(1)
