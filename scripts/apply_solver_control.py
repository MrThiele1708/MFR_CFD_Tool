#!/usr/bin/env python3
import os

"""Apply solver control settings from parameters.yaml."""

from pathlib import Path
import argparse
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--mode",
    choices=["fresh", "continue", "transient"],
    default="fresh",
)
parser.add_argument(
    "--restart-time",
    default=None,
    help="Explicit complete restart time",
)
args = parser.parse_args()

config = yaml.safe_load(
    (Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(
        encoding="utf-8"
    )
)

solver = config.get("solver", {})
mode = args.mode

if mode == "transient" or solver.get("mode", "steady") == "transient":
    application = solver.get("transient", "pimpleFoam")
    end_time = solver.get(
        "transientEndTime",
        solver.get("endTime", 5.0),
    )
    interval = solver.get(
        "transientWriteInterval",
        solver.get("writeInterval", 0.02),
    )
else:
    application = solver.get("steady", "simpleFoam")
    end_time = solver.get(
        "steadyEndTime",
        solver.get("endTime", 3000),
    )
    interval = solver.get(
        "steadyWriteInterval",
        solver.get("writeInterval", 200),
    )

if mode == "continue" and args.restart_time is not None:
    start_from = "startTime"
    start_time = str(args.restart_time)
elif mode == "continue":
    start_from = "latestTime"
    start_time = None
else:
    start_from = "startTime"
    start_time = "0"

control = ROOT / "case/system/controlDict"
text = control.read_text(encoding="utf-8")


def replace(pattern, value):
    global text

    text, count = re.subn(
        pattern,
        value,
        text,
        count=1,
    )

    if count != 1:
        print("Warning: entry not found:", pattern)


replace(
    r"application\s+\w+\s*;",
    f"application {application};",
)

replace(
    r"startFrom\s+\w+\s*;",
    f"startFrom {start_from};",
)

replace(
    r"stopAt\s+\w+\s*;",
    "stopAt endTime;",
)

if start_time is not None:
    replace(
        r"startTime\s+[^;]+\s*;",
        f"startTime {start_time};",
    )

replace(
    r"endTime\s+[^;]+\s*;",
    f"endTime {end_time};",
)

replace(
    r"writeControl\s+\w+\s*;",
    "writeControl timeStep;",
)

replace(
    r"writeInterval\s+[^;]+\s*;",
    f"writeInterval {interval};",
)

control.write_text(text, encoding="utf-8")

print(
    "Applied solver settings:",
    "mode=", mode,
    "application=", application,
    "startFrom=", start_from,
    "startTime=", start_time,
    "endTime=", end_time,
    "writeInterval=", interval,
)
