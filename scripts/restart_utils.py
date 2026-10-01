#!/usr/bin/env python3

from pathlib import Path
import re

REQUIRED_FIELDS = ("U", "p", "k", "omega", "nut")
NUMERIC_TIME_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
)


def numeric_time_directories(case):
    result = []

    for path in case.iterdir():
        if not path.is_dir():
            continue

        if not NUMERIC_TIME_PATTERN.fullmatch(path.name):
            continue

        result.append((float(path.name), path))

    return sorted(result, key=lambda item: item[0])


def is_complete_time(path):
    return all(
        (path / field).is_file()
        for field in REQUIRED_FIELDS
    )


def complete_time_directories(case):
    return [
        (value, path)
        for value, path in numeric_time_directories(case)
        if is_complete_time(path)
    ]


def latest_complete_time(case):
    complete = complete_time_directories(case)

    if not complete:
        raise RuntimeError(
            "No complete solver time directory found. "
            f"Required fields: {', '.join(REQUIRED_FIELDS)}"
        )

    return complete[-1][1]

# Backward-compatible alias used by existing helper scripts.
is_complete = is_complete_time
